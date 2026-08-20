"""Luma Bistro LiveKit voice agent entrypoint.

Secrets are loaded exclusively from voice_agent/.env (see .env.example).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterable

from livekit import rtc
from livekit.agents import (
    Agent,
    AgentSession,
    AutoSubscribe,
    JobContext,
    WorkerOptions,
    cli,
    get_job_context,
    tokenize,
)
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions
from livekit.agents.tts import StreamAdapter
from livekit.agents.voice.agent import ModelSettings
from livekit.plugins import deepgram, elevenlabs, openai, silero

from .call_recording import export_session_wav
from .config import get_settings
from .metrics import Metrics, highlight, setup_logging
from .prompts import SYSTEM_PROMPT
from .reservation_client import ReservationClient
from .session_state import SessionState
from .tools import build_tools

AGENT_NAME = "Jawwad"


_AUDIO_TAG = re.compile(r"\[[^\[\]]+\]")

# v3 treats tags as direction, not an enum — but mild labels like [friendly]
# and [happy] barely change delivery. Map those to tags ElevenLabs documents.
_V3_TAG_MAP = {
    "warm": "excited",
    "warmly": "excited",
    "friendly": "excited",
    "happy": "excited",
    "happily": "excited",
    "reassuring": "curious",
    "sympathetic": "sighs",
    "chuckles": "laughs",
    "chuckle": "laughs",
}


def _canonical_v3_tag(tag: str) -> str:
    inner = tag.strip("[]").strip().lower()
    inner = _V3_TAG_MAP.get(inner, inner)
    return f"[{inner}]"


def _opening_beat(tag: str, rest: str) -> str:
    """v3 often ignores a tag on a short, even sentence. A tiny acted beat helps."""
    inner = tag.strip("[]")
    start = rest.lower().lstrip()
    if inner == "excited" and not start.startswith(("oh", "ah", "yes", "great", "wow")):
        return f"Oh! {rest}"
    if inner == "curious" and not start.startswith(("hmm", "oh?")):
        return f"Hmm — {rest}"
    return rest


def _prepare_v3_text(raw: str, *, default_tag: str = "[excited]") -> str:
    """One official v3 tag at the start of the reply.

    Repeating a mild tag on every sentence does not make v3 more expressive.
    """
    text = " ".join((raw or "").split())
    if not text:
        return text

    text = _AUDIO_TAG.sub(lambda m: _canonical_v3_tag(m.group(0)), text)
    tags = _AUDIO_TAG.findall(text)
    if len(tags) > 1 and len(set(tags)) == 1:
        text = " ".join(_AUDIO_TAG.sub("", text).split())
        text = f"{tags[0]} {text}"
    elif not tags:
        text = f"{default_tag} {text}"

    match = _AUDIO_TAG.match(text)
    if match:
        tag = match.group(0)
        rest = text[match.end() :].lstrip()
        text = f"{tag} {_opening_beat(tag, rest)}"
    return text


class _LoggingElevenTTS(elevenlabs.TTS):
    """Print the exact text ElevenLabs receives (including v3 audio tags)."""

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ):
        if "v3" in (self.model or "").lower():
            text = _prepare_v3_text(text)
        shown = " ".join((text or "").split())
        tags = _AUDIO_TAG.findall(shown)
        highlight(f"11labs {shown}")
        highlight(
            f"11labs tags  {', '.join(tags)}" if tags else "11labs tags  (none — no emotion tags)"
        )
        return super().synthesize(text, conn_options=conn_options)


class HostAgent(Agent):
    """Buffer a full reply, then one eleven_v3 HTTP request.

    Sentence-by-sentence streaming drops emotion tags, inserts a pause between
    sentences (so callers talk over the rest), and flushes incomplete PCM frames
    (clicks / cut-off endings).
    """

    async def tts_node(
        self, text: AsyncIterable[str], model_settings: ModelSettings
    ) -> AsyncIterable[rtc.AudioFrame]:
        activity = self._get_activity_or_raise()
        tts = activity.tts
        model = (getattr(tts, "model", "") or "").lower()
        if tts is None or "v3" not in model:
            async for frame in Agent.default.tts_node(self, text, model_settings):
                yield frame
            return

        parts: list[str] = []
        async for chunk in text:
            parts.append(chunk)
        spoken = "".join(parts).strip()
        if not spoken:
            return

        inner = getattr(tts, "_wrapped_tts", tts)
        conn_options = activity.session.conn_options.tts_conn_options
        async with inner.synthesize(spoken, conn_options=conn_options) as stream:
            async for audio in stream:
                yield audio.frame


def _build_tts(settings) -> elevenlabs.TTS | StreamAdapter:
    """Eleven v3 has no WebSocket API; HTTP synthesize is used per full reply."""
    uses_v3 = "v3" in settings.eleven_model_id.lower()
    kwargs: dict = dict(
        voice_id=settings.eleven_voice_id,
        model=settings.eleven_model_id,
        api_key=settings.eleven_api_key,
        apply_text_normalization="auto",
        encoding="pcm_24000" if uses_v3 else "mp3_22050_32",
        # v3 stability is discrete: 0.0 Creative, 0.5 Natural, 1.0 Robust.
        # Natural stays close to the reference voice and barely follows tags.
        voice_settings=elevenlabs.VoiceSettings(
            stability=0.0 if uses_v3 else 0.5,
            similarity_boost=0.75,
        ),
    )
    if uses_v3:
        kwargs["language"] = "en"
    eleven = _LoggingElevenTTS(**kwargs)
    if uses_v3:
        # Fallback if anything still calls stream(): hold until the turn ends.
        return StreamAdapter(
            tts=eleven,
            sentence_tokenizer=tokenize.blingfire.SentenceTokenizer(
                retain_format=True,
                min_token_len=10_000,
            ),
        )
    return eleven


async def entrypoint(ctx: JobContext) -> None:
    settings = get_settings(require_voice_secrets=True)
    # Re-apply after LiveKit CLI configures its own loggers
    log = setup_logging(settings.log_level, settings.log_dir)

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    participant = await ctx.wait_for_participant()

    session_id = uuid.uuid4().hex[:12]
    state = SessionState(session_id=session_id, channel="browser")
    metrics = Metrics(session_id, settings.log_dir)
    client = ReservationClient(
        settings.reservation_api_base_url,
        availability_max_retries=settings.availability_max_retries,
        on_latency=metrics.note_api_latency,
    )

    highlight("─" * 48)
    highlight(f"session  {session_id}  agent={AGENT_NAME}  room={ctx.room.name}")
    highlight(f"caller   {participant.identity}")
    highlight(f"api      {settings.reservation_api_base_url}")
    highlight(f"llm      deepseek/{settings.deepseek_model}")
    highlight(f"tts      {settings.eleven_model_id}  voice={settings.eleven_voice_id}  stability={'0.0-creative' if 'v3' in settings.eleven_model_id.lower() else '0.5'}")
    highlight("─" * 48)

    metrics.emit(
        "session_start",
        room=ctx.room.name,
        channel=state.channel,
        participant=participant.identity,
        agent=AGENT_NAME,
        llm="deepseek",
    )

    tools = build_tools(client)

    session = AgentSession(
        vad=silero.VAD.load(),
        stt=deepgram.STT(
            model="nova-3",
            api_key=settings.deepgram_api_key,
            smart_format=True,
            numerals=True,
        ),
        llm=openai.LLM.with_deepseek(
            model=settings.deepseek_model,
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
        ),
        tts=_build_tts(settings),
        userdata=state,
        # Explicit barge-in for T3 (works in both `dev` and `start`)
        allow_interruptions=True,
        min_interruption_duration=0.8,
    )

    agent = HostAgent(
        instructions=SYSTEM_PROMPT,
        tools=tools,
    )

    @session.on("conversation_item_added")
    def _on_item(ev) -> None:
        item = getattr(ev, "item", None)
        if item is None or getattr(item, "type", None) != "message":
            return
        report = dict(getattr(item, "metrics", None) or {})
        role = getattr(item, "role", None)
        text = getattr(item, "text_content", None)
        if role == "user":
            metrics.on_user_message(report, text=text)
        elif role == "assistant":
            metrics.on_assistant_message(report)

    @session.on("metrics_collected")
    def _on_metrics(ev) -> None:
        # Deprecated path kept as a fallback; primary latency is ChatMessage.metrics
        m = getattr(ev, "metrics", None)
        if m is not None:
            metrics.on_metrics(m)

    @session.on("function_tools_executed")
    def _on_tools(ev) -> None:
        calls = getattr(ev, "function_calls", None) or []
        for call in calls:
            name = getattr(call, "name", None) or getattr(call, "function_info", None)
            if hasattr(name, "name"):
                name = name.name
            highlight(f"tool  {name or 'unknown'}")

    # Local WAV: RecorderIO captures caller + agent, then we export on close.
    await session.start(
        agent=agent,
        room=ctx.room,
        record={
            "audio": True,
            "traces": False,
            "logs": False,
            "transcript": False,
        },
    )

    @session.on("close")
    def _on_close(_ev) -> None:
        try:
            job = get_job_context(required=False)
            session_dir = job.session_directory if job else None
            if session_dir is None:
                highlight("recording not saved (no session directory)")
                return
            path = export_session_wav(
                room_name=ctx.room.name,
                session_dir=session_dir,
                session_id=session_id,
            )
            if path:
                highlight(f"saved  {path}")
                log.info("recording_saved path=%s", path)
            else:
                highlight("recording not saved (no audio.ogg)")
        except Exception:
            log.exception("failed to export WAV recording")

    await session.generate_reply(
        allow_interruptions=False,
        instructions=(
            "Greet the caller briefly as the host from Bolt Voice Cafe. "
            "Start with [excited] Oh! then one short hello from Bolt Voice Cafe, and ask how you can help. "
            "Do not list booking, changing, or cancelling as options. Keep it to two short sentences."
        ),
    )

    @ctx.room.on("disconnected")
    def _on_disconnected(*_args, **_kwargs):
        summary = metrics.summary_line()
        metrics.emit("session_end", summary=state.summary(), latency=summary)
        highlight("─" * 48)
        highlight(f"ended  {summary}")
        highlight("─" * 48)
        log.info("session_end id=%s", session_id)


if __name__ == "__main__":
    # Quiet noisy loggers before the CLI takes over
    setup_logging("INFO")
    # Worker reads LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET from env.
    # agent_name enables explicit dispatch (token must request this name).
    get_settings(require_voice_secrets=True)
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, agent_name=AGENT_NAME))
