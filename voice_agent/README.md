# Luma Bistro Voice Agent

Real-time voice host for Luma Bistro reservations.

**Stack:** LiveKit Agents · Deepgram STT · DeepSeek · ElevenLabs TTS · browser WebRTC (+ Twilio later)

## Secrets (.env)

All API keys and tokens live in `voice_agent/.env`. Never commit this file.

```bash
cd voice_agent
cp .env.example .env
# Edit .env and set real values for LIVEKIT_*, DEEPGRAM_*, DEEPSEEK_*, ELEVEN_*, TWILIO_*
```

| Variable | Purpose |
|---|---|
| `RESERVATION_API_BASE_URL` | Mock API (default `http://localhost:8000`) |
| `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` | LiveKit Cloud |
| `DEEPGRAM_API_KEY` | Streaming STT |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL` | DeepSeek LLM |
| `ELEVEN_API_KEY` / `ELEVEN_VOICE_ID` | Streaming TTS |
| `TWILIO_*` | Phone ingress (Phase 5) |

`.env` is gitignored. Only `.env.example` (placeholders) is tracked.

## Prerequisites

- Python **3.10+**
- Docker (recommended) for the reservation API, or run the starter with uvicorn
- Provider accounts + keys in `.env`

## 1. Start the reservation API

```bash
cd ../parse_voice_assessment_starter
docker compose up --build
# API: http://localhost:8000  Swagger: http://localhost:8000/docs
```

## 2. Install the agent

```bash
cd ../voice_agent
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3. Run tests (API only — no voice keys needed)

```bash
pytest tests/test_validation.py -q
pytest tests/test_client.py -q   # requires API on :8000
```

## 4. Run the voice agent

```bash
# Terminal A — agent worker (loads secrets from .env)
python -m agent.main dev

# Terminal B — browser token + UI server
python -m web.token_server
# Open http://localhost:8080
```

## Project layout

See `IMPLEMENTATION_PLAN.md` in the repo root for architecture, flows, and phases.
