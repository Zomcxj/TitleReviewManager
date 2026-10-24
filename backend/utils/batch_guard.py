"""
Batch operation guards

Risk: batch endpoints (batch transfer/submit/reminder/assign/release) process items
in a loop and **send notifications**. Without limits, a single request carrying tens
of thousands of IDs would:
1. Generate tens of thousands of notifications (notification table bloat, users bombarded)
2. Hold database connections and transactions for a long time (other requests queue up)
3. Be abused for resource exhaustion

Hence two layers of limits on batch operations:
- Max items per request (default 200)
- Max calls per time window (default 20 calls per 10 minutes per user)
"""
import logging
from datetime import timedelta

from utils.timeutil import utcnow

logger = logging.getLogger(__name__)

# Max items per batch operation
MAX_BATCH_SIZE = 200
# Rate limiting: max calls per user per window
BATCH_RATE_WINDOW_MINUTES = 10
BATCH_RATE_MAX_CALLS = 20


def validate_batch_ids(ids: list[int] | None, field_name: str = "IDs") -> list[int]:
    """Validate the ID list for a batch operation: non-empty, deduplicated, within the cap.

    Returns the deduplicated list; raises HTTPException when invalid.
    """
    from fastapi import HTTPException

    if not ids:
        raise HTTPException(status_code=400, detail="请至少选择一条记录")

    # Deduplicate while preserving order (duplicate IDs cause duplicate processing and notifications)
    seen = set()
    unique = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            unique.append(i)

    if len(unique) > MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"单次批量操作最多 {MAX_BATCH_SIZE} 条，当前 {len(unique)} 条，请分批处理",
        )
    return unique


def check_batch_rate_limit(db, user: dict, action: str) -> None:
    """Rate limit for batch operations (reuses the login_attempts table, distinguished by scope).

    Prevents scripted high-frequency batch calls from spamming notifications or
    overwhelming the database.
    """
    from fastapi import HTTPException

    from models import LoginAttempt

    uid = (user or {}).get("user_id") or (user or {}).get("id")
    if not uid:
        return

    key = f"batch:{action}:{uid}"
    since = utcnow() - timedelta(minutes=BATCH_RATE_WINDOW_MINUTES)
    count = db.query(LoginAttempt).filter(
        LoginAttempt.scope == "ip",
        LoginAttempt.key == key,
        LoginAttempt.attempted_at >= since,
    ).count()

    if count >= BATCH_RATE_MAX_CALLS:
        raise HTTPException(
            status_code=429,
            detail=f"批量操作过于频繁（{BATCH_RATE_WINDOW_MINUTES} 分钟内最多 {BATCH_RATE_MAX_CALLS} 次），请稍后再试",
        )

    db.add(LoginAttempt(scope="ip", key=key, attempted_at=utcnow()))
    db.flush()
