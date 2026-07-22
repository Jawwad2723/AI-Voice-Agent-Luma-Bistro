"""Structured logging and simple latency helpers."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def setup_logging(level: str = "INFO", log_dir: Optional[Path] = None) -> logging.Logger:
    logger = logging.getLogger("luma")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_dir / "agent.log")
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger


class Metrics:
    def __init__(self, session_id: str, log_dir: Optional[Path] = None):
        self.session_id = session_id
        self.log_dir = log_dir
        self._user_speech_ended_at: Optional[float] = None
        self.events: list[dict[str, Any]] = []
        if log_dir:
            log_dir.mkdir(parents=True, exist_ok=True)
            self._jsonl = log_dir / f"session_{session_id}.jsonl"
        else:
            self._jsonl = None

    def mark_user_speech_end(self) -> None:
        self._user_speech_ended_at = time.perf_counter()

    def eos_to_first_audio_ms(self) -> Optional[float]:
        if self._user_speech_ended_at is None:
            return None
        return round((time.perf_counter() - self._user_speech_ended_at) * 1000, 1)

    def emit(self, event: str, **fields: Any) -> dict[str, Any]:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "event": event,
            **fields,
        }
        self.events.append(record)
        logging.getLogger("luma.metrics").info("%s %s", event, json.dumps(fields))
        if self._jsonl:
            with self._jsonl.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        return record
