# Twilio + LiveKit telephony setup (Phase 5)

Secrets live in `voice_agent/.env` only:

- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_PHONE_NUMBER`

## Goal

Inbound calls to the Twilio number join the same LiveKit agent used by the browser demo.

## High-level steps

1. Create a Twilio US local number.
2. In LiveKit Cloud, create a SIP inbound trunk / dispatch rule that points to your agent.
3. Configure Twilio to send voice to LiveKit SIP (URI from LiveKit dashboard).
4. Place a test call; confirm the greeting and one reservation flow.

Detailed wiring will be filled after the browser path is stable.
