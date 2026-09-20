"""
审计日志防篡改（哈希链）

问题：审计日志存在业务库里，任何能直连数据库的人（运维、拿到 DB 密码者、
直接改 SQLite 文件者）都能改删日志而不留痕迹 —— 这恰好是审计日志最需要防的场景。

方案：哈希链（blockchain 式单向链）
    每条日志的 entry_hash = SHA256(规范化字段内容 + 上一条的 entry_hash)
    这样：
    - 改动任意一条日志 → 该条哈希变化 → 后续所有条目校验失败
    - 删除中间某条 → 后继条目的 prev_hash 对不上 → 校验失败
    - 删除**末尾**若干条：无法检测（这是哈希链的固有限制，需要外部锚定，
      如定期把链尾哈希写到外部日志/邮件，此处不做，但在文档中说明）

局限说明（避免误以为万无一失）：
    - 攻击者若能同时改数据并重算整条链，仍可伪造（因此链尾锚定很重要）
    - 本机制的价值在于「静默篡改」变为「必须重算全链」，大幅提高篡改成本与暴露概率
"""
import hashlib
import json
import logging
from datetime import datetime
from typing import Any

from utils.timeutil import utcnow

logger = logging.getLogger(__name__)

# 链的创世哈希（第一条日志的 prev_hash）
GENESIS_HASH = "0" * 64


def _normalize(value: Any) -> str:
    """把字段值规范化为稳定字符串（保证同一内容哈希一致）"""
    if value is None:
        return ""
    if isinstance(value, datetime):
        # 统一到秒级 ISO 格式，避免微秒/时区差异导致哈希不稳定
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
    """计算单条日志的链式哈希。

    注意：故意**不包含** user_agent 与 created_at 的微秒部分 ——
    user_agent 可能因客户端差异不稳定，微秒在不同数据库精度下不一致，
    都会导致正常数据被误判为篡改。
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
    """为一条待写入的 OperationLog 计算并填充哈希链字段。

    调用时机：在 db.add(entry) 之前或之后、commit 之前。
    会查询当前链尾哈希作为本条 prev_hash。
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
    """校验审计日志链完整性。

    返回：
        {
          "valid": bool,           # 是否全部通过
          "checked": int,          # 校验条数
          "broken_at": [id...],    # 校验失败的日志 id（最多列 20 个）
          "reason": str|None,      # 首个失败原因
          "unchained": int,        # 未带哈希的历史条目数（功能上线前的旧数据）
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
            # 功能上线前的历史条目：跳过校验，但计数提示
            result["unchained"] += 1
            continue

        # 1. prev_hash 必须等于上一条的 entry_hash
        if (entry.prev_hash or GENESIS_HASH) != expected_prev:
            result["valid"] = False
            if len(result["broken_at"]) < 20:
                result["broken_at"].append(entry.id)
            if not result["reason"]:
                result["reason"] = (
                    f"日志 #{entry.id} 的前序哈希不匹配（可能存在删除或插入）"
                )

        # 2. 内容哈希必须自洽
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
    """为历史日志补算哈希链（功能上线后的一次性操作）。

    按 id 升序处理未带 entry_hash 的条目，补齐后链即连续。
    返回补齐条数。
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

    # 找到已有链尾
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
    """注册 SQLAlchemy 事件：任何 OperationLog 落库前自动计算哈希链。

    用事件而不是逐处调用 chain_log_entry，原因：
    全项目有 20+ 处写审计日志，逐个改既容易漏、也会让业务代码充满
    "记得算哈希" 的隐式约定；挂在 ORM 层则新增日志代码无需关心这件事。
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
                    # 哈希链失败不能阻断业务写入（审计记录本身仍会落库）
                    logger.warning(f"审计日志哈希链计算失败: {e}")
