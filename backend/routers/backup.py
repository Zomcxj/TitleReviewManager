"""
数据备份管理（仅管理员）

- 查看历史备份列表（读 manifest）
- 手动触发一次备份（同步执行）
- 查看当前备份配置

底层实现见 tasks/backup.py；自动备份由 utils/scheduler.py 每天定时执行。
恢复步骤见 tasks/backup.py 模块 docstring 与 .env.example。
"""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import require_role
from database import get_db
from tasks import backup as backup_task
from utils.audit_logger import manual_audit_log

router = APIRouter(prefix="/api/backup", tags=["数据备份"])


class BackupRunRequest(BaseModel):
    """手动备份请求体（可选）。

    include_files 为 None 时沿用 BACKUP_INCLUDE_FILES 配置。
    """
    include_files: bool | None = None


def _log(db: Session, user: dict, action: str, new_value=None, request: Request = None):
    """写操作审计日志（随调用方事务一起提交）"""
    manual_audit_log(
        db=db,
        user_id=user.get("id"),
        username=user.get("username"),
        action=action,
        resource_type="backup",
        resource_id=None,
        old_value=None,
        new_value=new_value,
        request=request,
    )


@router.get("/")
async def list_backups(
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("admin")),
):
    """列出所有备份（按时间倒序）与备份目录配置"""
    items = backup_task.list_backups()
    return {
        "items": items,
        "total": len(items),
        "backup_dir": backup_task.get_backup_dir(),
        "enabled": backup_task.is_enabled(),
    }


@router.post("/run")
async def run_backup_now(
    data: BackupRunRequest = None,
    request: Request = None,
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("admin")),
):
    """立即执行一次备份（同步返回结果摘要）。

    注意：备份包含材料文件打包，数据量大时可能耗时较久（分钟级）。
    生产环境建议依赖调度器在凌晨自动执行，此接口主要用于小数据量手动验证
    或紧急备份；如前端调用，请设置足够的请求超时时间。
    """
    include_files = data.include_files if data else None
    outcome = backup_task.run_backup(include_files=include_files)
    _log(
        db, user, "手动执行数据备份",
        new_value={
            "success": outcome.get("success"),
            "db_backup": outcome.get("db_backup"),
            "files_backup": outcome.get("files_backup"),
            "error": outcome.get("error"),
        },
        request=request,
    )
    db.commit()
    return outcome


@router.get("/config")
async def get_backup_config(
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("admin")),
):
    """返回当前备份配置，供管理界面展示"""
    return backup_task.get_backup_config()
