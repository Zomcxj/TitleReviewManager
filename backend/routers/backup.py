"""
Data backup management (admin only)

- View the historical backup list (reads the manifest)
- Manually trigger one backup (runs synchronously)
- View the current backup configuration

See tasks/backup.py for the underlying implementation; automatic backups run
daily via utils/scheduler.py. For restore steps, see the tasks/backup.py module
docstring and .env.example.
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
    """Manual backup request body (optional).

    When include_files is None, the BACKUP_INCLUDE_FILES configuration applies.
    """
    include_files: bool | None = None


def _log(db: Session, user: dict, action: str, new_value=None, request: Request = None):
    """Write an operation audit log (committed with the caller's transaction)"""
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
    """List all backups (newest first) and the backup directory configuration"""
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
    """Run one backup immediately (returns a result summary synchronously).

    Note: the backup includes packaging material files and may take a long time
    (minutes) with large data volumes. In production, rely on the scheduler to run
    automatically in the early morning; this endpoint is mainly for manual
    verification of small datasets or emergency backups. Frontend callers should
    set a sufficiently long request timeout.
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
    """Return the current backup configuration for the admin UI"""
    return backup_task.get_backup_config()
