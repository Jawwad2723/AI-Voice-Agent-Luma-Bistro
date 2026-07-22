"""Minimal token + static page server for the browser voice demo.

Secrets stay in .env — never expose API secrets to the browser except
a short-lived room token.
"""

from __future__ import annotations

import os
import time
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from livekit.api import AccessToken, VideoGrants
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=False)

app = FastAPI(title="Luma Bistro Voice Demo")
WEB = Path(__file__).resolve().parent
app.mount("/assets", StaticFiles(directory=WEB), name="assets")


class TokenRequest(BaseModel):
    room_name: str = "luma-bistro"
    identity: str | None = None


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/token")
def create_token(body: TokenRequest):
    url = os.getenv("LIVEKIT_URL", "").strip()
    key = os.getenv("LIVEKIT_API_KEY", "").strip()
    secret = os.getenv("LIVEKIT_API_SECRET", "").strip()
    ttl = int(os.getenv("LIVEKIT_TOKEN_TTL_SECONDS", "3600"))

    if not url or not key or not secret or key.startswith("your_"):
        raise HTTPException(
            500,
            detail="LiveKit secrets missing. Set LIVEKIT_* in voice_agent/.env",
        )

    identity = body.identity or f"guest-{int(time.time())}"
    token = (
        AccessToken(key, secret)
        .with_identity(identity)
        .with_name(identity)
        .with_grants(
            VideoGrants(
                room_join=True,
                room=body.room_name,
                can_publish=True,
                can_subscribe=True,
            )
        )
        .with_ttl(timedelta(seconds=ttl))
        .to_jwt()
    )
    return {
        "token": token,
        "url": url,
        "room_name": body.room_name,
        "identity": identity,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "web.token_server:app",
        host="0.0.0.0",
        port=8080,
        reload=False,
    )
