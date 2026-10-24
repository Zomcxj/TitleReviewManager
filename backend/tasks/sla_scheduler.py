#!/usr/bin/env python3
"""
SLA scheduled tasks
- Daily check for overdue customers
- Automatically release customers not followed up for N days
- Send expiring-soon reminders
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from database import get_db
from models import Customer, Notification
from routers.notifications import create_notification
from utils.system_config import get_config
from utils.timeutil import utcnow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

POOL_RECOVERY_DAYS = 7  # auto-recycle after 7 days without follow-up
SLA_HOURS_INITIAL = 24  # 24-hour SLA after initial assignment
SLA_HOURS_REVIEW = 48   # 48-hour SLA for review


def check_and_recovery_customers():
    """Check and recycle customers overdue for follow-up"""
    db = next(get_db())
    try:
        # Recovery days come from system config at runtime; the module-level constant is only a fallback default
        recovery_days = get_config(db, "pool_recovery_days") or POOL_RECOVERY_DAYS
        threshold = utcnow() - timedelta(days=recovery_days)

        # Use coalesce with creation time as the fallback, so newly created customers (never followed up) are not immediately mis-recycled
        overdue_customers = db.query(Customer).filter(
            Customer.is_public == False,  # noqa: E712
            Customer.is_deleted == False,  # noqa: E712
            Customer.assigned_salesman_id.isnot(None),
            func.coalesce(Customer.last_follow_up_at, Customer.created_at) < threshold
        ).all()
        
        for customer in overdue_customers:
            salesman_id = customer.assigned_salesman_id
            
            customer.assigned_salesman_id = None
            customer.is_public = True
            customer.public_at = utcnow()
            
            if salesman_id:
                create_notification(
                    db=db,
                    user_id=salesman_id,
                    title="客户自动回收",
                    content=f"客户 {customer.name} 因超过{recovery_days}天未跟进，已自动回收到公海池",
                    type="pool_recovery",
                    related_type="customer",
                    related_id=customer.id,
                )
                
                logger.info(f"客户 {customer.name} (ID={customer.id}) 已回收到公海池")
        
        db.commit()
        logger.info(f"本次回收 {len(overdue_customers)} 个客户")
        
    except Exception as e:
        db.rollback()
        logger.error(f"回收客户失败：{e}")
    finally:
        db.close()


def check_sla_deadlines():
    """Check SLA deadlines"""
    db = next(get_db())
    try:
        now = utcnow()
        
        expired = db.query(Customer).filter(
            Customer.sla_deadline < now,
            Customer.is_public == False,  # noqa: E712
            Customer.is_deleted == False,  # noqa: E712
            Customer.assigned_salesman_id.isnot(None)
        ).all()
        
        for customer in expired:
            salesman_id = customer.assigned_salesman_id
            if salesman_id:
                create_notification(
                    db=db,
                    user_id=salesman_id,
                    title="SLA 已超时",
                    content=f"客户 {customer.name} 的处理时效已超时，请尽快跟进",
                    type="sla_overdue",
                    related_type="customer",
                    related_id=customer.id,
                )
                logger.warning(f"客户 {customer.name} SLA 已超时")
            # Clear the expired SLA deadline to avoid repeated notifications on every run
            customer.sla_deadline = None
        
        db.commit()
        
    except Exception as e:
        db.rollback()
        logger.error(f"检查 SLA 失败：{e}")
    finally:
        db.close()


def send_expiring_reminders():
    """Send expiring-soon reminders (deduplicated within a 12-hour window)"""
    db = next(get_db())
    try:
        now = utcnow()
        twelve_hours_later = now + timedelta(hours=12)
        # Notification created_at is stored as aware UTC; dedup comparisons need aware datetimes
        dedup_since = datetime.now(timezone.utc) - timedelta(hours=12)
        
        expiring = db.query(Customer).filter(
            Customer.sla_deadline.between(now, twelve_hours_later),
            Customer.is_public == False,  # noqa: E712
            Customer.is_deleted == False,  # noqa: E712
            Customer.assigned_salesman_id.isnot(None)
        ).all()
        
        for customer in expiring:
            salesman_id = customer.assigned_salesman_id
            if salesman_id:
                # Skip customers already reminded within 12 hours, avoiding repeated bombardment
                reminded = db.query(Notification).filter(
                    Notification.type == "sla_warning",
                    Notification.related_type == "customer",
                    Notification.related_id == customer.id,
                    Notification.created_at >= dedup_since,
                ).first()
                if reminded:
                    continue
                create_notification(
                    db=db,
                    user_id=salesman_id,
                    title="SLA 即将超时",
                    content=f"客户 {customer.name} 将在 12 小时内超时，请及时跟进",
                    type="sla_warning",
                    related_type="customer",
                    related_id=customer.id,
                )
                logger.info(f"客户 {customer.name} SLA 即将超时")
        
        db.commit()
        
    except Exception as e:
        db.rollback()
        logger.error(f"发送提醒失败：{e}")
    finally:
        db.close()


if __name__ == "__main__":
    logger.info("开始执行 SLA 定时任务")
    check_and_recovery_customers()
    check_sla_deadlines()
    send_expiring_reminders()
    logger.info("SLA 定时任务执行完成")
