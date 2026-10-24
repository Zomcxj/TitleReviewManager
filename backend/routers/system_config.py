"""
System parameter configuration (admin only)

- Read all config entries (with Chinese labels and default values)
- Batch update (only accepts known keys with numeric values)
- One-click restore of defaults

Underlying read/write is provided by utils/system_config.py (with a short TTL cache).
"""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from auth import require_role
from database import get_db
from enums import DEFAULT_SYSTEM_CONFIG
from utils.audit_logger import manual_audit_log
from utils.system_config import get_all_config, set_config

router = APIRouter(prefix="/api/system-config", tags=["系统配置"])


def _log(db: Session, user: dict, action: str, old_value, new_value, request: Request):
    manual_audit_log(
        db=db,
        user_id=user.get("id"),
        username=user.get("username"),
        action=action,
        resource_type="system_config",
        resource_id=None,
        old_value=old_value,
        new_value=new_value,
        request=request,
    )


@router.get("/")
async def list_config(
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("admin")),
):
    return get_all_config(db)


@router.put("/")
async def update_config(
    data: dict[str, Any],
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("admin")),
):
    old_all = get_all_config(db)
    applied = {}
    skipped = []

    for key, value in (data or {}).items():
        if key not in DEFAULT_SYSTEM_CONFIG:
            skipped.append(key)
            continue
        # bool is a subclass of int; explicitly exclude it here so True is not written as a numeric config
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise HTTPException(status_code=400, detail=f"配置项 {key} 必须是数字")
        set_config(db, key, value, user.get("username") or "")
        applied[key] = value

    new_all = get_all_config(db)
    _log(
        db, user, "更新系统配置",
        old_value={k: old_all[k]["value"] for k in applied},
        new_value=applied,
        request=request,
    )
    db.commit()

    return {"configs": new_all, "updated": list(applied.keys()), "skipped": skipped}


@router.post("/reset")
async def reset_config(
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("admin")),
):
    old_all = get_all_config(db)
    for key, value in DEFAULT_SYSTEM_CONFIG.items():
        set_config(db, key, value, user.get("username") or "")

    new_all = get_all_config(db)
    _log(
        db, user, "恢复系统配置默认值",
        old_value={k: old_all[k]["value"] for k in DEFAULT_SYSTEM_CONFIG},
        new_value=dict(DEFAULT_SYSTEM_CONFIG),
        request=request,
    )
    db.commit()

    return {"configs": new_all, "message": "已恢复默认配置"}
