"""
批量操作防护

风险：批量接口（批量转让/提交/催办/分配/释放）在循环里逐个处理并**发送通知**。
不设上限时，一次请求传上万个 ID 会：
1. 产生上万条通知（通知表膨胀、相关用户被轰炸）
2. 长时间占用数据库连接与事务（其他请求排队）
3. 被恶意利用做资源消耗

因此对批量操作做两层限制：
- 单次条数上限（默认 200）
- 单位时间内调用次数上限（默认每用户 10 分钟 20 次）
"""
import logging
from datetime import datetime, timedelta
from typing import List, Optional

logger = logging.getLogger(__name__)

# 单次批量操作的最大条数
MAX_BATCH_SIZE = 200
# 频率限制：每用户每窗口最多调用次数
BATCH_RATE_WINDOW_MINUTES = 10
BATCH_RATE_MAX_CALLS = 20


def validate_batch_ids(ids: Optional[List[int]], field_name: str = "IDs") -> List[int]:
    """校验批量操作的 ID 列表：非空、去重、不超上限。

    返回去重后的列表；不合法时抛 HTTPException。
    """
    from fastapi import HTTPException

    if not ids:
        raise HTTPException(status_code=400, detail="请至少选择一条记录")

    # 去重但保持顺序（重复 ID 会造成重复处理与重复通知）
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
    """批量操作频率限制（复用 login_attempts 表，scope 区分）。

    防止脚本化高频调用批量接口刷通知或压数据库。
    """
    from fastapi import HTTPException
    from models import LoginAttempt

    uid = (user or {}).get("user_id") or (user or {}).get("id")
    if not uid:
        return

    key = f"batch:{action}:{uid}"
    since = datetime.utcnow() - timedelta(minutes=BATCH_RATE_WINDOW_MINUTES)
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

    db.add(LoginAttempt(scope="ip", key=key, attempted_at=datetime.utcnow()))
    db.flush()
