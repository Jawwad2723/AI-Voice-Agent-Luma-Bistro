"""Export LiveKit session audio to a playable WAV in recordings/."""

from __future__ import annotations

import io
import time
from pathlib import Path

import av

_ROOT = Path(__file__).resolve().parent.parent
RECORDINGS_DIR = _ROOT / "recordings"


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [item for item in value if item is not None]
    return [value]


def _ogg_to_wav(src: Path) -> bytes:
    with av.open(str(src)) as inp:
        if not inp.streams.audio:
            raise RuntimeError("No audio stream in session recording")
        in_stream = inp.streams.audio[0]
        rate = in_stream.rate or 48000
        resampler = av.AudioResampler(format="s16", layout="mono", rate=rate)
        out_buf = io.BytesIO()
        with av.open(out_buf, mode="w", format="wav") as out:
            out_stream = out.add_stream("pcm_s16le", rate=rate, layout="mono")
            for frame in inp.decode(in_stream):
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
        if len(wav) < 44 or wav[:4] != b"RIFF":
            raise RuntimeError("WAV conversion failed")
        return wav


def export_session_wav(*, room_name: str, session_dir: Path, session_id: str) -> Path | None:
    src = session_dir / "audio.ogg"
    if not src.exists() or src.stat().st_size < 200:
        return None

    wav = _ogg_to_wav(src)
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in room_name).strip("-")
    name = f"{stamp}-{safe[:48] or session_id}.wav"
    path = RECORDINGS_DIR / name
    path.write_bytes(wav)
    return path
