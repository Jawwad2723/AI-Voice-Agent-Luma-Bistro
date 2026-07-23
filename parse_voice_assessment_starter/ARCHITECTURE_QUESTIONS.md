# Architecture Questions

1. Why this voice framework, STT, LLM, TTS, and transport?

LiveKit Agents was the path of least pain for a real-time voice loop — room join, mic/audio, and tool calling without me wiring WebRTC from scratch. Browser WebRTC over LiveKit Cloud is what I ship for the demo; Twilio can hang off the same agent later if I need a phone number.

Deepgram for STT because streaming transcripts are decent and it plugs into LiveKit cleanly. DeepSeek for the LLM — cheap enough for a host that mostly collects fields and calls tools, and the openai-compatible plugin meant I didn’t fight a custom client. ElevenLabs for TTS so the host doesn’t sound like a robot reading a script. Could swap any of these later; the agent session is the stable bit.

2. How is session and reservation state stored?

There are two separate memory spaces.

On the agent worker, each LiveKit job gets a `SessionState` object hung on the session as `userdata` — name, phone, date/time, party size, confirm flags (`create_confirmed` / etc.), last confirmation code, idempotency key, short notes for handoff. That lives only for the life of that room/process. Hang up → it’s gone.

Reservations themselves are owned by the mock API process: an in-memory dict keyed by reservation id, plus a separate dict for idempotency keys. Nothing is flushed to disk. Restart or `/admin/reset` and you’re back to the seed booking. In production I’d put reservations in a real DB and treat agent session state as ephemeral (or Redis if I needed it across workers).

3. How do you cancel generation during barge-in?

Technically it goes through the LiveKit voice session turn loop. I turn interruptions on for the session (`allow_interruptions=True`, and I require about 0.4s of speech before counting it so a cough doesn’t kill the reply).

While the agent is talking, Silero VAD is still listening on the caller’s mic. If it hears real speech over the agent, the session marks an interrupt and cancels the current `SpeechHandle` for that reply. Cancelling that handle does two things at once: it stops flushing ElevenLabs audio to the room (so playback cuts off), and it aborts the in-flight generation for that turn (LLM tokens / TTS synthesis tied to that handle don’t keep running as if the caller wasn’t talking).

After that, Deepgram finishes the new utterance, that text becomes the next user turn, and the LLM answers from the updated state — e.g. party size 4 instead of 2. I’m not manually calling a custom “cancel LLM” API in my code; LiveKit’s agent runtime owns stopping the active speech when interruption fires.

4. How are tool arguments validated?

Validation is in my tool layer, not “trust the LLM.” When DeepSeek calls something like `check_availability` or `create_reservation`, the Python tool runs first:

1. Parse/normalize — phone digits → `+1…`, spoken times → `HH:MM` on 30-minute slots, dates to `YYYY-MM-DD`.
2. Hard checks — party 1–8 (over 8 returns handoff), hours Tue–Sun 5–10pm Pacific, closed Mondays.
3. On failure I return a small JSON error (`ok: false`, a code, a message) straight back into the tool result. No HTTP call to the reservation API happens for that bad payload; the model just sees the error and asks the caller again.

For create / modify / cancel there’s an extra gate: the tool refuses to write unless `confirm_pending_write` already flipped the matching flag on `SessionState` after the caller said yes. So even a hallucinated tool call mid-sentence can’t POST a reservation without that confirm step.

5. How are duplicate writes prevented?

Two layers.

First, confirmation: create won’t run until `create_confirmed` is true on session state (same idea for modify/cancel). That stops accidental double-clicks from the model before any HTTP.

Second, HTTP idempotency on create. After fields validate, I build a SHA-256 key from `name|phone|date|time|party_size` (normalized values — no session id, so a second call with the same booking details reuses the key). That string goes out as the `Idempotency-Key` header on `POST /reservations`. The mock API keeps a map of key → reservation body. First time: create and store. Second time with the same key: return the stored body, don’t allocate another table or burn more capacity. That’s why Morgan Friday 8pm twice still lands on one confirmation code.

6. Which failures are retried?

Only the availability check in my HTTP client. Loop is: call `GET /availability` → if the status is a temporary failure (the Aug 16 test returns that on the first hit), sleep for the suggested wait (or about half a second) → call once more. Max two attempts total. If the second one works, I pass `available` / alternatives back to the model with `attempts=2` in the result. If both fail, I raise that up to the tool, the model is told to apologize and hand off, and I never invent a free slot.

Create / update / cancel are not in that retry loop. Create relies on the idempotency key if the same request is sent again; other errors just come back as tool failures for the model to handle.

7. How is context preserved during handoff?

When the model calls `handoff_to_human`, I don’t move the LiveKit participant to a human agent. I snapshot what I already have on `SessionState` via `summary()` — notes from the call, name, phone, requested slot, party size, confirmation / reservation id if any — plus the reason string the model passed in. That text goes in a `POST /handoff` body with the phone. The mock API appends it to an in-memory handoff queue and returns a handoff id / queued status. A real ops UI would read that queue next to the call. If the agent process dies after that, the summary still sits on the API side for that demo run (until reset).

8. Which production metrics and logs matter?

What I wire up and watch:

- Per-turn latency from LiveKit `ChatMessage.metrics` — mainly `e2e_latency` (end of user speech → agent starts responding), plus LLM TTFT and TTS TTFB when present. I log those as `lat` / `turn` lines.
- Reservation API wall time in my HTTP client (`perf_counter` around each call) — printed as `api … ms`, including availability after a retry.
- Tool names when a function batch finishes, and session start/end with a short summary.

Those go to the agent terminal (quieting LiveKit noise) and to `logs/agent.log` + `logs/session_<id>.jsonl` so I can fill the eval table from real numbers. In production I’d add error rate by tool, retry/503 counts, barge-in rate, handoff rate, and alerts on EOS→audio / API p95.

9. How would the system change at 10, 100, and 1,000 concurrent calls?

At ~10 concurrent calls one machine running a few agent workers is probably fine if provider quotas hold.

At ~100 I’d run multiple worker processes (or boxes) against the same LiveKit project, watch CPU on VAD/TTS, and make sure Deepgram/DeepSeek/ElevenLabs limits aren’t the bottleneck. The mock API would need to become a real service with a shared DB — one uvicorn process with a dict won’t cut it.

At ~1,000 you’re in horizontal scale territory: many agent workers, autoscaling, a proper reservation service with connection pooling, shared idempotency store, and probably rate limits / queueing on handoff. LiveKit handles room fan-out; the hard parts are provider cost/quota and keeping reservation writes consistent.

10. What would you improve in the supplied API?

Persist reservations (Postgres or similar) so restarts don’t wipe demos. Return clearer error bodies and maybe a `Idempotency-Replayed: true` header so the agent can say “you already have this booking” without guessing. List/search with pagination. Soft-delete or audit on cancel. Capacity as a first-class resource with optimistic locking so two creates can’t overbook the same slot under race. And document the Aug 16 503 behavior as a test hook, not a mystery.

11. How would you protect PII, recordings, transcripts, and secrets?

Secrets stay in `.env` / a secret manager — never in the browser except a short-lived LiveKit room token. I don’t turn on session recording for the demo (`record=False`). In production: encrypt transcripts and any recordings at rest, short retention, access logs, redact phone/name in log lines where you don’t need them, TLS everywhere, and don’t put raw PII in provider prompts longer than the call needs. Staff handoff views should be permissioned.

12. Estimate cost per five-minute call.

Rough numbers for a ~5 minute call on this stack (depends how much the host talks):

| Service | ~Cost |
|---|---:|
| Deepgram STT | $0.02 |
| DeepSeek LLM | $0.00016 |
| ElevenLabs TTS | $0.25 |
| LiveKit | $0.0286 |
| **Total** | **~$0.30** |

TTS is basically the whole bill. DeepSeek is noise. I’d re-check against real invoices after a few days of traffic.
