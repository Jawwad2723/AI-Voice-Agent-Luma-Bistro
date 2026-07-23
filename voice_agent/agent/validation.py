"""Input normalization and validation for reservation tools."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Los_Angeles")
MAX_PARTY = 8
SLOT_MINUTES = 30
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ValidationError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def normalize_phone(value: str) -> str:
    digits = "".join(c for c in value if c.isdigit())
    if value.strip().startswith("+"):
        normalized = "+" + digits
    elif len(digits) == 10:
        normalized = "+1" + digits
    elif len(digits) == 11 and digits.startswith("1"):
        normalized = "+" + digits
    else:
        normalized = "+" + digits if digits else ""
    if len(re.sub(r"\D", "", normalized)) < 7:
        raise ValidationError("INVALID_PHONE", "Phone number looks too short.")
    return normalized


def normalize_time(value: str) -> str:
    raw = value.strip().lower().replace(".", "")
    raw = raw.replace(" ", "")

    # Already HH:MM
    if TIME_RE.match(raw):
        hh, mm = map(int, raw.split(":"))
        if mm % SLOT_MINUTES != 0:
            raise ValidationError("INVALID_TIME", "Times must be on 30-minute slots.")
        return f"{hh:02d}:{mm:02d}"

    mer = None
    if raw.endswith("am"):
        mer = "am"
        raw = raw[:-2]
    elif raw.endswith("pm"):
        mer = "pm"
        raw = raw[:-2]

    if ":" in raw:
        parts = raw.split(":")
        hh, mm = int(parts[0]), int(parts[1])
    else:
        # e.g. 6 or 630
        if len(raw) <= 2:
            hh, mm = int(raw), 0
        elif len(raw) == 3:
            hh, mm = int(raw[0]), int(raw[1:])
        else:
            hh, mm = int(raw[:-2]), int(raw[-2:])

    if mer == "am":
        if hh == 12:
            hh = 0
    elif mer == "pm":
        if hh != 12:
            hh += 12

    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValidationError("INVALID_TIME", f"Could not parse time: {value}")
    if mm % SLOT_MINUTES != 0:
        raise ValidationError("INVALID_TIME", "Times must be on 30-minute slots.")
    return f"{hh:02d}:{mm:02d}"


def normalize_date(value: str) -> str:
    raw = value.strip()
    if DATE_RE.match(raw):
        datetime.strptime(raw, "%Y-%m-%d")
        return raw
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValidationError("INVALID_DATE", f"Could not parse date: {value}")


def validate_party_size(party_size: int) -> int:
    if party_size < 1:
        raise ValidationError("INVALID_PARTY_SIZE", "Party size must be at least 1.")
    if party_size > MAX_PARTY:
        raise ValidationError(
            "PARTY_TOO_LARGE",
            f"Party size {party_size} exceeds max {MAX_PARTY}; hand off to a human.",
        )
    return party_size


def validate_open_hours(date: str, time: str) -> None:
    dt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
    if dt.weekday() == 0:  # Monday
        raise ValidationError("CLOSED", "Luma Bistro is closed on Mondays.")
    minutes = dt.hour * 60 + dt.minute
    open_m, close_m = 17 * 60, 22 * 60
    if not (open_m <= minutes <= close_m):
        raise ValidationError(
            "OUTSIDE_HOURS",
            "Reservations are available Tuesday–Sunday, 5:00 PM–10:00 PM Pacific.",
        )


def validate_create_fields(
    *,
    name: str,
    phone: str,
    date: str,
    time: str,
    party_size: int,
    notes: Optional[str] = None,
) -> dict:
    name = (name or "").strip()
    if len(name) < 2 or len(name) > 100:
        raise ValidationError("INVALID_NAME", "Please provide a full name.")
    phone_n = normalize_phone(phone)
    date_n = normalize_date(date)
    time_n = normalize_time(time)
    party = validate_party_size(party_size)
    validate_open_hours(date_n, time_n)
    return {
        "name": name,
        "phone": phone_n,
        "date": date_n,
        "time": time_n,
        "party_size": party,
        "notes": notes,
    }
