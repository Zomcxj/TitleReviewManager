"""
外部通知渠道（邮件 / Webhook）

站内通知由 notifications.create_notification 负责；本模块负责把重要通知
同步推送到外部渠道，让用户不登录也能收到提醒。

设计原则：
- 全部通过环境变量配置，未配置即静默跳过（不影响主业务流程）
- 发送失败只记日志，绝不抛异常打断业务（通知是附属能力）
- 邮件用标准库 smtplib（不引入新依赖），Webhook 用标准库 urllib
- 支持开关与最小发送级别（只推重要类型，避免轰炸）
"""
import os
import json
import smtplib
import logging
import threading
from email.mime.text import MIMEText
from email.header import Header
from typing import Optional
from urllib.request import Request as UrlRequest, urlopen

logger = logging.getLogger(__name__)

# ---------- 配置 ----------
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", "") or SMTP_USER
SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "1") not in ("0", "false", "False")
# 非 SSL 端口（如 25/587）是否强制 STARTTLS：内网邮件服务器常不支持，默认关闭
SMTP_USE_STARTTLS = os.getenv("SMTP_USE_STARTTLS", "0") not in ("0", "false", "False")
EMAIL_ENABLED = os.getenv("EMAIL_NOTIFY_ENABLED", "0") not in ("0", "false", "False")

WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
WEBHOOK_ENABLED = os.getenv("WEBHOOK_NOTIFY_ENABLED", "0") not in ("0", "false", "False")

# 只推送这些类型的通知到外部渠道（避免琐碎通知轰炸）；配置 "*" 表示全部
EXTERNAL_NOTIFY_TYPES = {
    t.strip() for t in os.getenv("EXTERNAL_NOTIFY_TYPES", "status_change,sla_overdue,pool_recovery").split(",") if t.strip()
}


def _should_notify(notify_type: str) -> bool:
    if "*" in EXTERNAL_NOTIFY_TYPES:
        return True
    return notify_type in EXTERNAL_NOTIFY_TYPES


def _send_email(to_addr: str, subject: str, content: str) -> bool:
    """发送邮件，失败返回 False（不抛异常）"""
    if not (EMAIL_ENABLED and SMTP_HOST and to_addr):
        return False
    try:
        msg = MIMEText(content, "plain", "utf-8")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = SMTP_FROM
        msg["To"] = to_addr
        if SMTP_USE_SSL:
            server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=10)
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10)
            # 仅在显式开启时才升级 TLS —— 内网 SMTP 常不支持 STARTTLS
            if SMTP_USE_STARTTLS:
                server.starttls()
        try:
            # 仅在配置了账号密码且服务器声明支持 AUTH 时才登录（内网中继常无需认证）
            if SMTP_USER and SMTP_PASS and server.has_extn("auth"):
                server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_FROM, [to_addr], msg.as_string())
        finally:
            server.quit()
        logger.info(f"邮件通知已发送至 {to_addr}: {subject}")
        return True
    except Exception as e:
        logger.warning(f"邮件通知发送失败({to_addr}): {e}")
        return False


def _send_webhook(payload: dict) -> bool:
    """推送 Webhook（企业微信/钉钉/飞书等机器人），失败返回 False"""
    if not (WEBHOOK_ENABLED and WEBHOOK_URL):
        return False
    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = UrlRequest(WEBHOOK_URL, data=data, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(req, timeout=10) as resp:
            ok = 200 <= resp.status < 300
        if ok:
            logger.info(f"Webhook 通知已推送: {payload.get('title')}")
        return ok
    except Exception as e:
        logger.warning(f"Webhook 通知推送失败: {e}")
        return False


def _dispatch(notify_type: str, title: str, content: str, email: Optional[str]) -> None:
    """实际发送逻辑（在后台线程中执行）"""
    if email:
        _send_email(email, title, content)
    _send_webhook({"msgtype": "text", "text": {"content": f"{title}\n{content}"},
                   "title": title, "type": notify_type, "content": content})


def notify_external(
    notify_type: str,
    title: str,
    content: str,
    email: Optional[str] = None,
    background: bool = True,
) -> None:
    """
    向外部渠道推送通知。

    在后台线程执行，避免 SMTP/HTTP 阻塞请求；未配置渠道时立即返回。
    调用方无需 try/except —— 本函数内部已吞掉所有异常。
    """
    if not _should_notify(notify_type):
        return
    if not ((EMAIL_ENABLED and SMTP_HOST) or (WEBHOOK_ENABLED and WEBHOOK_URL)):
        return

    if background:
        threading.Thread(
            target=_dispatch, args=(notify_type, title, content, email), daemon=True
        ).start()
    else:
        _dispatch(notify_type, title, content, email)


def channel_status() -> dict:
    """返回各渠道配置状态（供管理界面展示，不暴露密码）"""
    return {
        "email": {
            "enabled": EMAIL_ENABLED,
            "configured": bool(SMTP_HOST and SMTP_USER),
            "host": SMTP_HOST or "(未配置)",
            "from": SMTP_FROM or "(未配置)",
        },
        "webhook": {
            "enabled": WEBHOOK_ENABLED,
            "configured": bool(WEBHOOK_URL),
            "url_set": bool(WEBHOOK_URL),
        },
        "notify_types": sorted(EXTERNAL_NOTIFY_TYPES) if "*" not in EXTERNAL_NOTIFY_TYPES else ["*"],
    }
