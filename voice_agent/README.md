# Luma Bistro Voice Agent

**Developed by [Jawwad Hassan](mailto:jawwadhassan76@gmail.com)** (`Jawwad2723`)

Real-time voice host for fictional restaurant **Luma Bistro**. Callers can check availability, create / modify / cancel reservations, and hand off to a human when needed.

**Stack:** LiveKit Agents (Python) · Deepgram STT · DeepSeek LLM · ElevenLabs TTS · browser WebRTC  
**Agent dispatch name:** `Jawwad`

---

## Demo video

**[Demo recording (Google Drive)](https://drive.google.com/file/d/1LuwEA1CmmLD7MwICfVN31t-Gtxc0uN_j/view?usp=sharing)**

---

## What’s built

- Browser demo: token server + mic UI → LiveKit room → agent worker
- Full reservation tools: availability, create, search, update, cancel, handoff
- Confirm-before-write gates (`confirm_pending_write`) for create / modify / cancel
- Input validation (phone, 30‑min slots, party 1–8, open hours)
- Availability **retry once** on temporary failure (Aug 16 / T6)
- **Idempotent create** — same guest + slot details → same confirmation (T7)
- Barge-in / interruption so callers can correct mid-sentence (T3)
- Clean agent logs + latency (`EOS → first audio`, API ms) for evaluation
- Unit / integration tests for validation + reservation client

---

## Evaluation results (from demo logs)

Source: `logs/agent.log` / `session_*.jsonl` (see also `../parse_voice_assessment_starter/EVALUATION_TEMPLATE.md`).

### Aggregates

| Metric | Value |
|---|---|
| Task success rate (T1–T7) | **7 / 7** |
| Tool-call accuracy | Matched expected flows (availability / confirm / create / search / update / cancel) |
| Duplicate-write rate (scored T7) | **0** — both creates returned `LUMA-5FEE` / `res_8b36a73e6b` |
| EOS → first audio p50 / p95 | **2575 / 4421 ms** (n=23) |
| API latency p50 / p95 | **14.5 / 74.1 ms** (n=17) |

### Per-test summary

| Test | Result | Outcome | EOS → audio (p50) | API highlight |
|---|---|---|---:|---|
| T1 Create | Pass | `LUMA-985B` · Jordan Lee · 2026-08-14 18:00 · party 4 | 2812 ms | create 8.1 ms |
| T2 Unavailable → alt | Pass | `LUMA-060B` · Taylor Kim · 19:30 (after 18:30 unavailable) | 2409 ms | check 28.3 ms (unavailable); create 10.5 ms |
| T3 Barge-in / correct | Pass | `LUMA-732B` · Casey Brown · party **4** (corrected from 2) | 2534 ms | create 13.6 ms |
| T4 Modify | Pass | Updated `LUMA-4821` → 19:30 · party 4 | 2796 ms | update 19.8 ms |
| T5 Cancel | Pass | Cancelled `LUMA-4821` once | 2351 ms | cancel 287.1 ms |
| T6 Temp failure | Pass | Aug 16 18:00 available after **attempts=2** | 2830 ms | check 17.0 ms |
| T7 Idempotency | Pass | Two creates → same `LUMA-5FEE` | 4421 ms / 2578 ms (two calls) | create 14.5 ms then 13.8 ms |

---

## Architecture

```
Browser (WebRTC) ──► LiveKit Cloud room
                          │
                          ▼
                   Jawwad agent worker
              ┌───────────┼───────────┐
              ▼           ▼           ▼
          Deepgram     DeepSeek   ElevenLabs
            STT          LLM         TTS
                          │
                          ▼
              Reservation tools (Python)
                          │
                          ▼
         Mock reservation API :8000
```

| Layer | Role |
|---|---|
| `web/token_server.py` + `web/index.html` | LiveKit tokens + `RoomAgentDispatch(agent_name="Jawwad")` + mic UI |
| `agent/main.py` | VAD → STT → LLM → tools → TTS; interruptions on |
| `agent/tools.py` | Function tools + confirm gates |
| `agent/reservation_client.py` | HTTP client: 503 retry-once, idempotency on create |
| `agent/validation.py` | Phone / time / party / hours |
| `agent/metrics.py` | Demo-friendly latency + API highlights |

Mock API: `../parse_voice_assessment_starter/` (in-memory; `/admin/reset`).

---

## Improvements (vs a bare starter loop)

| Area | What I added |
|---|---|
| Writes | Explicit confirm tool before create / modify / cancel |
| Duplicates | Idempotency key = hash(name + phone + date + time + party) — stable across calls |
| Reliability | Availability retries once on temporary failure; no invented slots |
| Latency visibility | EOS→audio + per-API timings in terminal and `logs/` |
| UX | Greeting asks how it can help (no booking/cancel menu dump) |
| Browser mic | UI checks secure context; open **http://127.0.0.1:8080** (not `0.0.0.0` / LAN IP) |
| Barge-in | Interruptions enabled; short min-speech so coughs don’t cancel |
| Safety | Party > 8 → handoff; `record=False` (no demo session recording) |

---

## Cost (~5 minute call)

| Service | ~Cost |
|---|---:|
| Deepgram STT | $0.02 |
| DeepSeek LLM | $0.00016 |
| ElevenLabs TTS | $0.25 |
| LiveKit | $0.0286 |
| **Total** | **~$0.30** |

TTS dominates. Recheck against provider invoices after real traffic.

---

## Secrets (`.env`)

```bash
cd voice_agent
cp .env.example .env
# Set LIVEKIT_*, DEEPGRAM_*, DEEPSEEK_*, ELEVEN_*
```

Never commit `.env`.

---

## Run (3 terminals)

**A — Reservation API**

```bash
cd ../parse_voice_assessment_starter
../voice_agent/.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000
```

**B — Agent worker**

```bash
cd ../voice_agent && source .venv/bin/activate
set -a; source .env; set +a
python -m agent.main dev
```

**C — Browser UI**

```bash
python -m web.token_server
# Open http://127.0.0.1:8080  (required for mic)
```

Use `dev` for local demos (including barge-in). `start` is the production-style worker.

---

## Bookable dates

Mock inventory: **2026-08-14**, **2026-08-15**, **2026-08-16**.  
Seed for modify/cancel: **LUMA-4821** / Alex Morgan / `+13105550147`.

---

## Limits

- Three assessment dates only (mock API)
- Party > 8 → handoff
- First availability on **2026-08-16** → temporary failure, then retry
- In-memory reservations (API restart clears; use `/admin/reset`)
- Browser path in this README (Twilio keys reserved for later)
- No local WAV export (`record=False`)

---

## Scaling

| Load | Approach |
|---|---|
| ~10 calls | One box, a few agent workers |
| ~100 | Multiple workers; real DB for reservations; watch provider quotas |
| ~1000 | Horizontal workers, shared idempotency store, autoscaling, rate-limited handoff |

---

## Tests

```bash
pytest tests/test_validation.py -q
pytest tests/test_client.py -q   # needs API on :8000
```

---

## Project layout

```
voice_agent/
  agent/          # worker, tools, validation, metrics, prompts
  web/            # token server + browser UI
  tests/
  docs/           # put demo.mp4 here for GitHub inline playback
  logs/           # session JSONL + agent.log (gitignored)
  .env.example
```

Also useful: repo-root `COMMANDS.md`, starter `EVALUATION_TEMPLATE.md`, `standard_test_cases.json`.
