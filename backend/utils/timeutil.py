"""
统一时间取值（UTC，naive）

为什么需要这个模块
------------------
`utcnow()` 在 Python 3.12 起被废弃，官方建议改用
`datetime.now(timezone.utc)`。但**直接替换会引入新缺陷**：

- `datetime.now(timezone.utc)` 返回 **aware** 对象；
- 数据库里的 `DateTime` 列在 SQLite/PostgreSQL 下读出来是 **naive** 对象；
- Python 禁止 aware 与 naive 直接比较，会抛
  `TypeError: can't compare offset-naive and offset-aware datetimes`。

本项目大量代码在做「库里的时间 vs 当前时间」比较（SLA 超时、催办去重、
公海回收、会话过期），一旦混用就会在运行时抛异常 —— 而且是在定时任务里，
不跑测试很难发现。

因此统一用本模块的 `utcnow()`：返回 **naive UTC**，行为与旧 `utcnow()` 完全
一致（毫秒级等价，已用测试锁定），只是不再触发废弃警告。

约定
----
- 存库、比库：一律用 `utcnow()`（naive UTC）。
- 需要给前端/日志输出 ISO 字符串：用 `utcnow_iso()`，或显式
  `datetime.now(timezone.utc).isoformat()`（aware，带 +00:00 后缀）。
- 需要当前时间戳做耗时统计：用 `time.time()`，与时间语义无关。

如果将来要全面迁移到 aware datetime，正确路径是**同时**改模型列类型
（`DateTime(timezone=True)`）+ 迁移历史数据 + 全量替换比较逻辑，
不能只改其中一半。那是一次独立的重构，不在本次范围内。
"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    """当前 UTC 时间，naive（与旧 datetime.utcnow() 行为一致）。

    保留 naive 是为了与数据库读出的 naive 值可直接比较。
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utcnow_aware() -> datetime:
    """当前 UTC 时间，aware（带 tzinfo）。

    仅在明确需要时区信息时使用（如生成带 +00:00 的 ISO 字符串）。
    与库中 naive 时间比较前必须先 `.replace(tzinfo=None)`。
    """
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    """当前 UTC 时间的 ISO 字符串（带 +00:00 后缀，供前端展示/日志）"""
    return datetime.now(timezone.utc).isoformat()


def to_naive(dt: datetime | None) -> datetime | None:
    """把可能带时区的时间转成 naive UTC，便于与库中 naive 值比较。

    aware 值会先换算到 UTC 再去除时区（而不是直接丢弃 tzinfo，
    后者会让 +08:00 的时间被当成 UTC 而差 8 小时）。
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)
