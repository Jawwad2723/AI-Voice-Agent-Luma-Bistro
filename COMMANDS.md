# Luma Bistro Voice Agent — Commands Cheat Sheet

Project root: `/Users/apple/Documents/Call`

---

## One-time setup

```bash
export PATH="$HOME/.local/bin:$PATH"

cd /Users/apple/Documents/Call/voice_agent
uv python install 3.12
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -r requirements.txt
uv pip install 'cryptography>=42,<45'
uv pip install 'livekit-plugins-openai~=1.0'

cp .env.example .env
# edit .env with LIVEKIT_*, DEEPGRAM_*, DEEPSEEK_*, ELEVEN_*
```

---

## Start everything (one command)

From the repo root:

```bash
./start.sh
```

Creates the Python 3.12 venv if needed, installs deps, and starts the reservation API, agent worker, and browser UI. Open **http://127.0.0.1:8080**. Ctrl+C stops all three.

---

## Start everything (3 terminals, manual)

### Terminal A — Reservation API

```bash
export PATH="$HOME/.local/bin:$PATH"
cd /Users/apple/Documents/Call/parse_voice_assessment_starter
../voice_agent/.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000
```

Or with Docker:

```bash
cd /Users/apple/Documents/Call/parse_voice_assessment_starter
docker compose up --build
```

API: http://localhost:8000  
Swagger: http://localhost:8000/docs

### Terminal B — Voice agent worker

```bash
export PATH="$HOME/.local/bin:$PATH"
cd /Users/apple/Documents/Call/voice_agent
source .venv/bin/activate
set -a; source .env; set +a
python -m agent.main dev      # demos + barge-in (T3) — preferred
# python -m agent.main start # production-style worker
```

`dev` = LiveKit development worker (`LIVEKIT_DEV_MODE`, looser load defaults).  
`start` = production-style worker. Interruptions are enabled in code for both; use **`dev` for the assessment demo**.

### Terminal C — Browser UI + token server

```bash
export PATH="$HOME/.local/bin:$PATH"
cd /Users/apple/Documents/Call/voice_agent
source .venv/bin/activate
set -a; source .env; set +a
python -m web.token_server
```

Then open: **http://localhost:8080**

---

## Restart agent only

```bash
pkill -f "python -m agent.main" || true
cd /Users/apple/Documents/Call/voice_agent
source .venv/bin/activate
set -a; source .env; set +a
python -m agent.main dev
```

## Restart browser UI only

```bash
pkill -f "python -m web.token_server" || true
cd /Users/apple/Documents/Call/voice_agent
source .venv/bin/activate
set -a; source .env; set +a
python -m web.token_server
```

## Restart reservation API only

```bash
pkill -f "uvicorn app:app" || true
cd /Users/apple/Documents/Call/parse_voice_assessment_starter
../voice_agent/.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000
```

---

## Stop everything

```bash
pkill -f "python -m agent.main" || true
pkill -f "python -m web.token_server" || true
pkill -f "uvicorn app:app" || true
```

---

## Health checks

```bash
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8080/health
```

---

## Reset mock reservation data

```bash
curl -s -X POST http://127.0.0.1:8000/admin/reset
```

---

## Run tests

```bash
cd /Users/apple/Documents/Call/voice_agent
source .venv/bin/activate
PYTHONPATH=. pytest tests/ -q
```

---
