#!/usr/bin/env python3
"""
SLA 时效管理定时任务
- 每日检查超时客户
- 自动释放 N 天未跟进的客户
- 发送即将超时提醒
"""

from database import get_db
from models import Customer, User, Notification
from datetime import datetime, timezone, timedelta
from routers.notifications import create_notification
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

POOL_RECOVERY_DAYS = 7  # 7 天未跟进自动回收
SLA_HOURS_INITIAL = 24  # 初次分配 24 小时 SLA
SLA_HOURS_REVIEW = 48   # 审核 48 小时 SLA


def check_and_recovery_customers():
    """检查并回收超时未跟进的客户"""
    db = next(get_db())
    try:
        threshold = datetime.utcnow() - timedelta(days=POOL_RECOVERY_DAYS)
        
        overdue_customers = db.query(Customer).filter(
            Customer.is_public == False,
            Customer.assigned_salesman_id.isnot(None),
            or_(
                Customer.last_follow_up_at < threshold,
                Customer.last_follow_up_at == None
            )
        ).all()
        
        for customer in overdue_customers:
            salesman_id = customer.assigned_salesman_id
            
            customer.assigned_salesman_id = None
            customer.is_public = True
            customer.public_at = datetime.utcnow()
            
            if salesman_id:
                create_notification(
                    db=db,
                    user_id=salesman_id,
                    title="客户自动回收",
                    content=f"客户 {customer.name} 因超过{POOL_RECOVERY_DAYS}天未跟进，已自动回收到公海池",
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
    """检查 SLA 截止时间"""
    db = next(get_db())
    try:
        now = datetime.utcnow()
        
        expired = db.query(Customer).filter(
            Customer.sla_deadline < now,
            Customer.is_public == False,
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
        
        db.commit()
        
    except Exception as e:
        db.rollback()
        logger.error(f"检查 SLA 失败：{e}")
    finally:
        db.close()


def send_expiring_reminders():
    """发送即将超时提醒"""
    db = next(get_db())
    try:
        now = datetime.utcnow()
        twelve_hours_later = now + timedelta(hours=12)
        
        expiring = db.query(Customer).filter(
            Customer.sla_deadline.between(now, twelve_hours_later),
            Customer.is_public == False,
            Customer.assigned_salesman_id.isnot(None)
        ).all()
        
        for customer in expiring:
            salesman_id = customer.assigned_salesman_id
            if salesman_id:
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
