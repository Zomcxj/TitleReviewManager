"""
请求上下文工具

生产部署通常在 Nginx/Caddy 之后，此时 `request.client.host` 是**反向代理的 IP**，
不是真实客户端 IP。直接用它会带来三个实际问题：
1. 按 IP 限流会把所有用户算作同一个 IP，正常用户被互相误伤
2. 审计日志的 ip_address 全部相同，失去追溯价值
3. 暴力破解告警无法定位真实来源

因此统一从代理头解析真实 IP，并按「可信代理层数」做防护 ——
不能无条件信任 X-Forwarded-For（客户端可以伪造），
只有当我们确实在代理后面（TRUST_PROXY=1）时才采信。
"""
import os
from typing import Optional
from starlette.requests import Request

# 是否处于反向代理之后。开启后才会采信 X-Forwarded-For / X-Real-IP。
TRUST_PROXY = os.getenv("TRUST_PROXY", "0") not in ("0", "false", "False")


def get_client_ip(request: Request) -> str:
    """获取真实客户端 IP。

    取值顺序：
    1. TRUST_PROXY 开启时：X-Forwarded-For 的**第一个**地址（最靠近客户端的）
    2. TRUST_PROXY 开启时：X-Real-IP（Nginx 常用）
    3. 回落到直连地址 request.client.host

    注意：X-Forwarded-For 可能被客户端伪造，只有在确认自己位于可信代理之后
    （TRUST_PROXY=1）才使用。单机直连部署保持默认 0，避免被伪造头绕过限流。
    """
    if TRUST_PROXY:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            # 形如 "client, proxy1, proxy2"，第一个是最初的客户端
            first = forwarded.split(",")[0].strip()
            if first:
                return first
        real_ip = request.headers.get("x-real-ip", "").strip()
        if real_ip:
            return real_ip

    return request.client.host if request.client else "unknown"


def is_https_request(request: Request) -> bool:
    """判断当前请求是否为 HTTPS（考虑反向代理场景）"""
    if request.url.scheme == "https":
        return True
    if TRUST_PROXY:
        proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
        return proto == "https"
    return False


def cookie_secure_flag() -> bool:
    """Cookie 是否应带 Secure 属性。

    由环境变量 COOKIE_SECURE 控制（默认 0，便于本地 http 开发）。
    生产环境走 HTTPS 时必须设为 1，否则 cookie 可能在明文信道被截获。
    """
    return os.getenv("COOKIE_SECURE", "0") not in ("0", "false", "False")


def cookie_extra_kwargs() -> dict:
    """返回 set_cookie 需要的安全参数"""
    kwargs = {"httponly": True, "samesite": "lax"}
    if cookie_secure_flag():
        kwargs["secure"] = True
    return kwargs
