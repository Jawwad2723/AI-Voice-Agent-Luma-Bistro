"""Minimal token + static page server for the browser voice demo.

Secrets stay in .env — never expose API secrets to the browser except
a short-lived room token.
"""

from __future__ import annotations

import io
import os
import time
from datetime import timedelta
from pathlib import Path

import av
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from livekit.api import AccessToken, RoomAgentDispatch, RoomConfiguration, VideoGrants
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
RECORDINGS_DIR = ROOT / "recordings"
ALLOWED_RECORDING_EXTS = {"webm", "mp4", "ogg", "wav"}
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
load_dotenv(ROOT / ".env", override=False)

AGENT_NAME = "Jawwad"

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


def _safe_name(value: str, fallback: str = "call") -> str:
    cleaned = "".join(c if c.isalnum() or c in "-_" else "-" for c in value).strip("-")
    return (cleaned[:64] or fallback)


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [item for item in value if item is not None]
    return [value]


def _audio_to_wav(data: bytes, src_format: str | None = None) -> bytes:
    """Transcode browser MediaRecorder output (webm/mp4/ogg) to 16 kHz mono WAV."""
    in_buf = io.BytesIO(data)
    open_kwargs = {}
    if src_format in ALLOWED_RECORDING_EXTS:
        open_kwargs["format"] = src_format
    try:
        container = av.open(in_buf, mode="r", **open_kwargs)
    except av.InvalidDataError:
        in_buf.seek(0)
        container = av.open(in_buf, mode="r")

    try:
        if not container.streams.audio:
            raise RuntimeError("No audio stream in recording")
        in_stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        out_buf = io.BytesIO()
        with av.open(out_buf, mode="w", format="wav") as out:
            out_stream = out.add_stream("pcm_s16le", rate=16000, layout="mono")
            for frame in container.decode(in_stream):
                for resampled in _as_list(resampler.resample(frame)):
                    resampled.pts = None
                    for packet in out_stream.encode(resampled):
                        out.mux(packet)
            for resampled in _as_list(resampler.resample(None)):
                resampled.pts = None
                for packet in out_stream.encode(resampled):
                    out.mux(packet)
            for packet in out_stream.encode(None):
                out.mux(packet)
        wav = out_buf.getvalue()
        if len(wav) < 44:
            raise RuntimeError("WAV conversion produced an empty file")
        return wav
    finally:
        container.close()


@app.post("/api/recordings")
async def save_recording(
    request: Request,
    room_name: str = "call",
    ext: str = "webm",
):
    data = await request.body()
    if not data:
        raise HTTPException(400, detail="Empty recording")

    src_ext = ext.lower().lstrip(".")
    if src_ext not in ALLOWED_RECORDING_EXTS:
        src_ext = "webm"

    print(f"recording upload {len(data)} bytes ext={src_ext}", flush=True)
    if data[:4] == b"RIFF":
        wav = data
    else:
        try:
            wav = _audio_to_wav(data, src_ext)
        except Exception as exc:
            raise HTTPException(
                400, detail=f"Could not convert recording to WAV: {exc}"
            ) from exc

    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = RECORDINGS_DIR / f"{stamp}-{_safe_name(room_name)}.wav"
    path.write_bytes(wav)
    print(f"saved recording {path} ({len(wav)} bytes)", flush=True)
    return {"saved": path.name, "bytes": len(wav), "dir": str(RECORDINGS_DIR)}


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
        .with_room_config(
            RoomConfiguration(
                agents=[RoomAgentDispatch(agent_name=AGENT_NAME)]
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
        "agent_name": AGENT_NAME,
    }


if __name__ == "__main__":
    import uvicorn

    # Bind localhost so the browser is a secure context for getUserMedia.
    # Open http://127.0.0.1:8080 (LAN IP / 0.0.0.0 will break the mic).
    uvicorn.run(
        "web.token_server:app",
        host="127.0.0.1",
        port=8080,
        reload=False,
    )
