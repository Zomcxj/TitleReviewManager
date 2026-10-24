"""
Tamper-proof audit log (hash chain)

Problem: audit logs live in the business database, so anyone with direct DB access
(ops, anyone holding the DB password, anyone editing the SQLite file directly)
can modify or delete logs without leaving a trace — exactly the scenario audit
logs most need to defend against.

Solution: hash chain (blockchain-style one-way chain)
    Each entry's entry_hash = SHA256(normalized field content + previous entry_hash)
    Therefore:
    - Modifying any entry -> its hash changes -> all subsequent entries fail verification
    - Deleting an entry in the middle -> successor's prev_hash mismatches -> verification fails
    - Deleting entries at the **tail**: undetectable (an inherent limitation of hash
      chains; requires external anchoring, e.g. periodically writing the chain tail
      hash to an external log/email — not done here, but documented)

Limitations (do not assume this is foolproof):
    - An attacker who can rewrite the data and recompute the entire chain can still
      forge entries (hence anchoring the chain tail matters)
    - The value of this mechanism is turning "silent tampering" into "must recompute
      the entire chain", greatly raising the cost and exposure probability of tampering
"""
import hashlib
import json
import logging
from datetime import datetime
from typing import Any

from utils.timeutil import utcnow

logger = logging.getLogger(__name__)

# Genesis hash of the chain (prev_hash of the first log entry)
GENESIS_HASH = "0" * 64


def _normalize(value: Any) -> str:
    """Normalize a field value into a stable string (same content must hash identically)."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        # Normalize to second-level ISO format; microsecond/timezone differences would make hashes unstable
        return value.replace(microsecond=0).isoformat()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return str(value)


def compute_entry_hash(
    prev_hash: str,
    user_id: int | None,
    username: str | None,
    action: str,
    resource_type: str,
    resource_id: int | None,
    old_value: Any,
    new_value: Any,
    ip_address: str | None,
    created_at: datetime,
) -> str:
    """Compute the chained hash of a single log entry.

    Note: user_agent and the microsecond part of created_at are deliberately **excluded** —
    user_agent varies across clients, and microseconds are inconsistent across database
    precision settings; either would misjudge legitimate data as tampering.
    """
    payload = "|".join([
        prev_hash or GENESIS_HASH,
        _normalize(user_id),
        _normalize(username),
        _normalize(action),
        _normalize(resource_type),
        _normalize(resource_id),
        _normalize(old_value),
        _normalize(new_value),
        _normalize(ip_address),
        _normalize(created_at),
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def chain_log_entry(entry) -> None:
    """Compute and fill the hash chain fields for an OperationLog about to be written.

    Call timing: before or after db.add(entry), but before commit.
    Queries the current chain tail hash as this entry's prev_hash.
    """
    from models import OperationLog

    session = None
    try:
        from sqlalchemy.orm import object_session
        session = object_session(entry)
    except Exception:
        session = None

    prev_hash = GENESIS_HASH
    if session is not None:
        try:
            last = (
                session.query(OperationLog)
                .filter(OperationLog.entry_hash.isnot(None))
                .order_by(OperationLog.id.desc())
                .first()
            )
            if last and last.entry_hash:
                prev_hash = last.entry_hash
        except Exception as e:
            logger.warning(f"读取链尾哈希失败，本条将使用创世哈希: {e}")

    entry.prev_hash = prev_hash
    entry.entry_hash = compute_entry_hash(
        prev_hash=prev_hash,
        user_id=entry.user_id,
        username=entry.username,
        action=entry.action,
        resource_type=entry.resource_type,
        resource_id=entry.resource_id,
        old_value=entry.old_value,
        new_value=entry.new_value,
        ip_address=entry.ip_address,
        created_at=entry.created_at or utcnow(),
    )


def verify_chain(db, limit: int | None = None) -> dict[str, Any]:
    """Verify the integrity of the audit log chain.

    Returns:
        {
          "valid": bool,           # whether all checks passed
          "checked": int,          # number of entries checked
          "broken_at": [id...],    # ids of entries failing verification (max 20 listed)
          "reason": str|None,      # first failure reason
          "unchained": int,        # number of legacy entries without hashes (data predating this feature)
        }
    """
    from models import OperationLog

    query = db.query(OperationLog).order_by(OperationLog.id.asc())
    if limit:
        query = query.limit(limit)
    entries: list[OperationLog] = query.all()

    result = {"valid": True, "checked": 0, "broken_at": [], "reason": None, "unchained": 0}
    expected_prev = GENESIS_HASH

    for entry in entries:
        if not entry.entry_hash:
            # Legacy entries predating this feature: skip verification but count them
            result["unchained"] += 1
            continue

        # 1. prev_hash must equal the previous entry's entry_hash
        if (entry.prev_hash or GENESIS_HASH) != expected_prev:
            result["valid"] = False
            if len(result["broken_at"]) < 20:
                result["broken_at"].append(entry.id)
            if not result["reason"]:
                result["reason"] = (
                    f"日志 #{entry.id} 的前序哈希不匹配（可能存在删除或插入）"
                )

        # 2. Content hash must be self-consistent
        recomputed = compute_entry_hash(
            prev_hash=entry.prev_hash or GENESIS_HASH,
            user_id=entry.user_id,
            username=entry.username,
            action=entry.action,
            resource_type=entry.resource_type,
            resource_id=entry.resource_id,
            old_value=entry.old_value,
            new_value=entry.new_value,
            ip_address=entry.ip_address,
            created_at=entry.created_at,
        )
        if recomputed != entry.entry_hash:
            result["valid"] = False
            if len(result["broken_at"]) < 20:
                result["broken_at"].append(entry.id)
            if not result["reason"]:
                result["reason"] = f"日志 #{entry.id} 内容被修改（哈希不匹配）"

        expected_prev = entry.entry_hash
        result["checked"] += 1

    return result


def backfill_chain(db, batch_size: int = 500) -> int:
    """Backfill the hash chain for historical log entries (one-time operation after rollout).

    Processes entries without entry_hash in ascending id order; once done the chain
    is continuous. Returns the number of backfilled entries.
    """
    from models import OperationLog

    pending = (
        db.query(OperationLog)
        .filter(OperationLog.entry_hash.is_(None))
        .order_by(OperationLog.id.asc())
        .limit(batch_size)
        .all()
    )
    if not pending:
        return 0

    # Locate the existing chain tail
    last_chained = (
        db.query(OperationLog)
        .filter(OperationLog.entry_hash.isnot(None))
        .order_by(OperationLog.id.desc())
        .first()
    )
    prev_hash = last_chained.entry_hash if last_chained else GENESIS_HASH

    for entry in pending:
        entry.prev_hash = prev_hash
        entry.entry_hash = compute_entry_hash(
            prev_hash=prev_hash,
            user_id=entry.user_id,
            username=entry.username,
            action=entry.action,
            resource_type=entry.resource_type,
            resource_id=entry.resource_id,
            old_value=entry.old_value,
            new_value=entry.new_value,
            ip_address=entry.ip_address,
            created_at=entry.created_at,
        )
        prev_hash = entry.entry_hash

    db.commit()
    return len(pending)


def register_chain_hook() -> None:
    """Register a SQLAlchemy event: compute the hash chain automatically before any
    OperationLog is persisted.

    Why an event instead of calling chain_log_entry at every site:
    the project has 20+ audit log write sites; patching each one is error-prone and
    would litter business code with the implicit convention of "remember to hash".
    Hooking the ORM layer means new logging code never needs to care about it.
    """
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    from models import OperationLog

    @event.listens_for(Session, "before_flush")
    def _chain_new_logs(session, flush_context, instances):
        for obj in session.new:
            if isinstance(obj, OperationLog) and not obj.entry_hash:
                try:
                    chain_log_entry(obj)
                except Exception as e:
                    # A hash chain failure must not block business writes (the audit entry is still persisted)
                    logger.warning(f"审计日志哈希链计算失败: {e}")
