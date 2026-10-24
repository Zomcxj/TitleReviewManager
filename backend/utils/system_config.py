"""
System configuration service

Admins can tune runtime parameters in the UI (public pool quota, SLA durations,
lockout thresholds, etc.).
Value priority: the database system_configs table > defaults from enums.DEFAULT_SYSTEM_CONFIG.
Uses a short-TTL cache so not every request hits the database.
"""
import time
from typing import Any

from sqlalchemy.orm import Session

from enums import DEFAULT_SYSTEM_CONFIG, SYSTEM_CONFIG_LABELS

_CACHE_TTL_SECONDS = 5
_cache: dict[str, Any] = {}
_cache_at: float = 0.0


def _coerce(raw: str, default: Any) -> Any:
    """Coerce the stored string according to the default value's type"""
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
        # Fall back to defaults when the table does not exist yet or the query fails; never breaks the main flow
        pass

    _cache, _cache_at = values, now
    return values


def get_config(db: Session, key: str) -> Any:
    """Read a single config value"""
    return _load(db).get(key, DEFAULT_SYSTEM_CONFIG.get(key))


def get_all_config(db: Session) -> dict[str, Any]:
    """Read all config values (with Chinese labels for the admin UI)"""
    values = dict(_load(db))
    return {
        k: {"value": v, "label": SYSTEM_CONFIG_LABELS.get(k, k), "default": DEFAULT_SYSTEM_CONFIG.get(k)}
        for k, v in values.items()
    }


def set_config(db: Session, key: str, value: Any, username: str = "") -> None:
    """Write a config value (created if missing)"""
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
    _cache_at = 0.0  # Invalidate the cache immediately; the next read reloads


def invalidate_cache() -> None:
    """Clear the cache (called on config changes or in tests)"""
    global _cache_at
    _cache_at = 0.0
