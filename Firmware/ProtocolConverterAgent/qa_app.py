#!/usr/bin/env python
"""
qa_agent.py

Multi-step RAG agent:

- Embedding: local OpenAI-compatible model (from config.local_embedding)
- Retrieval: Chroma
- Chat / agent brain: online model (from config.remote_chat)

The agent can:
- decide to CALL "search" with a query & top_k
- or RETURN "final_answer"

Each step, it outputs a JSON action; Python executes the action and
feeds the results back, encouraging multi-step retrieval.

Logs:
- chosen actions
- search queries & hits
- final answer
"""

import sys
import json
import logging
from pathlib import Path
from typing import List, Tuple

import chromadb
from openai import OpenAI

from build_kb import OpenAICompatEmbedding, load_config


logger = logging.getLogger("rag_agent")
logger.setLevel(logging.DEBUG)
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", "%H:%M:%S"))
logger.addHandler(_handler)


# -------------------------
# Init helpers
# -------------------------

def init_embedding(cfg):
    emb_cfg = cfg["local_embedding"]
    client = OpenAI(
        base_url=emb_cfg["base_url"],
        api_key=emb_cfg["api_key"],
    )
    model = emb_cfg["model"]
    return client, model


def init_chat(cfg):
    chat_cfg = cfg["remote_chat"]
    client = OpenAI(
        base_url=chat_cfg["base_url"],
        api_key=chat_cfg["api_key"],
    )
    model = chat_cfg["model"]
    return client, model


def init_collection(cfg, emb_client, emb_model):
    db_path = cfg["db_path"]
    col_name = cfg["collection_name"]

    chroma_client = chromadb.PersistentClient(path=db_path)
    embedding_fn = OpenAICompatEmbedding(emb_client, emb_model)
    collection = chroma_client.get_or_create_collection(
        name=col_name,
        embedding_function=embedding_fn,
    )
    return collection


# -------------------------
# Retrieval
# -------------------------

def retrieve_docs(collection, query: str, top_k: int = 3) -> List[Tuple[str, dict, str]]:
    res = collection.query(query_texts=[query], n_results=top_k)
    docs = res["documents"][0]
    metas = res["metadatas"][0]
    ids = res["ids"][0]
    return list(zip(docs, metas, ids))


def summarize_hits(hits: List[Tuple[str, dict, str]], snippet_len: int = 200) -> str:
    """
    Turn search hits into a compact text the model can read.
    """
    lines = []
    for i, (doc, meta, doc_id) in enumerate(hits, start=1):
        path = meta.get("path", "") if isinstance(meta, dict) else ""
        snippet = doc[:snippet_len].replace("\n", " ")
        lines.append(
            f"[{i}] id={doc_id} path={path} snippet={snippet}"
        )
    return "\n".join(lines)


def build_context_for_model(hits: List[Tuple[str, dict, str]], snippet_len: int = 800) -> str:
    """
    A richer version used when we show the model some content.
    """
    parts = []
    for i, (doc, meta, doc_id) in enumerate(hits, start=1):
        path = meta.get("path", "") if isinstance(meta, dict) else ""
        snippet = doc[:snippet_len]
        parts.append(
            f"### Document {i}\n"
            f"ID: {doc_id}\n"
            f"Path: {path}\n"
            f"Content:\n{snippet}\n"
        )
    return "\n\n".join(parts)


# -------------------------
# Agent Core
# -------------------------

AGENT_SYSTEM_PROMPT = """
You are a retrieval-augmented assistant for an automated chemical synthesis and electrochemistry workflow.
You must reason strictly based on retrieved documentation from the vector database (“the manual”).
Do NOT invent capabilities the system does not have.

You have access to a vector-database search tool. You must follow this protocol:

------------------------------------------------------------
AVAILABLE WORKSTATIONS & THEIR CAPABILITIES
------------------------------------------------------------

1. solution-preparation
- Can manipulate liquids according to a ratio_table CSV.
- The ONLY workstation that can open or close tube caps.
- Accepts open or closed tubes; outputs cap state exactly as specified.
- Cannot handle solids; all reagents must already be prepared as solutions.
- Tube volume limit: ≤ 25 mL added total.
- If the chemistry requires multiple reagents to be added in sequence **without any intermediate processing**,
it is best to:

* Combine these additions into one ratio_table
* Use a single Solution-Preparation step

Multiple steps should only be used when an intermediate event (ultrasonic, centrifuge, oven, etc.) **must occur between additions**.

pay attention to tube cap state

2. centrifuge-purification
- Accepts CLOSED tubes only; outputs CLOSED tubes.
- Performs centrifugation up to 10,000 rpm.
- Removes supernatant or retains precipitate.
- Can perform 1–5 washing cycles using operator-provided solvent.
- Cannot open or close tube caps.

3. ultrasonic-treatment
- Accepts OPEN tubes only; outputs OPEN tubes.
- Performs ultrasonic mixing for a specified duration and power level.
- Cannot change cap state.

4. oven-station
- Accepts CLOSED tubes only; outputs CLOSED tubes.
- Performs heating/drying at specified temperature and duration.
- Cannot open or close tubes.

5. electrochemistry-station
- Accepts OPEN tubes only; outputs OPEN tubes.
- Assumes Nafion has been added and ultrasonic mixing is complete.
- Uses a fixed catalyst coating area of 1 cm².
- Runs pre-written electrochemical programs (CV/LSV/EIS/etc.).
- Cannot change cap state.

------------------------------------------------------------
TUBE CAP RULES (ABSOLUTELY REQUIRED)
------------------------------------------------------------
- Only solution-preparation can modify tube cap state.
- All other workstations reject tubes with the wrong cap state.
- Workflow reasoning must always respect this cap-state machine.

------------------------------------------------------------
RETRIEVAL PROTOCOL
------------------------------------------------------------

ACTION 1 — "search"
Request retrieval from the manual.
JSON format:
{
"action": "search",
"query": "short English query",
"top_k": 10,
"reason": "why the search is needed"
}

ACTION 2 — "final_answer"
When enough evidence is retrieved, answer the user.
JSON format:
{
"action": "final_answer",
"answer": "your response",
"used_doc_ids": ["id1", "id2"],
"reason": "how the documents informed the answer"
}

------------------------------------------------------------
MANDATORY RULES
------------------------------------------------------------
- Always search first when answering questions about workstation behavior, requirements, or procedures.
- Never invent undocumented robot capabilities.
- Always enforce tube cap constraints.
- Keep queries short and focused.
- Stop and answer as soon as you have sufficient evidence.
""".strip()


def parse_action(raw: str) -> dict:
    """
    Parse the JSON action returned by the model.
    Handles minor formatting issues (like ```json fences).
    """
    text = raw.strip()
    if text.startswith("```"):
        # strip fences
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    return json.loads(text)


def agent_once(chat_client: OpenAI, chat_model: str, messages: List[dict]) -> dict:
    """
    Call chat model once and parse the JSON action.
    """
    resp = chat_client.chat.completions.create(
        model=chat_model,
        messages=messages,
        temperature=0.2,
    )
    content = resp.choices[0].message.content
    return parse_action(content)


def run_agent_loop(
    chat_client: OpenAI,
    chat_model: str,
    collection,
    user_question: str,
    max_steps: int = 100,
) -> str:
    """
    Multi-step loop:
    - ask model what to do (search / final_answer)
    - execute searches
    - feed results back
    - return final answer (string)
    """

    messages = [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "User question:\n"
                f"{user_question}\n\n"
                "Decide your first action as JSON."
            ),
        },
    ]

    all_hits_for_context: List[Tuple[str, dict, str]] = []

    for step in range(1, max_steps + 1):
        logger.info(f"--- Agent step {step} ---")


        try:
            action = agent_once(chat_client, chat_model, messages)
            print(action)
        except Exception as e:
            logger.error(f"Failed to parse model action: {e}")
            return "Error: the agent could not decide an action."


        act = action.get("action")
        logger.info(f"Model chose action: {json.dumps(action, ensure_ascii=False)}")

        if act == "search":
            query = action.get("query") or user_question
            top_k = int(action.get("top_k") or 10)

            hits = retrieve_docs(collection, query, top_k=top_k)
            all_hits_for_context.extend(hits)

            # Log hits
            logger.info(f"Search query: {query!r}, top_k={top_k}, {len(hits)} hits:")
            logger.info(summarize_hits(hits))

            # Build context text for the model
            context_text = build_context_for_model(hits)

            tool_result_msg = (
                f"Search results for query: {query!r}\n\n"
                f"{context_text}\n\n"
                "You may call 'search' again with a refined query, "
                "or call 'final_answer' if you have enough information."
            )

            messages.append(
                {
                    "role": "assistant",
                    "content": json.dumps(action),
                }
            )
            messages.append(
                {
                    "role": "system",
                    "content": tool_result_msg,
                }
            )
            continue

        elif act == "final_answer":
            #answer = action.get("answer", "").strip()

            answer_obj = action.get("answer", "")

            if isinstance(answer_obj, str):
                answer = answer_obj.strip()
            else:
                # answer 是 dict，转成 JSON 字符串（缩进好看一点）
                answer = json.dumps(answer_obj, ensure_ascii=False, indent=2)
            reason = action.get("reason", "").strip()
            used_doc_ids = action.get("used_doc_ids", [])

            logger.info("Final answer reason: " + reason)
            logger.info("Final answer used_doc_ids: " + json.dumps(used_doc_ids))

            return answer or "Empty answer from model."

        else:
            logger.warning(f"Unknown action '{act}', stopping.")
            return "Error: unknown action from agent."

    # If we exit loop without final_answer
    logger.warning("Max steps reached without final_answer.")
    return "I could not confidently answer your question within the allowed steps."


# -------------------------
# CLI
# -------------------------

def main(cfg_path: str | Path):
    cfg = load_config(cfg_path)

    emb_client, emb_model = init_embedding(cfg)
    chat_client, chat_model = init_chat(cfg)
    collection = init_collection(cfg, emb_client, emb_model)

    logger.info("RAG agent ready. Ask questions (empty to exit).")

    while True:
        try:
            q = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not q:
            print("Bye.")
            break

        answer = run_agent_loop(chat_client, chat_model, collection, q)
        print(f"\nAI: {answer}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python qa_agent.py config.json")
        sys.exit(1)
    main(sys.argv[1])
