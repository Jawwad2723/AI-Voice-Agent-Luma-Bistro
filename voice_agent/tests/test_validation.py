"""Unit tests for validation helpers (no API required)."""

import pytest

from agent.validation import (
    ValidationError,
    normalize_date,
    normalize_phone,
    normalize_time,
    validate_party_size,
)


def test_normalize_phone_us():
    assert normalize_phone("310-555-0199") == "+13105550199"
    assert normalize_phone("+1 310 555 0147") == "+13105550147"


def test_normalize_time_spoken():
    assert normalize_time("6 PM") == "18:00"
    assert normalize_time("6:30pm") == "18:30"
    assert normalize_time("19:30") == "19:30"


def test_normalize_date_iso():
    assert normalize_date("2026-08-14") == "2026-08-14"


def test_party_too_large():
    with pytest.raises(ValidationError) as ei:
        validate_party_size(12)
    assert ei.value.code == "PARTY_TOO_LARGE"
