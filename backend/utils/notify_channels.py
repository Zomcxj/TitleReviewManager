"""
External notification channels (email / webhook)

In-app notifications are handled by notifications.create_notification; this module
mirrors important notifications to external channels so users get alerted without
logging in.

Design principles:
- Fully configured via environment variables; unconfigured channels are silently
  skipped (never affects the main business flow)
- Send failures are only logged, never raised to interrupt business (notifications are auxiliary)
- Email uses the stdlib smtplib (no new dependency); webhooks use stdlib urllib
- Supports on/off switches and a minimum notify level (only push important types, avoid bombardment)
"""
import json
import logging
import os
import smtplib
import threading
from email.header import Header
from email.mime.text import MIMEText
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

logger = logging.getLogger(__name__)

# ---------- Configuration ----------
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", "") or SMTP_USER
SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "1") not in ("0", "false", "False")
# Whether to force STARTTLS on non-SSL ports (e.g. 25/587): intranet mail servers often lack it, off by default
SMTP_USE_STARTTLS = os.getenv("SMTP_USE_STARTTLS", "0") not in ("0", "false", "False")
EMAIL_ENABLED = os.getenv("EMAIL_NOTIFY_ENABLED", "0") not in ("0", "false", "False")

WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
WEBHOOK_ENABLED = os.getenv("WEBHOOK_NOTIFY_ENABLED", "0") not in ("0", "false", "False")

# Only push notifications of these types to external channels (avoid trivia bombardment); "*" means all
EXTERNAL_NOTIFY_TYPES = {
    t.strip() for t in os.getenv("EXTERNAL_NOTIFY_TYPES", "status_change,sla_overdue,pool_recovery").split(",") if t.strip()
}


def _should_notify(notify_type: str) -> bool:
    if "*" in EXTERNAL_NOTIFY_TYPES:
        return True
    return notify_type in EXTERNAL_NOTIFY_TYPES


def _send_email(to_addr: str, subject: str, content: str) -> bool:
    """Send an email; returns False on failure (never raises)"""
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
            # Only upgrade TLS when explicitly enabled — intranet SMTP often lacks STARTTLS
            if SMTP_USE_STARTTLS:
                server.starttls()
        try:
            # Only log in when credentials are configured and the server advertises AUTH (intranet relays often need none)
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


def _webhook_url_is_safe(url: str) -> bool:
    """Only allow http/https webhook URLs.

    WEBHOOK_URL is configured by an admin, but if misconfigured or tampered with,
    urlopen would accept schemes like file:// to read local files (CWE-22).
    This tightens the check at the scheme level.
    """
    from urllib.parse import urlparse
    try:
        scheme = urlparse(url).scheme.lower()
    except Exception:
        return False
    return scheme in ("http", "https")


def _send_webhook(payload: dict) -> bool:
    """Push a webhook (WeCom/DingTalk/Feishu bots etc.); returns False on failure"""
    if not (WEBHOOK_ENABLED and WEBHOOK_URL):
        return False
    if not _webhook_url_is_safe(WEBHOOK_URL):
        logger.warning("Webhook 地址协议不被允许（仅支持 http/https），已跳过推送")
        return False
    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = UrlRequest(WEBHOOK_URL, data=data, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(req, timeout=10) as resp:  # nosec B310 - scheme already restricted to http/https by _webhook_url_is_safe
            ok = 200 <= resp.status < 300
        if ok:
            logger.info(f"Webhook 通知已推送: {payload.get('title')}")
        return ok
    except Exception as e:
        logger.warning(f"Webhook 通知推送失败: {e}")
        return False


def _dispatch(notify_type: str, title: str, content: str, email: str | None) -> None:
    """Actual send logic (runs in a background thread)"""
    if email:
        _send_email(email, title, content)
    _send_webhook({"msgtype": "text", "text": {"content": f"{title}\n{content}"},
                   "title": title, "type": notify_type, "content": content})


def notify_external(
    notify_type: str,
    title: str,
    content: str,
    email: str | None = None,
    background: bool = True,
) -> None:
    """
    Push a notification to external channels.

    Runs in a background thread so SMTP/HTTP never blocks the request; returns
    immediately when no channel is configured. Callers need no try/except —
    this function swallows all exceptions internally.
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
    """Return the configuration status of each channel (for the admin UI, no secrets exposed)"""
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
