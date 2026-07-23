"""HTTP client for the Luma Bistro mock reservation API."""

from __future__ import annotations

import asyncio
import hashlib
import time as time_mod
from collections.abc import Callable
from typing import Any, Optional

import httpx

LatencyCallback = Callable[..., None]


class ReservationAPIError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        detail: Any = None,
        *,
        retry_after_ms: Optional[int] = None,
    ):
        self.status_code = status_code
        self.code = code
        self.detail = detail
        self.retry_after_ms = retry_after_ms
        super().__init__(f"{status_code} {code}: {detail}")


def make_idempotency_key(
    *,
    name: str,
    phone: str,
    date: str,
    time: str,
    party_size: int,
) -> str:
    """Stable key from booking fields only — same guest/slot → same key across calls."""
    raw = f"{name.strip().lower()}|{phone}|{date}|{time}|{party_size}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ReservationClient:
    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        *,
        availability_max_retries: int = 1,
        timeout: float = 10.0,
        on_latency: Optional[LatencyCallback] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.availability_max_retries = availability_max_retries
        self._on_latency = on_latency
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    def _report(self, name: str, latency_ms: float, **extra: Any) -> None:
        if self._on_latency:
            self._on_latency(name, round(latency_ms, 1), **extra)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "ReservationClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    def _parse_error(self, resp: httpx.Response) -> ReservationAPIError:
        try:
            body = resp.json()
        except Exception:
            body = {"detail": resp.text}
        detail = body.get("detail", body)
        code = "UNKNOWN"
        retry_after_ms = None
        if isinstance(detail, dict):
            code = detail.get("code", code)
            retry_after_ms = detail.get("retry_after_ms")
        return ReservationAPIError(
            resp.status_code, code, detail, retry_after_ms=retry_after_ms
        )

    async def health(self) -> dict:
        resp = await self._client.get("/health")
        resp.raise_for_status()
        return resp.json()

    async def get_restaurant(self) -> dict:
        t0 = time_mod.perf_counter()
        resp = await self._client.get("/restaurant")
        latency_ms = (time_mod.perf_counter() - t0) * 1000
        if resp.status_code >= 400:
            raise self._parse_error(resp)
        data = resp.json()
        data["_latency_ms"] = round(latency_ms, 1)
        self._report("get_restaurant", latency_ms)
        return data

    async def check_availability(
        self, *, date: str, time: str, party_size: int
    ) -> dict:
        """GET /availability with one retry on temporary 503 (assessment T6)."""
        attempts = 0
        max_attempts = 1 + max(0, self.availability_max_retries)
        last_error: Optional[ReservationAPIError] = None
        total_ms = 0.0

        while attempts < max_attempts:
            attempts += 1
            t0 = time_mod.perf_counter()
            resp = await self._client.get(
                "/availability",
                params={"date": date, "time": time, "party_size": party_size},
            )
            latency_ms = (time_mod.perf_counter() - t0) * 1000
            total_ms += latency_ms
            if resp.status_code == 503:
                err = self._parse_error(resp)
                last_error = err
                if attempts < max_attempts:
                    wait_ms = err.retry_after_ms or 500
                    await asyncio.sleep(wait_ms / 1000)
                    continue
                self._report(
                    "check_availability",
                    total_ms,
                    status=503,
                    attempts=attempts,
                    date=date,
                    time=time,
                )
                raise err
            if resp.status_code >= 400:
                raise self._parse_error(resp)
            data = resp.json()
            data["_latency_ms"] = round(total_ms, 1)
            data["_attempts"] = attempts
            self._report(
                "check_availability",
                total_ms,
                available=data.get("available"),
                attempts=attempts,
                date=date,
                time=time,
            )
            return data

        assert last_error is not None
        raise last_error

    async def create_reservation(
        self,
        *,
        name: str,
        phone: str,
        date: str,
        time: str,
        party_size: int,
        notes: Optional[str],
        idempotency_key: str,
    ) -> dict:
        payload = {
            "name": name,
            "phone": phone,
            "date": date,
            "time": time,
            "party_size": party_size,
            "notes": notes,
        }
        t0 = time_mod.perf_counter()
        resp = await self._client.post(
            "/reservations",
            json=payload,
            headers={"Idempotency-Key": idempotency_key},
        )
        latency_ms = (time_mod.perf_counter() - t0) * 1000
        if resp.status_code >= 400:
            self._report("create_reservation", latency_ms, status=resp.status_code)
            raise self._parse_error(resp)
        data = resp.json()
        data["_latency_ms"] = round(latency_ms, 1)
        self._report(
            "create_reservation",
            latency_ms,
            code=data.get("confirmation_code"),
            date=date,
            time=time,
        )
        return data

    async def search_reservations(
        self,
        *,
        phone: Optional[str] = None,
        confirmation_code: Optional[str] = None,
    ) -> dict:
        params: dict[str, str] = {}
        if phone:
            params["phone"] = phone
        if confirmation_code:
            params["confirmation_code"] = confirmation_code
        t0 = time_mod.perf_counter()
        resp = await self._client.get("/reservations/search", params=params)
        latency_ms = (time_mod.perf_counter() - t0) * 1000
        if resp.status_code >= 400:
            raise self._parse_error(resp)
        data = resp.json()
        data["_latency_ms"] = round(latency_ms, 1)
        self._report(
            "search_reservations",
            latency_ms,
            hits=len(data.get("results") or []),
        )
        return data

    async def update_reservation(
        self,
        reservation_id: str,
        *,
        date: Optional[str] = None,
        time: Optional[str] = None,
        party_size: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> dict:
        payload: dict[str, Any] = {}
        if date is not None:
            payload["date"] = date
        if time is not None:
            payload["time"] = time
        if party_size is not None:
            payload["party_size"] = party_size
        if notes is not None:
            payload["notes"] = notes
        t0 = time_mod.perf_counter()
        resp = await self._client.patch(
            f"/reservations/{reservation_id}", json=payload
        )
        latency_ms = (time_mod.perf_counter() - t0) * 1000
        if resp.status_code >= 400:
            raise self._parse_error(resp)
        data = resp.json()
        data["_latency_ms"] = round(latency_ms, 1)
        self._report("update_reservation", latency_ms, id=reservation_id[:8])
        return data

    async def cancel_reservation(self, reservation_id: str) -> dict:
        t0 = time_mod.perf_counter()
        resp = await self._client.post(f"/reservations/{reservation_id}/cancel")
        latency_ms = (time_mod.perf_counter() - t0) * 1000
        if resp.status_code >= 400:
            raise self._parse_error(resp)
        data = resp.json()
        data["_latency_ms"] = round(latency_ms, 1)
        self._report("cancel_reservation", latency_ms, id=reservation_id[:8])
        return data

    async def handoff(
        self,
        *,
        reason: str,
        conversation_summary: str,
        customer_phone: Optional[str] = None,
    ) -> dict:
        payload = {
            "reason": reason,
            "conversation_summary": conversation_summary,
            "customer_phone": customer_phone,
        }
        t0 = time_mod.perf_counter()
        resp = await self._client.post("/handoff", json=payload)
        latency_ms = (time_mod.perf_counter() - t0) * 1000
        if resp.status_code >= 400:
            raise self._parse_error(resp)
        data = resp.json()
        data["_latency_ms"] = round(latency_ms, 1)
        self._report("handoff", latency_ms, reason=reason[:40])
        return data

    async def reset(self) -> dict:
        resp = await self._client.post("/admin/reset")
        if resp.status_code >= 400:
            raise self._parse_error(resp)
        return resp.json()
