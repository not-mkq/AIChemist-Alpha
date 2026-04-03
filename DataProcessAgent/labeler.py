"""
labeler.py

从 config/label-config.json 读取 label 规则，
对某个 project/batch 下的所有文件打标签，
或者为单个文件手动设置标签。

约定：
- config/label-config.json 结构示例：

  {
    "regex": {
      "LSV": "LSV-.*\\.txt$",
      "CV": "CV-.*\\.txt$"
    },
    "wildcard": {
      "RAW_BIN": "*.bin",
      "JSON": "*.json"
    }
  }

- "regex" 块：使用标准正则表达式，作用目标是文件名（basename）
- "wildcard" 块：使用 fnmatch 通配符，作用目标同样是文件名（basename）
- 每个文件最多只保留一个 label（第一个匹配到的规则）
- 重跑批量打标签会覆盖原有标签
- 手动设置标签也会覆盖原有标签，但只允许使用 config 里定义过的 label
"""

import json
import re
import os
from fnmatch import fnmatch
from pathlib import Path
from typing import List, Optional, Set, Dict

import sqlite3

from db import add_file_label, get_connection


# 项目根目录 = 本文件所在目录
BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config" / "label-config.json"


class LabelRule:
    """封装一条 label 规则：label + pattern + 类型(regex / wildcard)。"""

    def __init__(self, label: str, pattern: str, rule_type: str):
        self.label = label
        self.pattern = pattern
        self.rule_type = rule_type  # "regex" or "wildcard"
        self._compiled: Optional[re.Pattern] = None

        if self.rule_type == "regex":
            try:
                self._compiled = re.compile(pattern)
            except Exception as e:
                print(f"[LABEL] ERROR: Invalid regex pattern for label '{label}': {pattern} ({e})")
                self._compiled = None
        elif self.rule_type == "wildcard":
            # wildcard 使用 fnmatch，不需要预编译
            self._compiled = None
        else:
            raise ValueError(f"Unknown rule_type: {rule_type}")

    def matches(self, rel_path: str) -> bool:
        """
        判断给定 rel_path 是否匹配该规则。
        !!! 重要修改：统一只以 basename 匹配，不考虑路径 !!!
        """
        filename = os.path.basename(rel_path)

        if self.rule_type == "regex":
            if not self._compiled:
                return False
            ok = self._compiled.search(filename) is not None
            print(f"[LABEL-DEBUG][regex] label={self.label} pattern={self.pattern} "
                  f"filename={filename} -> {ok}")
            return ok

        else:
            # wildcard: 使用 fnmatch 匹配文件名
            ok = fnmatch(filename, self.pattern)
            print(f"[LABEL-DEBUG][wildcard] label={self.label} pattern={self.pattern} "
                  f"filename={filename} -> {ok}")
            return ok



def load_label_rules(config_path: Path = CONFIG_PATH) -> List[LabelRule]:
    """
    从 config/label-config.json 读取规则列表。

    JSON 结构约定：
    {
      "regex":    { "LABEL1": "pattern1", ... },
      "wildcard": { "LABEL2": "*.bin",   ... }
    }

    返回所有规则组成的列表；如果文件不存在或为空，返回空列表。
    """
    if not config_path.exists():
        print(f"[LABEL] Config file not found: {config_path}, skip labeling.")
        return []

    try:
        with config_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[LABEL] Failed to load config file {config_path}: {e}")
        return []

    rules: List[LabelRule] = []

    regex_block = data.get("regex", {}) or {}
    wildcard_block = data.get("wildcard", {}) or {}

    # regex 规则
    if isinstance(regex_block, dict):
        for label, pattern in regex_block.items():
            if pattern:
                try:
                    rules.append(
                        LabelRule(
                            label=str(label),
                            pattern=str(pattern),
                            rule_type="regex",
                        )
                    )
                except re.error as e:
                    print(f"[LABEL] Invalid regex for label '{label}': {pattern} ({e})")
    else:
        print("[LABEL] 'regex' block is not a dict, ignored.")

    # wildcard 规则
    if isinstance(wildcard_block, dict):
        for label, pattern in wildcard_block.items():
            if pattern:
                rules.append(
                    LabelRule(
                        label=str(label),
                        pattern=str(pattern),
                        rule_type="wildcard",
                    )
                )
    else:
        print("[LABEL] 'wildcard' block is not a dict, ignored.")

    # 为了结果可预期，把规则按 (rule_type, label) 排一下（可选）
    rules.sort(key=lambda r: (r.rule_type, r.label))

    print(f"[LABEL] Loaded {len(rules)} rules from {config_path}")
    return rules


def get_valid_labels(config_path: Path = CONFIG_PATH) -> Set[str]:
    """
    从 label-config.json 中读取所有合法 label 名。
    如果没有规则或文件不存在，返回空集合。
    """
    rules = load_label_rules(config_path=config_path)
    return {r.label for r in rules}


def find_label_for_path(rel_path: str, rules: List[LabelRule]) -> Optional[str]:
    """
    给定文件的 rel_path 和规则列表，返回匹配到的 label。

    策略：
    - 依次遍历 rules，遇到第一个 matches 的规则就返回其 label
    - 若没有规则匹配，则返回 None
    - 我们假设用户不会写冲突规则，如果写了，先匹配到的那条生效
    """
    for rule in rules:
        if rule.matches(rel_path):
            return rule.label
    return None


def label_files_for_batch(
    project_name: str,
    batch_name: str,
    conn: Optional[sqlite3.Connection] = None,
    config_path: Path = CONFIG_PATH,
) -> None:
    """
    对某个 project/batch 下的所有文件打标签。

    过程：
    1. 从 label-config.json 加载规则
    2. 查询 files 表中该 batch 下的所有记录
    3. 对每个文件，根据 rel_path 匹配规则，得到 label（或 None）
    4. 对每个文件：
       - 先 DELETE 该文件在 file_labels 中的所有记录
       - 若有 label，则插入新的 (project, batch, item, filename, label)

    如果 config 文件不存在或没有规则，则直接返回。
    """
    rules = load_label_rules(config_path=config_path)
    if not rules:
        # 没有规则，直接跳过
        return

    owns_conn = False
    if conn is None:
        conn = get_connection()
        owns_conn = True

    try:
        cur = conn.cursor()

        # 查询该 batch 下的所有文件
        cur.execute(
            """
            SELECT item_name, filename, rel_path
            FROM files
            WHERE project_name = ? AND batch_name = ?;
            """,
            (project_name, batch_name),
        )
        rows = cur.fetchall()

        print(f"[LABEL] Labeling project={project_name}, batch={batch_name}, files={len(rows)}")

        for row in rows:
            item_name = row["item_name"]
            filename = row["filename"]
            rel_path = row["rel_path"]

            # 根据 rel_path 找 label
            label = find_label_for_path(rel_path, rules)

            # 每次重跑 label 就覆盖：先删掉旧的，再插入新的（如果有）
            conn.execute(
                """
                DELETE FROM file_labels
                WHERE project_name = ?
                  AND batch_name   = ?
                  AND item_name    = ?
                  AND filename     = ?;
                """,
                (project_name, batch_name, item_name, filename),
            )

            if label is not None:
                add_file_label(
                    conn=conn,
                    project_name=project_name,
                    batch_name=batch_name,
                    item_name=item_name,
                    filename=filename,
                    label=label,
                )
                print(f"[LABEL] {rel_path} -> {label}")
            else:
                print(f"[LABEL] {rel_path} -> <no match>")

        conn.commit()
    finally:
        if owns_conn:
            conn.close()


def set_label_for_file(
    project_name: str,
    batch_name: str,
    item_name: str,
    filename: str,
    label: str,
    conn: Optional[sqlite3.Connection] = None,
    config_path: Path = CONFIG_PATH,
) -> None:
    """
    底层接口：给单个文件设置指定的 label。

    规则：
    - label 必须出现在 config/label-config.json 中（无论在 regex 还是 wildcard 块里）
    - 如果 label 不在配置中：打印报错日志，不修改数据库
    - 如果在配置中：
        - 先删除该文件原有的所有 file_labels 记录
        - 再插入一条新的 (project, batch, item, filename, label)

    同样遵守“一文件仅一个 label”的约束。
    """
    valid_labels = get_valid_labels(config_path=config_path)

    if not valid_labels:
        print(
            f"[LABEL-SET] No labels configured in {config_path}, "
            f"cannot set '{label}' for {project_name}/{batch_name}/{item_name}/{filename}"
        )
        return

    if label not in valid_labels:
        print(
            f"[LABEL-SET] Invalid label '{label}' for "
            f"{project_name}/{batch_name}/{item_name}/{filename}. "
            f"Allowed labels: {sorted(valid_labels)}"
        )
        return

    owns_conn = False
    if conn is None:
        conn = get_connection()
        owns_conn = True

    try:
        # 删掉这个文件原有的所有 label
        conn.execute(
            """
            DELETE FROM file_labels
            WHERE project_name = ?
              AND batch_name   = ?
              AND item_name    = ?
              AND filename     = ?;
            """,
            (project_name, batch_name, item_name, filename),
        )

        # 插入新的 label
        add_file_label(
            conn=conn,
            project_name=project_name,
            batch_name=batch_name,
            item_name=item_name,
            filename=filename,
            label=label,
        )

        conn.commit()
        print(
            f"[LABEL-SET] {project_name}/{batch_name}/{item_name}/{filename} -> {label}"
        )
    finally:
        if owns_conn:
            conn.close()


def label_project(
    project_name: str,
    config_path: Path = CONFIG_PATH,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, int]:
    """
    为某个项目下所有 batch 的文件重打标签（覆盖模式）。
    返回统计信息：{"batches": x, "files": y}
    """
    rules = load_label_rules(config_path=config_path)
    if not rules:
        print(f"[LABEL] No rules in {config_path}, skip labeling for project={project_name}")
        return {"batches": 0, "files": 0}

    owns_conn = False
    if conn is None:
        conn = get_connection()
        owns_conn = True

    batch_count = 0
    file_count = 0
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT batch_name FROM files WHERE project_name = ?;",
            (project_name,),
        )
        batches = [row["batch_name"] for row in cur.fetchall()]
        for batch in batches:
            label_files_for_batch(project_name, batch, conn=conn, config_path=config_path)
            batch_count += 1
            cur.execute(
                "SELECT COUNT(*) AS c FROM files WHERE project_name=? AND batch_name=?;",
                (project_name, batch),
            )
            row = cur.fetchone()
            file_count += row["c"] if row else 0
        return {"batches": batch_count, "files": file_count}
    finally:
        if owns_conn:
            conn.close()


def label_all_projects(config_path: Path = CONFIG_PATH, conn: Optional[sqlite3.Connection] = None) -> Dict[str, int]:
    """
    为所有项目的文件重打标签（覆盖模式）。
    返回统计信息：{"projects": p, "batches": b, "files": f}
    """
    owns_conn = False
    if conn is None:
        conn = get_connection()
        owns_conn = True

    try:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT project_name FROM files;")
        projects = [row["project_name"] for row in cur.fetchall()]
        stats = {"projects": 0, "batches": 0, "files": 0}
        for prj in projects:
            res = label_project(prj, config_path=config_path, conn=conn)
            stats["projects"] += 1
            stats["batches"] += res.get("batches", 0)
            stats["files"] += res.get("files", 0)
        return stats
    finally:
        if owns_conn:
            conn.close()


if __name__ == "__main__":
    # 简单手动测试入口（可选）
    print(f"Label config path: {CONFIG_PATH}")
    rules = load_label_rules()
    print(f"Valid labels: {sorted({r.label for r in rules})}")
