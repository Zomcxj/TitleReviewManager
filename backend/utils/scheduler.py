"""
内置定时任务调度（轻量实现，无需额外依赖）

背景：SLA 自动回收 / 超时提醒依赖 tasks/sla_scheduler.py，但此前只能靠外部
cron 手动调用，部署时极易遗漏 —— 结果就是「自动回收」这个功能静默失效。

这里在应用进程内启动一个守护线程，按固定间隔执行调度任务：
- 多 worker 场景下每个 worker 都会启动线程 → 用文件锁避免重复执行
- 可通过环境变量 SCHEDULER_ENABLED=0 关闭（例如改用外部 cron 统一调度）
- 间隔由 SCHEDULER_INTERVAL_MINUTES 控制，默认 60 分钟

注意：这是"够用"的方案。若后续任务量增大或需要精确调度，
建议换成独立 worker（Celery / APScheduler 持久化作业存储）。
"""
import os
import time
import logging
import threading
import tempfile
from datetime import datetime

logger = logging.getLogger(__name__)

SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "1") not in ("0", "false", "False")
INTERVAL_MINUTES = int(os.getenv("SCHEDULER_INTERVAL_MINUTES", "60"))
# 首次执行延迟，避免与应用启动竞争资源
STARTUP_DELAY_SECONDS = int(os.getenv("SCHEDULER_STARTUP_DELAY", "60"))

_thread: threading.Thread = None
_stop_event = threading.Event()
# 跨进程互斥：同一时刻只允许一个 worker 真正执行任务
_LOCK_FILE = os.path.join(tempfile.gettempdir(), "trm_scheduler.lock")
# 任务执行间隔内的锁有效期（略大于间隔，避免死锁残留）
_LOCK_TTL_SECONDS = max(INTERVAL_MINUTES * 60 - 30, 60)


def _acquire_lock() -> bool:
    """基于文件时间戳的简易跨进程锁"""
    try:
        now = time.time()
        if os.path.exists(_LOCK_FILE):
            if now - os.path.getmtime(_LOCK_FILE) < _LOCK_TTL_SECONDS:
                return False
        with open(_LOCK_FILE, "w") as f:
            f.write(f"{os.getpid()}@{datetime.utcnow().isoformat()}")
        return True
    except Exception as e:
        logger.warning(f"调度锁获取失败（按可执行处理）: {e}")
        return True


def _maybe_run_backup(result: dict) -> None:
    """按小时判断是否需要执行自动备份，并把结果写入 result。

    备份可能耗时（打包材料文件），但运行在后台调度线程中，不影响请求链路。
    备份失败只记日志 / 写入 warnings，不加入 errors —— 备份失败不应让整个
    调度任务被判定为失败。
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
        else:
            # 备份失败降级为 warning，避免拖垮整个调度任务的健康状态
            result["warnings"].append(f"自动备份失败: {outcome.get('error')}")
            logger.error(f"自动备份失败: {outcome.get('error')}")
    except Exception as e:
        result["warnings"].append(f"自动备份异常: {e}")
        logger.error(f"自动备份异常: {e}", exc_info=True)


def run_once() -> dict:
    """执行一轮全部调度任务（供定时线程与手动调用共用）"""
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

    # 顺带清理过期记录，避免表无限增长
    try:
        from database import SessionLocal
        from utils.login_guard import cleanup_old_attempts
        from utils.session_manager import cleanup_expired_sessions
        db = SessionLocal()
        try:
            cleanup_old_attempts(db, older_than_hours=24)
            cleanup_expired_sessions(db, older_than_days=30)
        finally:
            db.close()
    except Exception as e:
        result["errors"].append(f"清理过期记录: {e}")

    # 每日自动备份（数据库 + 材料文件）：仅当当前小时 == BACKUP_HOUR 且今天未备份过
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
                # 备份失败只作为 warning 提示，不影响调度整体判定
                if res.get("warnings"):
                    logger.warning(f"调度任务警告: {res['warnings']}")
            else:
                logger.debug("其他 worker 正在执行调度任务，本次跳过")
        except Exception as e:
            logger.error(f"调度循环异常: {e}", exc_info=True)
        _stop_event.wait(INTERVAL_MINUTES * 60)


def start_scheduler() -> bool:
    """启动后台调度线程（重复调用安全）"""
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
    """停止调度线程（用于测试或优雅关闭）"""
    _stop_event.set()
    if _thread and _thread.is_alive():
        _thread.join(timeout=5)
