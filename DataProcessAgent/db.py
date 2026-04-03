"""
db.py

极简 SQLite 数据库封装：
- 使用 name 作为主键/联合主键
- 只包含 projects / batches / items / files / file_labels 五张表
- 不做额外冗余字段，也暂时不实现 label 逻辑，只提供基础接口

默认数据库文件放在项目根目录下的 data.db：
./data.db
"""

import sqlite3
import time
import random
from pathlib import Path
from typing import Optional

# 默认数据库路径：和 db.py 同级目录下的 data.db
DB_PATH = Path(__file__).with_name("data.db")


# =========================
# Retry Decorator
# =========================

def retry_on_lock(max_retries=10, initial_delay=0.1, backoff_factor=1.5):
    """
    Decorator to retry database operations when 'database is locked' error occurs.
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except sqlite3.OperationalError as e:
                    last_exception = e
                    if "locked" in str(e) and attempt < max_retries:
                        # Exponential backoff with jitter
                        sleep_time = delay + random.uniform(0, 0.1)
                        # print(f"[DB] Database locked, retrying {func.__name__} in {sleep_time:.2f}s (attempt {attempt + 1}/{max_retries})")
                        time.sleep(sleep_time)
                        delay *= backoff_factor
                        continue
                    raise e
            if last_exception:
                raise last_exception
        return wrapper
    return decorator


# =========================
# 连接 & 初始化
# =========================

def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """
    获取一个 SQLite 连接，并开启外键支持。
    调用者负责在合适的时候 conn.close()。
    """
    if db_path is None:
        db_path = str(DB_PATH)

    # 增加 timeout 到 60秒以应对高并发写入
    conn = sqlite3.connect(db_path, timeout=60.0)
    # 返回 dict-like 的行（可选）
    conn.row_factory = sqlite3.Row
    # 开启外键支持
    conn.execute("PRAGMA foreign_keys = ON;")
    # 开启 WAL 模式以支持并发读写
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def init_db(conn: Optional[sqlite3.Connection] = None) -> None:
    """
    初始化数据库：创建所有表和索引（如果不存在）。
    可以传入已有连接；不传则内部短暂打开一个连接。
    """
    owns_conn = False
    if conn is None:
        conn = get_connection()
        owns_conn = True

    try:
        cur = conn.cursor()

        # ---- projects ----
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                name        TEXT PRIMARY KEY,
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                description TEXT
            );
            """
        )

        # ---- batches ----
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS batches (
                project_name TEXT NOT NULL,
                name         TEXT NOT NULL,   -- batch 名，如 "Batch-xxxxxx"
                upload_type  TEXT NOT NULL,   -- "batch" | "item" | "files"
                created_at   TEXT NOT NULL DEFAULT (datetime('now')),

                PRIMARY KEY (project_name, name),

                FOREIGN KEY (project_name)
                    REFERENCES projects(name)
                    ON DELETE CASCADE
            );
            """
        )

        # ---- items ----
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                project_name TEXT NOT NULL,
                batch_name   TEXT NOT NULL,
                name         TEXT NOT NULL,   -- item 名，如 "DataItem-1" 或 "Item-xxxxxx"
                created_at   TEXT NOT NULL DEFAULT (datetime('now')),

                PRIMARY KEY (project_name, batch_name, name),

                FOREIGN KEY (project_name, batch_name)
                    REFERENCES batches(project_name, name)
                    ON DELETE CASCADE
            );
            """
        )

        # ---- files ----
        # 去掉 size_bytes / mime_type / checksum，只保留必要信息
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS files (
                project_name TEXT NOT NULL,
                batch_name   TEXT NOT NULL,
                item_name    TEXT NOT NULL,
                filename     TEXT NOT NULL,   -- 文件名本身，如 "LSV-2.txt"
                rel_path     TEXT NOT NULL,   -- 相对 project 根的路径："Batch-xxx/Item-yyy/LSV-2.txt"
                created_at   TEXT NOT NULL DEFAULT (datetime('now')),

                PRIMARY KEY (project_name, batch_name, item_name, filename),

                FOREIGN KEY (project_name, batch_name, item_name)
                    REFERENCES items(project_name, batch_name, name)
                    ON DELETE CASCADE
            );
            """
        )

        # ---- batch_files ----
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS batch_files (
                project_name TEXT NOT NULL,
                batch_name   TEXT NOT NULL,
                filename     TEXT NOT NULL,
                rel_path     TEXT NOT NULL,
                created_at   TEXT NOT NULL DEFAULT (datetime('now')),

                PRIMARY KEY (project_name, batch_name, filename),

                FOREIGN KEY (project_name, batch_name)
                    REFERENCES batches(project_name, name)
                    ON DELETE CASCADE
            );
            """
        )

        # ---- prj_files ----
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS prj_files (
                project_name TEXT NOT NULL,
                filename     TEXT NOT NULL,
                rel_path     TEXT NOT NULL,
                created_at   TEXT NOT NULL DEFAULT (datetime('now')),

                PRIMARY KEY (project_name, filename),

                FOREIGN KEY (project_name)
                    REFERENCES projects(name)
                    ON DELETE CASCADE
            );
            """
        )

        # ---- file_labels ----
        # 极简版：只存 (project, batch, item, filename, label)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS file_labels (
                project_name TEXT NOT NULL,
                batch_name   TEXT NOT NULL,
                item_name    TEXT NOT NULL,
                filename     TEXT NOT NULL,
                label        TEXT NOT NULL,

                PRIMARY KEY (project_name, batch_name, item_name, filename, label),

                FOREIGN KEY (project_name, batch_name, item_name, filename)
                    REFERENCES files(project_name, batch_name, item_name, filename)
                    ON DELETE CASCADE
            );
            """
        )

        # batch_file_labels
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS batch_file_labels (
                project_name TEXT NOT NULL,
                batch_name   TEXT NOT NULL,
                filename     TEXT NOT NULL,
                label        TEXT NOT NULL,

                PRIMARY KEY (project_name, batch_name, filename, label),

                FOREIGN KEY (project_name, batch_name, filename)
                    REFERENCES batch_files(project_name, batch_name, filename)
                    ON DELETE CASCADE
            );
            """
        )

        # prj_file_labels
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS prj_file_labels (
                project_name TEXT NOT NULL,
                filename     TEXT NOT NULL,
                label        TEXT NOT NULL,

                PRIMARY KEY (project_name, filename, label),

                FOREIGN KEY (project_name, filename)
                    REFERENCES prj_files(project_name, filename)
                    ON DELETE CASCADE
            );
            """
        )

        # ---- 一些轻量索引，方便查询 ----

        # 按项目查 batch
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_batches_project
            ON batches (project_name);
            """
        )

        # 按项目+batch 查 item
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_items_project_batch
            ON items (project_name, batch_name);
            """
        )

        # 按 label 查文件
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_file_labels_label
            ON file_labels (label);
            """
        )

        # ---- prj_config ----
        # 每个 project 一行，后续通过 ALTER TABLE ADD COLUMN tool_<tool_name> TEXT
        # 来为不同工具写入 JSON 配置
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS prj_config (
                project_name TEXT PRIMARY KEY
                -- 动态列: tool_<tool_name> TEXT
            );
            """
        )

        # ---- item_results ----
        # 每个 (project, batch, item) 一行，后续用 ALTER TABLE ADD COLUMN <result_col> TEXT
        # 来存放各种工具计算出的数值（字符串/JSON）
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS item_results (
                project_name TEXT NOT NULL,
                batch_name   TEXT NOT NULL,
                item_name    TEXT NOT NULL,

                PRIMARY KEY (project_name, batch_name, item_name),

                FOREIGN KEY (project_name, batch_name, item_name)
                    REFERENCES items(project_name, batch_name, name)
                    ON DELETE CASCADE
            );
            """
        )

        # ---- batch_results ----
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS batch_results (
                project_name TEXT NOT NULL,
                batch_name   TEXT NOT NULL,

                PRIMARY KEY (project_name, batch_name),

                FOREIGN KEY (project_name, batch_name)
                    REFERENCES batches(project_name, name)
                    ON DELETE CASCADE
            );
            """
        )

        # ---- prj_results ----
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS prj_results (
                project_name TEXT PRIMARY KEY,

                FOREIGN KEY (project_name)
                    REFERENCES projects(name)
                    ON DELETE CASCADE
            );
            """
        )

        # ---- tool run history tables ----
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tool_run_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                tool_instance TEXT NOT NULL,
                code_name TEXT NOT NULL,
                tool_type TEXT NOT NULL,
                project TEXT NOT NULL,
                batch TEXT,
                item TEXT,
                scope TEXT NOT NULL,
                iteration_index INTEGER NOT NULL DEFAULT 0,
                status TEXT,
                error_reason TEXT,
                extra TEXT,
                started_at TEXT NOT NULL DEFAULT (datetime('now')),
                finished_at TEXT
            );
            """
        )
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_tool_run_history_run
            ON tool_run_history (run_id, iteration_index);
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tool_run_history_item
            ON tool_run_history (project, batch, item);
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tool_run_file_inputs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                history_id INTEGER NOT NULL,
                param_name TEXT,
                label TEXT,
                filename TEXT,
                FOREIGN KEY (history_id)
                    REFERENCES tool_run_history(id)
                    ON DELETE CASCADE
            );
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tool_run_file_inputs_history
            ON tool_run_file_inputs (history_id);
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tool_run_result_inputs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                history_id INTEGER NOT NULL,
                param_name TEXT,
                result_col TEXT,
                value_json TEXT,
                FOREIGN KEY (history_id)
                    REFERENCES tool_run_history(id)
                    ON DELETE CASCADE
            );
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tool_run_result_inputs_history
            ON tool_run_result_inputs (history_id);
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tool_run_params (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                history_id INTEGER NOT NULL,
                param_name TEXT,
                value_json TEXT,
                FOREIGN KEY (history_id)
                    REFERENCES tool_run_history(id)
                    ON DELETE CASCADE
            );
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tool_run_params_history
            ON tool_run_params (history_id);
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tool_run_file_outputs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                history_id INTEGER NOT NULL,
                label TEXT,
                filename TEXT,
                FOREIGN KEY (history_id)
                    REFERENCES tool_run_history(id)
                    ON DELETE CASCADE
            );
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tool_run_file_outputs_history
            ON tool_run_file_outputs (history_id);
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tool_run_result_outputs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                history_id INTEGER NOT NULL,
                result_col TEXT,
                value_json TEXT,
                FOREIGN KEY (history_id)
                    REFERENCES tool_run_history(id)
                    ON DELETE CASCADE
            );
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tool_run_result_outputs_history
            ON tool_run_result_outputs (history_id);
            """
        )

        # tool_codes 和 tool_instances 表已废弃，不再创建
        # 工具配置现在完全从文件系统读取（tool-instances/<profile>/ 和 tools/<type>/）

        # 提交
        conn.commit()
    finally:
        if owns_conn:
            conn.close()


# =========================
# 基本写接口（供 upload 使用）
# =========================

@retry_on_lock()
def create_project(
    conn: sqlite3.Connection,
    name: str,
    description: Optional[str] = None,
) -> None:
    """
    创建一个 project；如果已经存在则忽略（不会抛错）。
    你可以在上传前保证 project 已存在，也可以在第一次用到时自动创建。
    """
    conn.execute(
        """
        INSERT OR IGNORE INTO projects (name, description)
        VALUES (?, ?);
        """,
        (name, description),
    )
    conn.commit()


@retry_on_lock()
def create_batch(
    conn: sqlite3.Connection,
    project_name: str,
    batch_name: str,
    upload_type: str,
) -> None:
    """
    创建一个 batch。一条上传 = 一个 batch。
    要求 project 已经存在（否则会违反外键）。
    """
    conn.execute(
        """
        INSERT INTO batches (project_name, name, upload_type)
        VALUES (?, ?, ?);
        """,
        (project_name, batch_name, upload_type),
    )
    conn.commit()


@retry_on_lock()
def create_item(
    conn: sqlite3.Connection,
    project_name: str,
    batch_name: str,
    item_name: str,
) -> None:
    """
    在某个 batch 下创建一个 item。
    """
    conn.execute(
        """
        INSERT INTO items (project_name, batch_name, name)
        VALUES (?, ?, ?);
        """,
        (project_name, batch_name, item_name),
    )
    conn.commit()


@retry_on_lock()
def create_file(
    conn: sqlite3.Connection,
    project_name: str,
    batch_name: str,
    item_name: str,
    filename: str,
    rel_path: str,
) -> None:
    """
    创建一条 file 记录，对应一个真实文件：
    workspace/<project_name>/<rel_path>
    """
    conn.execute(
        """
        INSERT OR REPLACE INTO files (project_name, batch_name, item_name, filename, rel_path)
        VALUES (?, ?, ?, ?, ?);
        """,
        (project_name, batch_name, item_name, filename, rel_path),
    )
    conn.commit()


@retry_on_lock()
def create_batch_file(
    conn: sqlite3.Connection,
    project_name: str,
    batch_name: str,
    filename: str,
    rel_path: str,
) -> None:
    """
    在 batch_files 中创建记录。
    """
    conn.execute(
        """
        INSERT OR REPLACE INTO batch_files (project_name, batch_name, filename, rel_path)
        VALUES (?, ?, ?, ?);
        """,
        (project_name, batch_name, filename, rel_path),
    )
    conn.commit()


@retry_on_lock()
def create_prj_file(
    conn: sqlite3.Connection,
    project_name: str,
    filename: str,
    rel_path: str,
) -> None:
    """
    在 prj_files 中创建记录。
    """
    conn.execute(
        """
        INSERT OR REPLACE INTO prj_files (project_name, filename, rel_path)
        VALUES (?, ?, ?);
        """,
        (project_name, filename, rel_path),
    )
    conn.commit()


@retry_on_lock()
def add_file_label(
    conn: sqlite3.Connection,
    project_name: str,
    batch_name: str,
    item_name: str,
    filename: str,
    label: str,
) -> None:
    """
    为某个文件添加一个 label。
    这是个极简接口，不管来源/版本。
    """
    conn.execute(
        """
        INSERT OR REPLACE INTO file_labels
            (project_name, batch_name, item_name, filename, label)
        VALUES (?, ?, ?, ?, ?);
        """,
        (project_name, batch_name, item_name, filename, label),
    )
    conn.commit()


@retry_on_lock()
def add_batch_file_label(
    conn: sqlite3.Connection,
    project_name: str,
    batch_name: str,
    filename: str,
    label: str,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO batch_file_labels
            (project_name, batch_name, filename, label)
        VALUES (?, ?, ?, ?);
        """,
        (project_name, batch_name, filename, label),
    )
    conn.commit()


@retry_on_lock()
def add_prj_file_label(
    conn: sqlite3.Connection,
    project_name: str,
    filename: str,
    label: str,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO prj_file_labels
            (project_name, filename, label)
        VALUES (?, ?, ?);
        """,
        (project_name, filename, label),
    )
    conn.commit()


# =========================
# 简单的查询工具（可选）
# =========================

def list_projects(conn: sqlite3.Connection):
    """
    列出所有项目。
    返回项目名称列表。
    """
    cur = conn.execute(
        """
        SELECT name
        FROM projects
        ORDER BY created_at ASC;
        """
    )
    rows = cur.fetchall()
    return [row["name"] for row in rows]


def list_batches(conn: sqlite3.Connection, project_name: str):
    """
    列出某个 project 下的所有 batch。
    返回 sqlite3.Row 列表。
    """
    cur = conn.execute(
        """
        SELECT name, upload_type, created_at
        FROM batches
        WHERE project_name = ?
        ORDER BY created_at ASC;
        """,
        (project_name,),
    )
    return cur.fetchall()


def list_items(conn: sqlite3.Connection, project_name: str, batch_name: str):
    """
    列出某个 batch 下的所有 item。
    """
    cur = conn.execute(
        """
        SELECT name, created_at
        FROM items
        WHERE project_name = ? AND batch_name = ?
        ORDER BY created_at ASC;
        """,
        (project_name, batch_name),
    )
    return cur.fetchall()


def list_batch_files(conn: sqlite3.Connection, project_name: str, batch_name: str):
    """列出 batch 级文件。"""
    cur = conn.execute(
        """
        SELECT filename, rel_path, created_at
        FROM batch_files
        WHERE project_name = ? AND batch_name = ?
        ORDER BY filename ASC;
        """,
        (project_name, batch_name),
    )
    return cur.fetchall()


def list_prj_files(conn: sqlite3.Connection, project_name: str):
    """列出 project 级文件。"""
    cur = conn.execute(
        """
        SELECT filename, rel_path, created_at
        FROM prj_files
        WHERE project_name = ?
        ORDER BY filename ASC;
        """,
        (project_name,),
    )
    return cur.fetchall()


def list_files(conn: sqlite3.Connection, project_name: str, batch_name: str, item_name: str):
    """
    列出某个 item 下的所有文件。
    """
    cur = conn.execute(
        """
        SELECT filename, rel_path, created_at
        FROM files
        WHERE project_name = ? AND batch_name = ? AND item_name = ?
        ORDER BY filename ASC;
        """,
        (project_name, batch_name, item_name),
    )
    return cur.fetchall()


def list_batch_file_labels(conn: sqlite3.Connection, project_name: str, batch_name: str, filename: str):
    """列出 batch 文件的 labels。"""
    cur = conn.execute(
        """
        SELECT label
        FROM batch_file_labels
        WHERE project_name = ? AND batch_name = ? AND filename = ?
        ORDER BY label ASC;
        """,
        (project_name, batch_name, filename),
    )
    return [row["label"] for row in cur.fetchall()]


def list_prj_file_labels(conn: sqlite3.Connection, project_name: str, filename: str):
    """列出项目级文件的 labels。"""
    cur = conn.execute(
        """
        SELECT label
        FROM prj_file_labels
        WHERE project_name = ? AND filename = ?
        ORDER BY label ASC;
        """,
        (project_name, filename),
    )
    return [row["label"] for row in cur.fetchall()]


def list_file_labels(conn: sqlite3.Connection, project_name: str, batch_name: str, item_name: str, filename: str):
    """
    列出某个文件的所有 label。
    """
    cur = conn.execute(
        """
        SELECT label
        FROM file_labels
        WHERE project_name = ?
          AND batch_name   = ?
          AND item_name    = ?
          AND filename     = ?
        ORDER BY label ASC;
        """,
        (project_name, batch_name, item_name, filename),
    )
    return [row["label"] for row in cur.fetchall()]


# =========================
# 直接运行 db.py 做一次初始化
# =========================

if __name__ == "__main__":
    conn = get_connection()
    init_db(conn)
    print(f"Initialized database at {DB_PATH}")
    conn.close()
