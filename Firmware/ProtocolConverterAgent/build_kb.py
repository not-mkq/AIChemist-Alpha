#!/usr/bin/env python
"""
使用 Chroma + OpenAI 兼容 Embedding 搭建本地知识库：
- 从 config.json 中读取 base_url / api_key / embedding_model / db_path / collection_name / docs_dir
- 递归遍历 docs_dir 下所有 .md 文件
- 将每个文件内容按 chunk 切分后，作为多个 document 写入 Chroma 向量库
"""

import json
import sys
from pathlib import Path
from typing import List

import chromadb
from chromadb.utils import embedding_functions

from openai import OpenAI


# =========================
# 配置加载
# =========================

def load_config(path: str | Path) -> dict:
    cfg_path = Path(path)
    if not cfg_path.is_file():
        raise FileNotFoundError(f"配置文件不存在: {cfg_path}")
    with cfg_path.open("r", encoding="utf-8") as f:
        return json.load(f)


# =========================
# OpenAI 兼容 Embedding 封装
# =========================

class OpenAICompatEmbedding(embedding_functions.EmbeddingFunction):
    """
    一个适配 Chroma 的 EmbeddingFunction，
    通过 OpenAI 兼容接口调用本地/远程 embedding 模型。

    注意：为了兼容不完全实现批量 input 的服务，这里改成
    对每个文本单独发一次请求，保证 len(texts) == len(embeddings)。
    """

    def __init__(self, client: OpenAI, model: str):
        self._client = client
        self._model = model

    def __call__(self, texts: List[str]) -> List[List[float]]:
        embeddings: List[List[float]] = []
        for t in texts:
            if not t.strip():
                # 空文本不应该进入 embedding 函数
                raise ValueError("空文本不应该进入 embedding 函数")

            resp = self._client.embeddings.create(
                model=self._model,
                input=t,
            )
            if not resp.data:
                raise RuntimeError("embedding 接口返回空 data 列表")

            embeddings.append(resp.data[0].embedding)

        if len(embeddings) != len(texts):
            raise RuntimeError(
                f"Embedding 数量不匹配: 输入 {len(texts)} 条，返回 {len(embeddings)} 条"
            )
        return embeddings


# =========================
# Markdown 切片工具
# =========================

def split_by_headings(text: str) -> List[str]:
    """
    粗略按 Markdown 标题 (# / ## / ### ...) 切成若干 section。
    标题行也保留在对应 section 里。
    """
    lines = text.splitlines(keepends=True)
    sections: List[List[str]] = []
    current: List[str] = []

    def is_heading(line: str) -> bool:
        stripped = line.lstrip()
        return stripped.startswith("#")

    for line in lines:
        if is_heading(line):
            # 新标题 => 开启新 section
            if current:
                sections.append(current)
                current = []
        current.append(line)

    if current:
        sections.append(current)

    # 拼成字符串
    return ["".join(sec).strip() for sec in sections if "".join(sec).strip()]


def chunk_long_text(text: str, max_chars: int = 800, overlap: int = 200) -> List[str]:
    """
    对单个较长文本再做细分：
    - 先按空行分成 paragraph
    - 再按字符数组 chunk，并加入一定 overlap
    """
    if len(text) <= max_chars:
        return [text]

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: List[str] = []
    cur: List[str] = []
    cur_len = 0

    for p in paragraphs:
        p_len = len(p) + 2  # 加上两个换行
        if cur_len + p_len <= max_chars:
            cur.append(p)
            cur_len += p_len
        else:
            # 当前 chunk 收尾
            if cur:
                chunks.append("\n\n".join(cur))

                # 为了 overlap，从当前 chunk 的尾部截取一段
                if overlap > 0:
                    joined = "\n\n".join(cur)
                    overlap_text = joined[-overlap:]
                    cur = [overlap_text, p]
                    cur_len = len(overlap_text) + 2 + len(p)
                else:
                    cur = [p]
                    cur_len = p_len
            else:
                # 单个段落就超长，硬切 by chars
                text_p = p
                start = 0
                while start < len(text_p):
                    end = start + max_chars
                    chunks.append(text_p[start:end])
                    if end >= len(text_p):
                        break
                    start = end - overlap
                cur = []
                cur_len = 0

    if cur:
        chunks.append("\n\n".join(cur))

    return chunks


def chunk_markdown(text: str,
                   max_chars: int = 800,
                   overlap: int = 200) -> List[str]:
    """
    综合切片：
    1. 先按 Markdown 标题分成若干 section
    2. 对每个 section，如果太长，再用 chunk_long_text 拆分
    """
    text = text.strip()
    if not text:
        return []

    sections = split_by_headings(text)
    if not sections:
        # 没有标题时，直接对全文切
        return chunk_long_text(text, max_chars=max_chars, overlap=overlap)

    chunks: List[str] = []
    for sec in sections:
        if len(sec) <= max_chars:
            chunks.append(sec)
        else:
            chunks.extend(chunk_long_text(sec, max_chars=max_chars, overlap=overlap))
    return chunks


# =========================
# 文件扫描
# =========================

def iter_markdown_files(root: Path):
    """
    递归遍历 root 下所有 .md 文件。
    """
    for p in root.rglob("*.md"):
        if p.is_file():
            yield p


# =========================
# 主逻辑：构建知识库
# =========================

def build_knowledge_base(config_path: str | Path):
    cfg = load_config(config_path)

    base_url = cfg["base_url"]
    api_key = cfg["api_key"]
    embedding_model = cfg["embedding_model"]
    db_path = Path(cfg.get("db_path", "./chroma_db"))
    collection_name = cfg.get("collection_name", "personal_notes")
    docs_dir = Path(cfg.get("docs_dir", "./notes"))

    if not docs_dir.is_dir():
        raise NotADirectoryError(f"docs_dir 不是目录或不存在: {docs_dir}")

    # ---- 初始化 OpenAI 兼容客户端 ----
    client = OpenAI(
        base_url=base_url,
        api_key=api_key,
    )

    # ---- 初始化 Chroma ----
    chroma_client = chromadb.PersistentClient(path=str(db_path))

    embedding_fn = OpenAICompatEmbedding(client, embedding_model)

    collection = chroma_client.get_or_create_collection(
        name=collection_name,
        embedding_function=embedding_fn,
    )

    print(f"使用 Chroma 路径: {db_path}")
    print(f"Collection 名称: {collection_name}")
    print(f"文档目录: {docs_dir.resolve()}")

    # ---- 收集所有 .md 文件 ----
    files = list(iter_markdown_files(docs_dir))
    if not files:
        print("未找到任何 .md 文件，退出。")
        return

    print(f"共发现 {len(files)} 个 markdown 文件，开始切片并写入知识库...")

    ids: List[str] = []
    docs: List[str] = []
    metas: List[dict] = []

    total_chunks = 0

    for f in files:
        rel_path = f.relative_to(docs_dir)
        base_id = str(rel_path)
        text = f.read_text(encoding="utf-8", errors="ignore")

        chunks = chunk_markdown(text, max_chars=800, overlap=200)
        if not chunks:
            continue

        for idx, chunk in enumerate(chunks):
            chunk_id = f"{base_id}::chunk-{idx}"
            ids.append(chunk_id)
            docs.append(chunk)
            metas.append({
                "path": str(rel_path),
                "name": f.stem,
                "chunk_index": idx,
            })
            total_chunks += 1

    if not docs:
        print("所有文件内容为空或未生成任何 chunk，未写入文档。")
        return

    print(f"总共生成 {total_chunks} 个 chunks，准备写入 Chroma（embedding 调用次数 = chunk 数量）...")

    # 简单 sanity check
    assert len(ids) == len(docs) == len(metas)

    collection.add(
        ids=ids,
        documents=docs,
        metadatas=metas,
    )

    print("写入完成！")


# =========================
# 命令行入口
# =========================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python build_kb.py path/to/config.json")
        sys.exit(1)

    config_path = sys.argv[1]
    build_knowledge_base(config_path)
