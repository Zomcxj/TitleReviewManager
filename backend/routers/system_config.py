"""
系统参数配置（仅管理员）

- 读取全部配置项（含中文标签与默认值）
- 批量更新（只接受已知 key 且值为数字）
- 一键恢复默认值

底层读写由 utils/system_config.py 提供（带短 TTL 缓存）。
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
        # bool 是 int 的子类，这里明确排除，避免 True 被当作数字配置写入
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
