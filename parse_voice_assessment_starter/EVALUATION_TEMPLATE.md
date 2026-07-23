# Evaluation Results — Luma Bistro Voice Agent

**Author:** Jawwad Hassan  
**Stack:** LiveKit Agents · Deepgram STT · DeepSeek · ElevenLabs TTS · browser WebRTC  
**Agent run mode:** `python -m agent.main dev`  
**Log source:** `voice_agent/logs/agent.log` + `session_*.jsonl`

---

## Summary

| Metric | Result |
|---|---|
| Task success (T1–T7) | **7 / 7 Pass** |
| Duplicate writes (scored T7) | **0** (same confirmation on replay) |
| EOS → first audio | **p50 = 2575 ms** · **p95 = 4421 ms** (n = 23) |
| Reservation API latency | **p50 = 14.5 ms** · **p95 = 74.1 ms** (n = 17) |

### Metric definitions

| Metric | Meaning |
|---|---|
| EOS → first audio | Time from caller finished speaking until agent audio starts (ms) |
| API latency | Wall time for the mock reservation HTTP call (ms). Availability may include one retry. |

---

## Results table

| Test | Pass/Fail | Final outcome | Tool calls | Duplicate/wrong write? | End-of-speech to first audio | API latency | Notes |
|---|---|---|---|---|---|---|---|
| T1 | Pass | Created LUMA-985B · Jordan Lee · +13105550199 · 2026-08-14 18:00 · party 4 · res_6868ddcd90 | check_availability → confirm_pending_write → create_reservation | No | 1985 · 3672 · 2812 ms; p50=2812 · p95=3672 (n=3) | check 9.3 ms; create 8.1 ms; API p50=8.1 (n=2) | session=`5ab83eceb87d`. hear: reserve 4 Friday Aug 14 6PM; Jordan Lee 310-555-0199; No notes; Yes. Confirm. |
| T2 | Pass | Created LUMA-060B · Taylor Kim · +14245550188 · 2026-08-14 19:30 · party 4 · res_a126734839 | check_availability → confirm_pending_write → create_reservation | No | 2408 · 2295 · 1913 · 2800 ms; p50=2409 · p95=2800 (n=4) | check 28.3 ms available=False @ 18:30; create 10.5 ms @ 19:30; API p50=10.5 (n=2) | session=`d15840fd30d0`. hear: Book 4 … 06:30PM; I can do 07:30PM instead; Taylor Kim; Yes. |
| T3 | Pass | Created LUMA-732B · Casey Brown · +12135550114 · 2026-08-15 18:30 · party 4 · res_883d27cc3c | check_availability → check_availability → confirm_pending_write → create_reservation | No | 2245 · 1920 · 2534 · 2575 ms; p50=2534 · p95=2575 (n=4) | check 31.3 ms; check 13.5 ms; create 13.6 ms; API p50=13.6 (n=3) | session=`83982272fe2a`. hear: Saturday Aug 15 06:30PM for 2; Casey Brown; Sorry… make that for 4 people; Yes. Confirm, please. Party size 4 in session_end. Use `python -m agent.main dev`; barge-in enabled. |
| T4 | Pass | Updated LUMA-4821 · Alex Morgan · +13105550147 · 2026-08-14 19:30 · party 4 · res_existing_4821 | search_reservations → check_availability → confirm_pending_write → update_reservation | No | 2477 · 2988 · 2796 ms; p50=2796 · p95=2988 (n=3) | search 9.1 ms hits=1; check 11.3 ms @ 19:30; update 19.8 ms; API p50=11.3 (n=3) | session=`ca8704cc1948`. hear: change reservation Luma 4 8 2 1…; make it for 4 people; Confirm Confirm. Seed: LUMA-4821 / +13105550147. |
| T5 | Pass | Cancelled LUMA-4821 · Alex Morgan · +13105550147 · 2026-08-14 19:30 · party 4 · res_existing_4821 | search_reservations → confirm_pending_write → cancel_reservation | No (cancel once) | 2351 · 2304 · 4355 ms; p50=2351 · p95=4355 (n=3) | search 33.8 ms hits=1; cancel 287.1 ms; API p50=33.8 (n=2) | session=`b81a3464f103`. hear: Cancel … luma 4 8 2 1; I would like to cancel it; Yes. Cancel it. Seed: LUMA-4821 / +13105550147. |
| T6 | Pass | Requested 2026-08-16 18:00 · party 2; available after retry | check_availability | No | 2830 ms | check 17.0 ms available=True attempts=2 date=2026-08-16 time=18:00 | session=`1ac6da5a0cc0`. hear: Please check Sunday, August 16 at 6PM for 2. attempts=2 = first 503 then retry success; never invent a result. |
| T7 | Pass | Both creates → LUMA-5FEE · Morgan Reed · +13105550166 · 2026-08-14 20:00 · party 2 · res_8b36a73e6b | Each call: check_availability → confirm_pending_write → create_reservation | No — same code LUMA-5FEE / same reservation_id | Call1: 1947 · 4421 · 6543 ms (p50=4421 · p95=6543). Call2: 2578 · 3086 ms (p50=2578 · p95=3086) | Call1: check 74.1 · create 14.5. Call2: check 15.4 · create 13.8 | sessions=`6d94fd65b57a` then `78872420a75b`. Both session_end summaries: Created LUMA-5FEE … Reservation ID: res_8b36a73e6b. |

---

## Aggregates

| Metric | Value |
|---|---|
| Task success rate (T1–T7) | 7/7 |
| Tool-call accuracy | Tools matched expected flows in logs (availability / confirm / create / search / update / cancel) |
| Duplicate-write rate | 0 for scored T7 (same LUMA-5FEE / res_8b36a73e6b). Earlier pre-fix runs created LUMA-44FB then LUMA-8468 (different keys) — not counted as the scored T7. |
| EOS→audio p50 / p95 (across demos) | 2575 / 4421 ms (n=23) |
| API latency p50 / p95 | 14.5 / 74.1 ms (n=17; includes cancel 287.1 ms as outlier above p95) |

---

## Known limitations

| Topic | Note |
|---|---|
| Dates | Mock inventory only: 2026-08-14 · 15 · 16 |
| Party size | > 8 → human handoff |
| Persistence | API is in-memory; restart / reset clears bookings |
| Channel | Browser WebRTC for this demo |
| Recording | `record=False` — no local WAV export |

---

## Environment used

| Component | Status |
|---|---|
| Reservation API `:8000` | Yes |
| Agent `python -m agent.main dev` | Yes |
| UI `http://127.0.0.1:8080` | Yes |
| LiveKit / Deepgram / DeepSeek / ElevenLabs keys | Yes |
| Seed `LUMA-4821` for T4/T5 | Yes |
