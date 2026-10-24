"""Unified time utility tests.

These tests pin down one key constraint: `utils.timeutil.utcnow()` must behave
exactly like the old `datetime.utcnow()` (naive UTC).

Background: `datetime.utcnow()` is deprecated on 3.12, but switching directly
to `datetime.now(timezone.utc)` returns an aware object, which raises
TypeError when compared with naive values read from the database. Lots of code
in this project does such comparisons (SLA, reminders, public pool recovery),
so the replacement must keep naive semantics.
"""
from datetime import datetime, timedelta, timezone

import pytest

from utils.timeutil import to_naive, utcnow, utcnow_aware, utcnow_iso


class TestUtcnow:
    def test_returns_naive(self):
        """Must return naive, otherwise comparisons with database values raise TypeError"""
        assert utcnow().tzinfo is None

    def test_matches_legacy_utcnow(self):
        """Behaves like the old datetime.utcnow() (the core guarantee that the swap is correct)"""
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            legacy = datetime.utcnow()
        current = utcnow()
        # Normal elapsed time between the two calls should be far below 1 second
        assert abs((current - legacy).total_seconds()) < 1.0

    def test_comparable_with_naive_values(self):
        """Directly comparable with naive times read from the database (no exception)"""
        stored = datetime(2026, 1, 1, 12, 0, 0)  # naive, simulating a database value
        now = utcnow()
        assert isinstance(now > stored, bool)
        assert isinstance(now - stored, timedelta)

    def test_is_utc_not_local(self):
        """The value must be UTC, not local time"""
        delta = abs((utcnow() - utcnow_aware().replace(tzinfo=None)).total_seconds())
        assert delta < 1.0

    def test_monotonic_ordering(self):
        first = utcnow()
        second = utcnow()
        assert second >= first


class TestUtcnowAware:
    def test_returns_aware_utc(self):
        value = utcnow_aware()
        assert value.tzinfo is not None
        assert value.utcoffset() == timedelta(0)

    def test_naive_and_aware_are_not_directly_comparable(self):
        """Records this pitfall: mixing them raises TypeError — exactly why a naive swap is impossible"""
        with pytest.raises(TypeError):
            # The expression is meant to raise here; this is not an accidental comparison
            utcnow() < utcnow_aware()  # noqa: B015


class TestUtcnowIso:
    def test_has_utc_offset(self):
        value = utcnow_iso()
        assert "+00:00" in value

    def test_parseable(self):
        parsed = datetime.fromisoformat(utcnow_iso())
        assert parsed.tzinfo is not None


class TestToNaive:
    def test_none_passthrough(self):
        assert to_naive(None) is None

    def test_naive_unchanged(self):
        value = datetime(2026, 1, 1, 12, 0, 0)
        assert to_naive(value) == value

    def test_aware_utc_stripped(self):
        value = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = to_naive(value)
        assert result.tzinfo is None
        assert result == datetime(2026, 1, 1, 12, 0, 0)

    def test_non_utc_converted_not_truncated(self):
        """A +08:00 time must be converted to UTC (12:00+08:00 → 04:00 UTC),
        not merely stripped of tzinfo (which would yield 12:00, 8 hours off)"""
        value = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone(timedelta(hours=8)))
        result = to_naive(value)
        assert result == datetime(2026, 1, 1, 4, 0, 0)


class TestSlaComparisonSafety:
    """Regression: comparisons like SLA/reminders ("database time vs current time") must not raise"""

    def test_sla_deadline_comparison(self):
        from models import Application
        app = Application()
        # Simulate a naive deadline read from the database
        app.review_sla_deadline = utcnow() - timedelta(hours=5)
        # This kind of comparison is everywhere in the old code
        overdue_hours = (utcnow() - app.review_sla_deadline).total_seconds() / 3600
        assert overdue_hours >= 5

    def test_sqlalchemy_column_default_stays_naive(self):
        """Times from model defaults must also be naive, keeping the whole chain consistent"""
        from models import Customer
        col = Customer.__table__.c.created_at
        value = col.default.arg(None) if callable(col.default.arg) else col.default.arg
        assert value.tzinfo is None
