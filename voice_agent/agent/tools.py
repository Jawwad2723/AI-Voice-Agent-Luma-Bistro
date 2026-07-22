"""LiveKit function tools backed by the reservation API + session gates."""

from __future__ import annotations

import logging
from typing import Annotated, Optional

from livekit.agents import RunContext, function_tool
from pydantic import Field

from .reservation_client import (
    ReservationAPIError,
    ReservationClient,
    make_idempotency_key,
)
from .session_state import SessionState
from .validation import ValidationError, normalize_phone, validate_create_fields

logger = logging.getLogger("luma.tools")


def build_tools(client: ReservationClient):
    """Return tool callables closed over the shared ReservationClient."""

    @function_tool()
    async def get_restaurant_info(context: RunContext) -> dict:
        """Get Luma Bistro hours, timezone, and party-size limits."""
        state: SessionState = context.userdata
        if state.restaurant_info:
            return state.restaurant_info
        info = await client.get_restaurant()
        state.restaurant_info = info
        return {
            "name": info.get("name"),
            "timezone": info.get("timezone"),
            "hours": info.get("hours"),
            "slot_minutes": info.get("slot_minutes"),
            "max_standard_party_size": info.get("max_standard_party_size"),
        }

    @function_tool()
    async def check_availability(
        context: RunContext,
        date: Annotated[str, Field(description="Reservation date YYYY-MM-DD")],
        time: Annotated[str, Field(description="Slot time HH:MM 24h, e.g. 18:00")],
        party_size: Annotated[int, Field(description="Party size 1-8")],
    ) -> dict:
        """Check if a date/time is available for the party size. Retries once on temporary failure."""
        from .validation import (
            normalize_date,
            normalize_time,
            validate_open_hours,
            validate_party_size,
        )

        state: SessionState = context.userdata
        try:
            date_n = normalize_date(date)
            time_n = normalize_time(time)
            party = validate_party_size(party_size)
            validate_open_hours(date_n, time_n)
        except ValidationError as e:
            if e.code == "PARTY_TOO_LARGE":
                return {
                    "ok": False,
                    "code": e.code,
                    "message": str(e),
                    "action": "handoff_required",
                }
            return {"ok": False, "code": e.code, "message": str(e)}

        state.date = date_n
        state.time = time_n
        state.party_size = party

        try:
            result = await client.check_availability(
                date=date_n,
                time=time_n,
                party_size=party,
            )
        except ReservationAPIError as e:
            return {
                "ok": False,
                "code": e.code,
                "status_code": e.status_code,
                "message": "Availability service failed after retry. Offer handoff.",
                "detail": e.detail,
            }

        state.alternatives = result.get("alternatives") or []
        return {
            "ok": True,
            "available": result.get("available"),
            "date": result.get("date"),
            "time": result.get("time"),
            "party_size": result.get("party_size"),
            "remaining_capacity": result.get("remaining_capacity"),
            "alternatives": state.alternatives,
            "attempts": result.get("_attempts"),
        }

    @function_tool()
    async def confirm_pending_write(
        context: RunContext,
        action: Annotated[
            str, Field(description="One of: create, modify, cancel")
        ],
    ) -> dict:
        """Call only after the caller explicitly confirms the final details aloud."""
        state: SessionState = context.userdata
        action = action.strip().lower()
        if action == "create":
            state.mark_create_confirmed()
            return {"ok": True, "confirmed": "create"}
        if action == "modify":
            state.modify_confirmed = True
            state.pending_action = "modify"
            return {"ok": True, "confirmed": "modify"}
        if action == "cancel":
            state.cancel_confirmed = True
            state.pending_action = "cancel"
            return {"ok": True, "confirmed": "cancel"}
        return {"ok": False, "message": "action must be create, modify, or cancel"}

    @function_tool()
    async def create_reservation(
        context: RunContext,
        name: Annotated[str, Field(description="Guest full name")],
        phone: Annotated[str, Field(description="Guest phone number")],
        date: Annotated[str, Field(description="YYYY-MM-DD")],
        time: Annotated[str, Field(description="HH:MM 24h")],
        party_size: Annotated[int, Field(description="1-8")],
        notes: Annotated[
            Optional[str], Field(description="Optional special requests")
        ] = None,
    ) -> dict:
        """Create a reservation AFTER confirm_pending_write(action='create'). Uses idempotency."""
        state: SessionState = context.userdata
        if not state.create_confirmed:
            return {
                "ok": False,
                "code": "CONFIRMATION_REQUIRED",
                "message": "Ask the caller to confirm details, then call confirm_pending_write('create') first.",
            }
        try:
            fields = validate_create_fields(
                name=name,
                phone=phone,
                date=date,
                time=time,
                party_size=party_size,
                notes=notes,
            )
        except ValidationError as e:
            return {"ok": False, "code": e.code, "message": str(e)}

        key = make_idempotency_key(
            session_id=state.session_id,
            name=fields["name"],
            phone=fields["phone"],
            date=fields["date"],
            time=fields["time"],
            party_size=fields["party_size"],
        )
        state.last_idempotency_key = key
        state.customer_name = fields["name"]
        state.phone = fields["phone"]
        state.date = fields["date"]
        state.time = fields["time"]
        state.party_size = fields["party_size"]
        state.notes = fields["notes"]

        try:
            result = await client.create_reservation(
                **fields, idempotency_key=key
            )
        except ReservationAPIError as e:
            state.create_confirmed = False
            return {
                "ok": False,
                "code": e.code,
                "status_code": e.status_code,
                "detail": e.detail,
            }

        state.reservation_id = result.get("reservation_id")
        state.confirmation_code = result.get("confirmation_code")
        state.already_created = True
        state.clear_write_flags()
        state.note(f"Created {state.confirmation_code}")
        return {
            "ok": True,
            "reservation_id": state.reservation_id,
            "confirmation_code": state.confirmation_code,
            "name": result.get("name"),
            "phone": result.get("phone"),
            "date": result.get("date"),
            "time": result.get("time"),
            "party_size": result.get("party_size"),
            "status": result.get("status"),
            "idempotency_key": key,
        }

    @function_tool()
    async def search_reservations(
        context: RunContext,
        phone: Annotated[
            Optional[str], Field(description="Guest phone number")
        ] = None,
        confirmation_code: Annotated[
            Optional[str], Field(description="e.g. LUMA-4821")
        ] = None,
    ) -> dict:
        """Find reservations by phone or confirmation code."""
        state: SessionState = context.userdata
        if not phone and not confirmation_code:
            return {
                "ok": False,
                "code": "SEARCH_CRITERIA_REQUIRED",
                "message": "Provide phone or confirmation_code.",
            }
        phone_n = None
        if phone:
            try:
                phone_n = normalize_phone(phone)
            except ValidationError as e:
                return {"ok": False, "code": e.code, "message": str(e)}
        try:
            result = await client.search_reservations(
                phone=phone_n, confirmation_code=confirmation_code
            )
        except ReservationAPIError as e:
            return {
                "ok": False,
                "code": e.code,
                "status_code": e.status_code,
                "detail": e.detail,
            }
        results = result.get("results") or []
        if len(results) == 1:
            r = results[0]
            state.reservation_id = r.get("reservation_id")
            state.confirmation_code = r.get("confirmation_code")
            state.customer_name = r.get("name")
            state.phone = r.get("phone")
            state.date = r.get("date")
            state.time = r.get("time")
            state.party_size = r.get("party_size")
        return {"ok": True, "results": results}

    @function_tool()
    async def update_reservation(
        context: RunContext,
        reservation_id: Annotated[str, Field(description="Reservation id")],
        date: Annotated[Optional[str], Field(description="YYYY-MM-DD")] = None,
        time: Annotated[Optional[str], Field(description="HH:MM")] = None,
        party_size: Annotated[Optional[int], Field(description="1-8")] = None,
        notes: Annotated[Optional[str], Field(description="Notes")] = None,
    ) -> dict:
        """Modify a reservation AFTER confirm_pending_write(action='modify')."""
        state: SessionState = context.userdata
        if not state.modify_confirmed:
            return {
                "ok": False,
                "code": "CONFIRMATION_REQUIRED",
                "message": "Confirm changes with the caller, then confirm_pending_write('modify').",
            }
        try:
            result = await client.update_reservation(
                reservation_id,
                date=date,
                time=time,
                party_size=party_size,
                notes=notes,
            )
        except ReservationAPIError as e:
            state.modify_confirmed = False
            return {
                "ok": False,
                "code": e.code,
                "status_code": e.status_code,
                "detail": e.detail,
            }
        state.reservation_id = result.get("reservation_id")
        state.confirmation_code = result.get("confirmation_code")
        state.date = result.get("date")
        state.time = result.get("time")
        state.party_size = result.get("party_size")
        state.clear_write_flags()
        state.note(f"Updated {state.confirmation_code}")
        return {"ok": True, "reservation": result}

    @function_tool()
    async def cancel_reservation(
        context: RunContext,
        reservation_id: Annotated[str, Field(description="Reservation id")],
    ) -> dict:
        """Cancel a reservation AFTER confirm_pending_write(action='cancel')."""
        state: SessionState = context.userdata
        if not state.cancel_confirmed:
            return {
                "ok": False,
                "code": "CONFIRMATION_REQUIRED",
                "message": "Confirm cancellation with the caller, then confirm_pending_write('cancel').",
            }
        try:
            result = await client.cancel_reservation(reservation_id)
        except ReservationAPIError as e:
            state.cancel_confirmed = False
            return {
                "ok": False,
                "code": e.code,
                "status_code": e.status_code,
                "detail": e.detail,
            }
        state.clear_write_flags()
        state.note(f"Cancelled {result.get('confirmation_code')}")
        return {"ok": True, "reservation": result}

    @function_tool()
    async def handoff_to_human(
        context: RunContext,
        reason: Annotated[str, Field(description="Why handoff is needed")],
        customer_phone: Annotated[
            Optional[str], Field(description="Caller phone if known")
        ] = None,
    ) -> dict:
        """Queue a human handoff with conversation summary preserved."""
        state: SessionState = context.userdata
        phone = customer_phone or state.phone
        if phone:
            try:
                phone = normalize_phone(phone)
            except ValidationError:
                pass
        summary = state.summary()
        try:
            result = await client.handoff(
                reason=reason,
                conversation_summary=summary,
                customer_phone=phone,
            )
        except ReservationAPIError as e:
            return {
                "ok": False,
                "code": e.code,
                "status_code": e.status_code,
                "detail": e.detail,
            }
        state.handoff_queued = True
        return {
            "ok": True,
            "handoff_id": result.get("handoff_id"),
            "status": result.get("status"),
            "conversation_summary": summary,
        }

    return [
        get_restaurant_info,
        check_availability,
        confirm_pending_write,
        create_reservation,
        search_reservations,
        update_reservation,
        cancel_reservation,
        handoff_to_human,
    ]
