"""Luma Bistro LiveKit voice agent entrypoint.

Secrets are loaded exclusively from voice_agent/.env (see .env.example).
"""

from __future__ import annotations

import uuid

from livekit.agents import (
    Agent,
    AgentSession,
    AutoSubscribe,
    JobContext,
    WorkerOptions,
    cli,
)
from livekit.plugins import deepgram, elevenlabs, google, silero

from .config import get_settings
from .metrics import Metrics, setup_logging
from .prompts import SYSTEM_PROMPT
from .reservation_client import ReservationClient
from .session_state import SessionState
from .tools import build_tools


async def entrypoint(ctx: JobContext) -> None:
    settings = get_settings(require_voice_secrets=True)
    log = setup_logging(settings.log_level, settings.log_dir)

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    participant = await ctx.wait_for_participant()

    session_id = uuid.uuid4().hex[:12]
    state = SessionState(session_id=session_id, channel="browser")
    metrics = Metrics(session_id, settings.log_dir)
    client = ReservationClient(
        settings.reservation_api_base_url,
        availability_max_retries=settings.availability_max_retries,
    )

    log.info(
        "session_start id=%s room=%s participant=%s api=%s model=%s",
        session_id,
        ctx.room.name,
        participant.identity,
        settings.reservation_api_base_url,
        settings.gemini_model,
    )
    metrics.emit(
        "session_start",
        room=ctx.room.name,
        channel=state.channel,
        participant=participant.identity,
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
        llm=google.LLM(
            model=settings.gemini_model,
            api_key=settings.google_api_key,
        ),
        tts=elevenlabs.TTS(
            voice_id=settings.eleven_voice_id,
            model=settings.eleven_model_id,
            api_key=settings.eleven_api_key,
        ),
        userdata=state,
    )

    agent = Agent(
        instructions=SYSTEM_PROMPT,
        tools=tools,
    )

    await session.start(agent=agent, room=ctx.room)

    await session.generate_reply(
        instructions=(
            "Greet the caller briefly as Luma Bistro's host. "
            "Offer to help with a new reservation, changing one, or cancelling."
        )
    )

    @ctx.room.on("disconnected")
    def _on_disconnected(*_args, **_kwargs):
        metrics.emit("session_end", summary=state.summary())
        log.info("session_end id=%s", session_id)


if __name__ == "__main__":
    # Worker reads LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET from env.
    get_settings(require_voice_secrets=True)
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
