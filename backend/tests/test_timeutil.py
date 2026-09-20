"""统一时间工具测试。

这些测试锁定一个关键约束：`utils.timeutil.utcnow()` 必须与旧的
`datetime.utcnow()` 行为完全一致（naive UTC）。

背景：`datetime.utcnow()` 在 3.12 被废弃，但直接换成
`datetime.now(timezone.utc)` 会返回 aware 对象，与数据库读出的 naive 值
比较时抛 TypeError。本项目大量代码在做这类比较（SLA、催办、公海回收），
所以替换必须保持 naive 语义。
"""
from datetime import datetime, timedelta, timezone

import pytest

from utils.timeutil import to_naive, utcnow, utcnow_aware, utcnow_iso


class TestUtcnow:
    def test_returns_naive(self):
        """必须返回 naive，否则与库中值比较会抛 TypeError"""
        assert utcnow().tzinfo is None

    def test_matches_legacy_utcnow(self):
        """与旧 datetime.utcnow() 行为一致（这是替换正确性的核心保证）"""
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            legacy = datetime.utcnow()
        current = utcnow()
        # 两次调用之间的正常耗时，应远小于 1 秒
        assert abs((current - legacy).total_seconds()) < 1.0

    def test_comparable_with_naive_values(self):
        """可与数据库读出的 naive 时间直接比较（不抛异常）"""
        stored = datetime(2026, 1, 1, 12, 0, 0)  # naive，模拟库中值
        now = utcnow()
        assert isinstance(now > stored, bool)
        assert isinstance(now - stored, timedelta)

    def test_is_utc_not_local(self):
        """取值必须是 UTC 而非本地时间"""
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
        """记录这个坑：混用会抛 TypeError —— 这正是不能简单替换的原因"""
        with pytest.raises(TypeError):
            # 这里就是要让表达式抛异常，不是笔误的比较
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
        """+08:00 的时间必须换算成 UTC（12:00+08:00 → 04:00 UTC），
        而不是直接丢掉 tzinfo（那会得到 12:00，差 8 小时）"""
        value = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone(timedelta(hours=8)))
        result = to_naive(value)
        assert result == datetime(2026, 1, 1, 4, 0, 0)


class TestSlaComparisonSafety:
    """回归：SLA/催办这类「库中时间 vs 当前时间」比较必须不抛异常"""

    def test_sla_deadline_comparison(self):
        from models import Application
        app = Application()
        # 模拟从库中读出的 naive 截止时间
        app.review_sla_deadline = utcnow() - timedelta(hours=5)
        # 这类比较在旧代码里到处都是
        overdue_hours = (utcnow() - app.review_sla_deadline).total_seconds() / 3600
        assert overdue_hours >= 5

    def test_sqlalchemy_column_default_stays_naive(self):
        """模型默认值取出的时间也应是 naive，保持全链路一致"""
        from models import Customer
        col = Customer.__table__.c.created_at
        value = col.default.arg(None) if callable(col.default.arg) else col.default.arg
        assert value.tzinfo is None
