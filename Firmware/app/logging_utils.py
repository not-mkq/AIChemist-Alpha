from __future__ import annotations

import logging
import time
from pathlib import Path


class SeqFilter(logging.Filter):
    """Inject sequential index number 'seq'."""

    def __init__(self):
        super().__init__()
        self._n = 0

    def filter(self, record: logging.LogRecord) -> bool:
        self._n += 1
        record.seq = self._n
        return True


def setup_logging(log_cfg: dict) -> logging.Logger:
    level = getattr(logging, log_cfg.get("level", "DEBUG"))
    fmt = "[#%(seq)04d] %(message)s"
    encoding = log_cfg.get("encoding", "utf-8")

    dir_ = Path(log_cfg.get("log_dir", "."))
    dir_.mkdir(parents=True, exist_ok=True)
    pattern = log_cfg.get("filename_pattern", "chatbot_%Y%m%d_%H%M%S.log")
    logfile = dir_ / time.strftime(pattern)

    logger = logging.getLogger("miniagent")
    logger.setLevel(level)
    logger.handlers.clear()
    seq_filter = SeqFilter()

    fh = logging.FileHandler(logfile, encoding=encoding)
    fh.addFilter(seq_filter)
    fh.setFormatter(logging.Formatter(fmt))
    sh = logging.StreamHandler()
    sh.addFilter(seq_filter)
    sh.setFormatter(logging.Formatter(fmt))

    logger.addHandler(fh)
    logger.addHandler(sh)
    logger.logfile = str(logfile)  # type: ignore[attr-defined]

    logger.info("Program start")
    logger.info(f"Log file: {logfile}")
    return logger
