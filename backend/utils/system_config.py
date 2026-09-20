"""
系统参数配置服务

管理员可在界面上调整运行参数（公海限额、SLA 时长、锁定阈值等）。
取值优先级：数据库 system_configs 表 > enums.DEFAULT_SYSTEM_CONFIG 默认值。
带短 TTL 缓存，避免每个请求都查库。
"""
import time
from typing import Any

from sqlalchemy.orm import Session

from enums import DEFAULT_SYSTEM_CONFIG, SYSTEM_CONFIG_LABELS

_CACHE_TTL_SECONDS = 5
_cache: dict[str, Any] = {}
_cache_at: float = 0.0


def _coerce(raw: str, default: Any) -> Any:
    """按默认值的类型转换存储的字符串"""
    try:
        if isinstance(default, bool):
            return str(raw).strip().lower() in ("1", "true", "yes", "on")
        if isinstance(default, int):
            return int(float(raw))
        if isinstance(default, float):
            return float(raw)
    except (TypeError, ValueError):
        return default
    return raw


def _load(db: Session) -> dict[str, Any]:
    global _cache, _cache_at
    now = time.time()
    if _cache and now - _cache_at < _CACHE_TTL_SECONDS:
        return _cache

    values = dict(DEFAULT_SYSTEM_CONFIG)
    try:
        from models import SystemConfig
        for row in db.query(SystemConfig).all():
            if row.key in values:
                values[row.key] = _coerce(row.value, values[row.key])
    except Exception:
        # 表尚未创建或查询异常时回落到默认值，不影响主流程
        pass

    _cache, _cache_at = values, now
    return values


def get_config(db: Session, key: str) -> Any:
    """读取单个配置项"""
    return _load(db).get(key, DEFAULT_SYSTEM_CONFIG.get(key))


def get_all_config(db: Session) -> dict[str, Any]:
    """读取全部配置项（含中文标签，供管理界面展示）"""
    values = dict(_load(db))
    return {
        k: {"value": v, "label": SYSTEM_CONFIG_LABELS.get(k, k), "default": DEFAULT_SYSTEM_CONFIG.get(k)}
        for k, v in values.items()
    }


def set_config(db: Session, key: str, value: Any, username: str = "") -> None:
    """写入配置项（不存在则创建）"""
    from models import SystemConfig
    global _cache_at
    row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    text_value = str(value)
    if row:
        row.value = text_value
        row.updated_by = username
    else:
        db.add(SystemConfig(
            key=key,
            value=text_value,
            description=SYSTEM_CONFIG_LABELS.get(key, key),
            updated_by=username,
        ))
    db.commit()
    _cache_at = 0.0  # 立即失效缓存，下次读取重新加载


def invalidate_cache() -> None:
    """清除缓存（配置变更或测试场景调用）"""
    global _cache_at
    _cache_at = 0.0
