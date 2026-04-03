#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from app.config import build_openai_client, load_config, load_tool_docs
from app.logging_utils import setup_logging
from app.session import ChatSession


def cli_decision_provider(ticket):
    ai = ticket.ai_decision or {}
    summary = ai.get("summary", "")
    doubts = ai.get("doubts", [])
    print("\n===== AI 审计结果 =====")
    print(f"工具: {ticket.tool_name}")
    if summary:
        print(f"摘要: {summary}")
    if doubts:
        print("疑点/注意事项:")
        for i, doubt in enumerate(doubts, 1):
            print(f"  {i}. {doubt}")
    print("=======================")
    while True:
        ans = input("是否继续执行该工具调用？(y/N): ").strip().lower()
        if ans in ("y", "yes"):
            ticket.resolve(True, actor="cli")
            return
        if ans in ("n", "no", ""):
            ticket.resolve(False, actor="cli")
            return
        print("请输入 y 或 n。")


def main():
    cfg = load_config("config.json")
    docs = load_tool_docs(cfg["docs_filename"])
    logger = setup_logging(cfg.get("logging", {}))
    client = build_openai_client(cfg["openai_client"])

    session = ChatSession(
        session_id="cli",
        cfg=cfg,
        docs=docs,
        logger=logger,
        client=client,
        decision_provider=cli_decision_provider,
        label="CLI Session",
    )

    print("🧠 Native tools mode: All tools are available via OpenAI function-calling.")
    seen_events = 0
    while True:
        try:
            user_input = input("\n🗣️ Enter your request (q to quit):\n> ").strip()
        except EOFError:
            break
        if user_input.lower() == "q":
            logger.info("== Program exit ==")
            break
        events = session.process_user_message(user_input)
        for evt in events[seen_events:]:
            if evt["type"] == "assistant_message":
                print(f"🧾 Model: {evt['content']}")
        seen_events = len(events)


if __name__ == "__main__":
    main()
