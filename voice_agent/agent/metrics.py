"""Clean, presentable logging and latency measurement for demos."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


# Keep noisy third-party loggers quiet so the terminal stays demo-friendly
_QUIET_LOGGERS = (
    "livekit",
    "livekit.agents",
    "livekit.agents.voice",
    "livekit.agents.worker",
    "livekit.plugins",
    "livekit.plugins.deepgram",
    "livekit.plugins.elevenlabs",
    "livekit.plugins.openai",
    "livekit.plugins.google",
    "httpx",
    "httpcore",
    "openai",
    "asyncio",
    "urllib3",
    "uvicorn",
    "uvicorn.access",
)


class _HighlightFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return f"{time.strftime('%H:%M:%S')}  {record.getMessage()}"


def setup_logging(level: str = "INFO", log_dir: Optional[Path] = None) -> logging.Logger:
    """Configure quiet third-party loggers + a clean `luma` highlight logger."""
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    # Also quiet the root LiveKit CLI handler noise when possible
    root = logging.getLogger()
    if root.level < logging.WARNING:
        # Don't raise root so our luma logger still works; just mute known noisy names
        pass

    logger = logging.getLogger("luma")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()
    logger.propagate = False

    sh = logging.StreamHandler()
    sh.setFormatter(_HighlightFormatter())
    logger.addHandler(sh)

    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_dir / "agent.log")
        fh.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
        )
        logger.addHandler(fh)

    return logger


def highlight(msg: str) -> None:
    logging.getLogger("luma").info(msg)


class Metrics:
    """Tracks per-turn latency and prints clean demo highlights."""

    def __init__(self, session_id: str, log_dir: Optional[Path] = None):
        self.session_id = session_id
        self.log_dir = log_dir
        self.events: list[dict[str, Any]] = []
        self.eos_to_audio_samples: list[float] = []
        self.api_latencies_ms: list[float] = []
        if log_dir:
            log_dir.mkdir(parents=True, exist_ok=True)
            self._jsonl = log_dir / f"session_{session_id}.jsonl"
        else:
            self._jsonl = None

    def emit(self, event: str, **fields: Any) -> dict[str, Any]:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "event": event,
            **fields,
        }
        self.events.append(record)
        if self._jsonl:
            with self._jsonl.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        return record

    def note_api_latency(self, name: str, latency_ms: float, **extra: Any) -> None:
        self.api_latencies_ms.append(latency_ms)
        self.emit("api", tool=name, latency_ms=latency_ms, **extra)
        bits = "  ".join(f"{k}={v}" for k, v in extra.items())
        highlight(f"api   {name:<22} {latency_ms:6.1f} ms  {bits}".rstrip())

    def on_assistant_message(self, metrics_report: dict[str, Any]) -> None:
        """Use ChatMessage.metrics (preferred LiveKit path) for EOS→audio."""
        e2e = metrics_report.get("e2e_latency")
        llm_ttft = metrics_report.get("llm_node_ttft")
        tts_ttfb = metrics_report.get("tts_node_ttfb")
        if e2e is None and llm_ttft is None and tts_ttfb is None:
            return

        e2e_ms = round(float(e2e) * 1000, 1) if e2e is not None else None
        llm_ms = round(float(llm_ttft) * 1000, 1) if llm_ttft is not None else None
        tts_ms = round(float(tts_ttfb) * 1000, 1) if tts_ttfb is not None else None

        if e2e_ms is not None:
            self.eos_to_audio_samples.append(e2e_ms)
            highlight(f"lat   EOS → first audio   {e2e_ms:6.0f} ms")
        parts = []
        if llm_ms is not None:
            parts.append(f"llm_ttft={llm_ms:.0f}ms")
        if tts_ms is not None:
            parts.append(f"tts_ttfb={tts_ms:.0f}ms")
        if parts:
            highlight(f"turn  {'  '.join(parts)}")

        self.emit(
            "latency",
            eos_to_first_audio_ms=e2e_ms,
            llm_ttft_ms=llm_ms,
            tts_ttfb_ms=tts_ms,
        )

    def on_user_message(self, metrics_report: dict[str, Any], text: Optional[str] = None) -> None:
        eou = metrics_report.get("end_of_turn_delay")
        tx = metrics_report.get("transcription_delay")
        snippet = (text or "").strip().replace("\n", " ")
        if len(snippet) > 60:
            snippet = snippet[:57] + "..."
        bits = []
        if eou is not None:
            bits.append(f"eou={float(eou)*1000:.0f}ms")
        if tx is not None:
            bits.append(f"stt={float(tx)*1000:.0f}ms")
        if snippet:
            bits.append(f'user="{snippet}"')
        if bits:
            highlight(f"hear  {'  '.join(bits)}")

    def on_metrics(self, metrics_obj: Any) -> None:
        """Fallback handler for MetricsCollectedEvent.metrics payloads."""
        mtype = getattr(metrics_obj, "type", None) or type(metrics_obj).__name__
        if mtype == "eou_metrics":
            eou = getattr(metrics_obj, "end_of_utterance_delay", 0.0) or 0.0
            tx = getattr(metrics_obj, "transcription_delay", 0.0) or 0.0
            highlight(
                f"turn  user finished speaking   eou={eou*1000:.0f}ms  stt={tx*1000:.0f}ms"
            )
        elif mtype == "llm_metrics":
            ttft = getattr(metrics_obj, "ttft", 0.0) or 0.0
            tokens = getattr(metrics_obj, "total_tokens", 0) or 0
            highlight(f"llm   first token {ttft*1000:6.0f} ms   tokens={tokens}")
        elif mtype == "tts_metrics":
            ttfb = getattr(metrics_obj, "ttfb", 0.0) or 0.0
            highlight(f"tts   first audio {ttfb*1000:6.0f} ms")

    def summary_line(self) -> str:
        def pct(vals: list[float], p: float) -> Optional[float]:
            if not vals:
                return None
            s = sorted(vals)
            idx = min(len(s) - 1, max(0, int(round((p / 100) * (len(s) - 1)))))
            return round(s[idx], 1)

        eos_p50 = pct(self.eos_to_audio_samples, 50)
        eos_p95 = pct(self.eos_to_audio_samples, 95)
        api_p50 = pct(self.api_latencies_ms, 50)
        parts = [f"session={self.session_id}"]
        if eos_p50 is not None:
            parts.append(
                f"EOS→audio p50={eos_p50}ms p95={eos_p95}ms n={len(self.eos_to_audio_samples)}"
            )
        if api_p50 is not None:
            parts.append(f"API p50={api_p50}ms n={len(self.api_latencies_ms)}")
        return "  ".join(parts)
