"""
Built-in scheduled task runner (lightweight, no extra dependencies)

Background: SLA auto-recovery / overdue reminders depend on tasks/sla_scheduler.py,
but this used to rely on manually wired external cron, easily missed during
deployment — the result was "auto-recovery" silently failing.

Here a daemon thread inside the application process runs scheduled tasks at a
fixed interval:
- With multiple workers each worker starts the thread -> a file lock avoids duplicate execution
- Can be disabled via SCHEDULER_ENABLED=0 (e.g. switching to a unified external cron)
- Interval controlled by SCHEDULER_INTERVAL_MINUTES, default 60 minutes

Note: this is a "good enough" solution. If the workload grows or precise scheduling
is needed, switch to a dedicated worker (Celery / APScheduler with persistent job store).
"""
import logging
import os
import tempfile
import threading
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "1") not in ("0", "false", "False")
INTERVAL_MINUTES = int(os.getenv("SCHEDULER_INTERVAL_MINUTES", "60"))
# Startup delay, avoiding resource contention with application startup
STARTUP_DELAY_SECONDS = int(os.getenv("SCHEDULER_STARTUP_DELAY", "60"))

_thread: threading.Thread = None
_stop_event = threading.Event()
# Cross-process mutual exclusion: only one worker may actually run the tasks at a time
_LOCK_FILE = os.path.join(tempfile.gettempdir(), "trm_scheduler.lock")
# Lock TTL within one execution interval (slightly longer than the interval, avoiding stale deadlocks)
_LOCK_TTL_SECONDS = max(INTERVAL_MINUTES * 60 - 30, 60)


def _acquire_lock() -> bool:
    """Simple cross-process lock based on the lock file's timestamp"""
    try:
        now = time.time()
        if os.path.exists(_LOCK_FILE) and now - os.path.getmtime(_LOCK_FILE) < _LOCK_TTL_SECONDS:
            return False
        with open(_LOCK_FILE, "w") as f:
            f.write(f"{os.getpid()}@{datetime.now(timezone.utc).isoformat()}")
        return True
    except Exception as e:
        logger.warning(f"调度锁获取失败（按可执行处理）: {e}")
        return True


def _maybe_run_backup(result: dict) -> None:
    """Decide by hour whether to run the automatic backup, writing the outcome into result.

    Backups can be slow (packing material files), but they run in the background
    scheduler thread, never on the request path. Backup failures are only logged /
    appended to warnings, not errors — a failed backup must not mark the whole
    scheduled run as failed.
    """
    try:
        from tasks import backup as backup_task
    except Exception as e:
        result["warnings"].append(f"备份模块导入失败: {e}")
        logger.error(f"备份模块导入失败: {e}", exc_info=True)
        return

    try:
        if not backup_task.should_run_now():
            return
        logger.info("到达备份时间点，开始执行自动备份")
        outcome = backup_task.run_backup()
        result["backup"] = outcome
        if outcome.get("success"):
            logger.info(f"自动备份成功: {outcome.get('db_backup')}")
            _maybe_run_restore_drill(result)
        else:
            # Degrade backup failure to a warning so it does not drag down the scheduled run's health
            result["warnings"].append(f"自动备份失败: {outcome.get('error')}")
            logger.error(f"自动备份失败: {outcome.get('error')}")
    except Exception as e:
        result["warnings"].append(f"自动备份异常: {e}")
        logger.error(f"自动备份异常: {e}", exc_info=True)


def _maybe_run_restore_drill(result: dict) -> None:
    """After a successful backup, run a restore drill to prove the backup is actually usable.

    "A backup whose restore has never been drilled equals no backup" — whether the
    backup file format, paths and manifest match the actual content is only known by
    restoring once for real. The drill runs in a temp directory and never touches
    production data.

    A failed drill is only logged as a warning and does not affect the backup's own outcome.
    """
    if os.getenv("BACKUP_DRILL_ENABLED", "1") in ("0", "false", "False"):
        return
    try:
        from tasks import restore as restore_task
        report = restore_task.drill()
        result["restore_drill"] = {
            "ok": report.get("ok"),
            "row_counts": report.get("row_counts"),
        }
        if report.get("ok"):
            logger.info(f"恢复演练通过: {report.get('row_counts')}")
        else:
            result["warnings"].append(f"恢复演练未通过: {report}")
    except Exception as e:
        # A failed drill means "this backup may not be restorable" — alert explicitly instead of staying silent
        result["warnings"].append(f"恢复演练失败（备份可用性存疑）: {e}")
        logger.error(f"恢复演练失败: {e}", exc_info=True)


def run_once() -> dict:
    """Run one round of all scheduled tasks (shared by the timer thread and manual calls)"""
    from tasks import sla_scheduler
    result = {
        "recovered": 0, "sla_notified": 0, "reminded": 0,
        "errors": [], "warnings": [], "backup": None,
    }

    for name, fn in (
        ("客户自动回收", sla_scheduler.check_and_recovery_customers),
        ("SLA 超时提醒", sla_scheduler.check_sla_deadlines),
        ("SLA 临期提醒", sla_scheduler.send_expiring_reminders),
    ):
        try:
            fn()
        except Exception as e:
            result["errors"].append(f"{name}: {e}")
            logger.error(f"调度任务「{name}」执行失败: {e}", exc_info=True)

    try:
        from utils.reminders import send_operational_reminders
        reminder_stats = send_operational_reminders()
        result["reminders"] = reminder_stats
    except Exception as e:
        result["errors"].append(f"运营催办: {e}")
        logger.error(f"调度任务「运营催办」执行失败: {e}", exc_info=True)

    # Also clean up expired records, keeping tables from growing unbounded
    try:
        from datetime import timedelta

        from database import SessionLocal
        from models import ClientError
        from utils.login_guard import cleanup_old_attempts
        from utils.session_manager import cleanup_expired_sessions
        from utils.timeutil import utcnow
        db = SessionLocal()
        try:
            cleanup_old_attempts(db, older_than_hours=24)
            cleanup_expired_sessions(db, older_than_days=30)
            # Frontend error reports are diagnostic data with no audit value; every
            # client error POST writes a row, so a buggy release could flood this
            # table. Cap at 90 days to keep it bounded.
            cutoff = utcnow() - timedelta(days=90)
            deleted = db.query(ClientError).filter(ClientError.created_at < cutoff).delete(synchronize_session=False)
            if deleted:
                db.commit()
                logger.info(f"Cleaned {deleted} client error reports older than 90 days")
        finally:
            db.close()
    except Exception as e:
        result["errors"].append(f"清理过期记录: {e}")

    # Daily automatic backup (database + material files): only when the current hour == BACKUP_HOUR and not backed up today
    _maybe_run_backup(result)

    return result


def _loop():
    if _stop_event.wait(STARTUP_DELAY_SECONDS):
        return
    while not _stop_event.is_set():
        try:
            if _acquire_lock():
                logger.info("开始执行定时调度任务")
                res = run_once()
                if res["errors"]:
                    logger.warning(f"调度任务存在错误: {res['errors']}")
                else:
                    logger.info("定时调度任务执行完成")
                # Backup failures are surfaced as warnings only; they do not affect the overall run verdict
                if res.get("warnings"):
                    logger.warning(f"调度任务警告: {res['warnings']}")
            else:
                logger.debug("其他 worker 正在执行调度任务，本次跳过")
        except Exception as e:
            logger.error(f"调度循环异常: {e}", exc_info=True)
        _stop_event.wait(INTERVAL_MINUTES * 60)


def start_scheduler() -> bool:
    """Start the background scheduler thread (safe to call repeatedly)"""
    global _thread
    if not SCHEDULER_ENABLED:
        logger.info("内置调度器已禁用（SCHEDULER_ENABLED=0），请确保有外部计划任务调用 sla_scheduler")
        return False
    if _thread and _thread.is_alive():
        return True
    _stop_event.clear()
    _thread = threading.Thread(target=_loop, name="sla-scheduler", daemon=True)
    _thread.start()
    logger.info(f"内置调度器已启动（每 {INTERVAL_MINUTES} 分钟执行一次）")
    return True


def stop_scheduler() -> None:
    """Stop the scheduler thread (for tests or graceful shutdown)"""
    _stop_event.set()
    if _thread and _thread.is_alive():
        _thread.join(timeout=5)
