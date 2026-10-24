"""
Unified time sourcing (UTC, naive)

Why this module exists
----------------------
`utcnow()` is deprecated as of Python 3.12; the official recommendation is
`datetime.now(timezone.utc)`. But **replacing it directly introduces new defects**:

- `datetime.now(timezone.utc)` returns an **aware** object;
- `DateTime` columns read from SQLite/PostgreSQL come back as **naive** objects;
- Python forbids comparing aware with naive directly and raises
  `TypeError: can't compare offset-naive and offset-aware datetimes`.

Lots of code in this project compares "time in the database vs current time"
(SLA timeouts, reminder dedup, public pool recovery, session expiry); mixing the
two raises at runtime — inside scheduled jobs, which is hard to notice without tests.

Therefore use this module's `utcnow()` uniformly: it returns **naive UTC**, behaves
exactly like the old `utcnow()` (millisecond-equivalent, locked by tests) and just
no longer triggers the deprecation warning.

Conventions
-----------
- Storing to / comparing with the database: always `utcnow()` (naive UTC).
- Need an ISO string for the frontend/logs: use `utcnow_iso()`, or explicitly
  `datetime.now(timezone.utc).isoformat()` (aware, with the +00:00 suffix).
- Need a current timestamp for duration measurements: use `time.time()`; it carries
  no time semantics.

If a full migration to aware datetime ever happens, the correct path is to change
the model column types (`DateTime(timezone=True)`) **and** migrate historical data
**and** replace all comparison logic at the same time — never half of it. That is a
separate refactor, out of scope here.
"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Current UTC time, naive (same behavior as the old datetime.utcnow()).

    Staying naive allows direct comparison with the naive values read from the database.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utcnow_aware() -> datetime:
    """Current UTC time, aware (with tzinfo).

    Use only when timezone information is explicitly needed (e.g. generating ISO
    strings with +00:00). Before comparing with naive times from the database you
    must first `.replace(tzinfo=None)`.
    """
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    """ISO string of the current UTC time (with +00:00 suffix, for frontend display/logs)"""
    return datetime.now(timezone.utc).isoformat()


def to_naive(dt: datetime | None) -> datetime | None:
    """Convert a possibly timezone-aware datetime to naive UTC for comparison with naive DB values.

    Aware values are converted to UTC before the tzinfo is dropped (rather than
    discarding tzinfo directly, which would treat a +08:00 time as UTC and be off by 8 hours).
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)
