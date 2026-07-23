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
from livekit.plugins import deepgram, elevenlabs, openai, silero

from .config import get_settings
from .metrics import Metrics, highlight, setup_logging
from .prompts import SYSTEM_PROMPT
from .reservation_client import ReservationClient
from .session_state import SessionState
from .tools import build_tools

AGENT_NAME = "Jawwad"


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
        tts=elevenlabs.TTS(
            voice_id=settings.eleven_voice_id,
            model=settings.eleven_model_id,
            api_key=settings.eleven_api_key,
        ),
        userdata=state,
        # Explicit barge-in for T3 (works in both `dev` and `start`)
        allow_interruptions=True,
        min_interruption_duration=0.4,
    )

    agent = Agent(
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

    # record=False: ignore LiveKit Cloud enable_recording
    await session.start(agent=agent, room=ctx.room, record=False)

    await session.generate_reply(
        instructions=(
            "Greet the caller briefly as the host from Luma Bistro. "
            "Introduce yourself from Luma Bistro, then ask how you can help. "
            "Do not list booking, changing, or cancelling as options."
        )
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
