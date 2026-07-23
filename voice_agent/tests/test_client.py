"""Integration tests against the live reservation API.

Requires API at RESERVATION_API_BASE_URL (default http://localhost:8000).
Voice provider secrets are NOT required.
"""

from __future__ import annotations

import os

import pytest

from agent.reservation_client import ReservationClient, make_idempotency_key

BASE = os.getenv("RESERVATION_API_BASE_URL", "http://localhost:8000").rstrip("/")


@pytest.fixture
async def client():
    c = ReservationClient(BASE, availability_max_retries=1)
    try:
        await c.health()
    except Exception as e:
        await c.aclose()
        pytest.skip(f"Reservation API not reachable at {BASE}: {e}")
    await c.reset()
    yield c
    await c.aclose()


@pytest.mark.asyncio
async def test_create_available(client: ReservationClient):
    avail = await client.check_availability(
        date="2026-08-14", time="18:00", party_size=4
    )
    assert avail["available"] is True
    key = make_idempotency_key(
        name="Jordan Lee",
        phone="+13105550199",
        date="2026-08-14",
        time="18:00",
        party_size=4,
    )
    r = await client.create_reservation(
        name="Jordan Lee",
        phone="310-555-0199",
        date="2026-08-14",
        time="18:00",
        party_size=4,
        notes=None,
        idempotency_key=key,
    )
    assert r["confirmation_code"].startswith("LUMA-")
    assert r["party_size"] == 4


@pytest.mark.asyncio
async def test_unavailable_offers_alternatives(client: ReservationClient):
    avail = await client.check_availability(
        date="2026-08-14", time="18:30", party_size=4
    )
    assert avail["available"] is False
    assert isinstance(avail["alternatives"], list)
    assert len(avail["alternatives"]) >= 1


@pytest.mark.asyncio
async def test_modify_existing(client: ReservationClient):
    found = await client.search_reservations(confirmation_code="LUMA-4821")
    assert len(found["results"]) == 1
    rid = found["results"][0]["reservation_id"]
    updated = await client.update_reservation(
        rid, time="19:30", party_size=4
    )
    assert updated["time"] == "19:30"
    assert updated["party_size"] == 4


@pytest.mark.asyncio
async def test_cancel_existing(client: ReservationClient):
    found = await client.search_reservations(confirmation_code="LUMA-4821")
    rid = found["results"][0]["reservation_id"]
    cancelled = await client.cancel_reservation(rid)
    assert cancelled["status"] == "cancelled"


@pytest.mark.asyncio
async def test_availability_503_retries_once(client: ReservationClient):
    # First call after reset for 2026-08-16 returns 503; client retries.
    result = await client.check_availability(
        date="2026-08-16", time="18:00", party_size=2
    )
    assert result["available"] is True
    assert result["_attempts"] == 2


@pytest.mark.asyncio
async def test_idempotency_duplicate_protection(client: ReservationClient):
    key = make_idempotency_key(
        name="Morgan Reed",
        phone="+13105550166",
        date="2026-08-14",
        time="20:00",
        party_size=2,
    )
    r1 = await client.create_reservation(
        name="Morgan Reed",
        phone="310-555-0166",
        date="2026-08-14",
        time="20:00",
        party_size=2,
        notes=None,
        idempotency_key=key,
    )
    r2 = await client.create_reservation(
        name="Morgan Reed",
        phone="310-555-0166",
        date="2026-08-14",
        time="20:00",
        party_size=2,
        notes=None,
        idempotency_key=key,
    )
    assert r1["reservation_id"] == r2["reservation_id"]
    assert r1["confirmation_code"] == r2["confirmation_code"]


@pytest.mark.asyncio
async def test_handoff_preserves_summary(client: ReservationClient):
    h = await client.handoff(
        reason="party_too_large",
        conversation_summary="Guest wants table for 12 on Aug 14",
        customer_phone="+13105550199",
    )
    assert h["status"] == "queued"
    assert h["conversation_summary"].startswith("Guest wants")
