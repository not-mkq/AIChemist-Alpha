from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from openai import OpenAI


def load_json(path: str | Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_config(config_path: str | Path = "config.json") -> Dict[str, Any]:
    cfg = load_json(config_path)
    required = ["agents", "openai_client", "docs_filename", "system_prompt"]
    for name in required:
        if name not in cfg:
            raise KeyError(f"config.json missing '{name}'")
    if "default_model" not in cfg["openai_client"]:
        raise KeyError("config.json missing openai_client.default_model")

    # Auditor config can live under Audit/config.json to keep the root config clean.
    if not cfg.get("auditor"):
        audit_cfg_path = Path(config_path).resolve().parent / "Audit" / "config.json"
        if audit_cfg_path.exists():
            audit_cfg = load_json(audit_cfg_path)
            auditor = audit_cfg.get("auditor")
            if auditor:
                cfg["auditor"] = auditor
    return cfg


def load_tool_docs(docs_path: str | Path) -> Dict[str, Any]:
    return load_json(docs_path)


def build_openai_client(cfg_openai: Dict[str, Any]) -> OpenAI:
    base_url = cfg_openai.get("base_url")
    api_key = cfg_openai.get("api_key")
    if base_url:
        return OpenAI(base_url=base_url, api_key=api_key)
    return OpenAI(api_key=api_key)
