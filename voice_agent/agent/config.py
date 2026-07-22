"""Load and validate configuration from environment / .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _ROOT / ".env"


def _load_dotenv() -> None:
    # Prefer voice_agent/.env; do not override already-exported shell vars.
    load_dotenv(_ENV_PATH, override=False)


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value or value.startswith("your_"):
        raise RuntimeError(
            f"Missing or placeholder secret `{name}`. "
            f"Copy .env.example to .env and set real values ({_ENV_PATH})."
        )
    return value


def _optional(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class Settings:
    reservation_api_base_url: str
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str
    livekit_token_ttl_seconds: int
    deepgram_api_key: str
    google_api_key: str
    gemini_model: str
    eleven_api_key: str
    eleven_voice_id: str
    eleven_model_id: str
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_phone_number: str
    log_level: str
    log_dir: Path
    silence_timeout_seconds: float
    availability_max_retries: int

    @property
    def root(self) -> Path:
        return _ROOT


@lru_cache(maxsize=1)
def get_settings(*, require_voice_secrets: bool = True) -> Settings:
    """
    Load settings from .env / environment.

    require_voice_secrets=False is for unit tests that only need the
    reservation API (no LiveKit/Deepgram/Gemini/ElevenLabs/Twilio keys).
    """
    _load_dotenv()

    reservation_api_base_url = _optional(
        "RESERVATION_API_BASE_URL", "http://localhost:8000"
    ).rstrip("/")

    if require_voice_secrets:
        livekit_url = _require("LIVEKIT_URL")
        livekit_api_key = _require("LIVEKIT_API_KEY")
        livekit_api_secret = _require("LIVEKIT_API_SECRET")
        deepgram_api_key = _require("DEEPGRAM_API_KEY")
        google_api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or ""
        if not google_api_key.strip() or google_api_key.strip().startswith("your_"):
            raise RuntimeError(
                "Missing GOOGLE_API_KEY (or GEMINI_API_KEY). "
                f"Set it in {_ENV_PATH}."
            )
        google_api_key = google_api_key.strip()
        eleven_api_key = _require("ELEVEN_API_KEY")
        # Twilio required for phone path; allow placeholders until Phase 5
        twilio_account_sid = _optional("TWILIO_ACCOUNT_SID")
        twilio_auth_token = _optional("TWILIO_AUTH_TOKEN")
        twilio_phone_number = _optional("TWILIO_PHONE_NUMBER")
    else:
        livekit_url = _optional("LIVEKIT_URL")
        livekit_api_key = _optional("LIVEKIT_API_KEY")
        livekit_api_secret = _optional("LIVEKIT_API_SECRET")
        deepgram_api_key = _optional("DEEPGRAM_API_KEY")
        google_api_key = _optional("GOOGLE_API_KEY") or _optional("GEMINI_API_KEY")
        eleven_api_key = _optional("ELEVEN_API_KEY")
        twilio_account_sid = _optional("TWILIO_ACCOUNT_SID")
        twilio_auth_token = _optional("TWILIO_AUTH_TOKEN")
        twilio_phone_number = _optional("TWILIO_PHONE_NUMBER")

    log_dir = Path(_optional("LOG_DIR", "logs"))
    if not log_dir.is_absolute():
        log_dir = _ROOT / log_dir

    return Settings(
        reservation_api_base_url=reservation_api_base_url,
        livekit_url=livekit_url,
        livekit_api_key=livekit_api_key,
        livekit_api_secret=livekit_api_secret,
        livekit_token_ttl_seconds=int(_optional("LIVEKIT_TOKEN_TTL_SECONDS", "3600")),
        deepgram_api_key=deepgram_api_key,
        google_api_key=google_api_key,
        gemini_model=_optional("GEMINI_MODEL", "gemini-3-flash-preview"),
        eleven_api_key=eleven_api_key,
        eleven_voice_id=_optional("ELEVEN_VOICE_ID", "21m00Tcm4TlvDq8ikWAM"),
        eleven_model_id=_optional("ELEVEN_MODEL_ID", "eleven_turbo_v2_5"),
        twilio_account_sid=twilio_account_sid,
        twilio_auth_token=twilio_auth_token,
        twilio_phone_number=twilio_phone_number,
        log_level=_optional("LOG_LEVEL", "INFO").upper(),
        log_dir=log_dir,
        silence_timeout_seconds=float(_optional("SILENCE_TIMEOUT_SECONDS", "8")),
        availability_max_retries=int(_optional("AVAILABILITY_MAX_RETRIES", "1")),
    )
