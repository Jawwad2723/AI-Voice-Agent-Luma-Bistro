"""Per-call session state for the Luma Bistro agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

PendingAction = Literal["none", "create", "modify", "cancel"]


@dataclass
class SessionState:
    session_id: str
    channel: Literal["browser", "phone"] = "browser"
    customer_name: Optional[str] = None
    phone: Optional[str] = None
    party_size: Optional[int] = None
    date: Optional[str] = None
    time: Optional[str] = None
    notes: Optional[str] = None
    pending_action: PendingAction = "none"
    reservation_id: Optional[str] = None
    confirmation_code: Optional[str] = None
    last_idempotency_key: Optional[str] = None
    create_confirmed: bool = False
    modify_confirmed: bool = False
    cancel_confirmed: bool = False
    already_created: bool = False
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    conversation_summary_parts: list[str] = field(default_factory=list)
    handoff_queued: bool = False
    restaurant_info: Optional[dict[str, Any]] = None

    def note(self, text: str) -> None:
        self.conversation_summary_parts.append(text.strip())

    def summary(self) -> str:
        parts = list(self.conversation_summary_parts)
        if self.customer_name:
            parts.append(f"Name: {self.customer_name}")
        if self.phone:
            parts.append(f"Phone: {self.phone}")
        if self.date and self.time:
            parts.append(f"Requested: {self.date} {self.time}")
        if self.party_size:
            parts.append(f"Party size: {self.party_size}")
        if self.confirmation_code:
            parts.append(f"Confirmation: {self.confirmation_code}")
        if self.reservation_id:
            parts.append(f"Reservation ID: {self.reservation_id}")
        return " | ".join(parts) if parts else "No details collected yet."

    def mark_create_confirmed(self) -> None:
        self.create_confirmed = True
        self.pending_action = "create"

    def clear_write_flags(self) -> None:
        self.create_confirmed = False
        self.modify_confirmed = False
        self.cancel_confirmed = False
        self.pending_action = "none"
