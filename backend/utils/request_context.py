"""
Request context utilities

Production deployments usually sit behind Nginx/Caddy, where `request.client.host`
is the **reverse proxy's IP**, not the real client IP. Using it directly causes
three practical problems:
1. IP-based rate limiting treats all users as one IP; legitimate users block each other
2. Audit log ip_address values are all identical, losing traceability
3. Brute-force alerts cannot locate the real source

Hence real IPs are parsed from proxy headers uniformly, guarded by a
"trusted proxy" switch — X-Forwarded-For must not be trusted unconditionally
(clients can forge it); only trust it when we are truly behind a proxy (TRUST_PROXY=1).
"""
import os

from starlette.requests import Request

# Whether we sit behind a reverse proxy. X-Forwarded-For / X-Real-IP are trusted only when enabled.
TRUST_PROXY = os.getenv("TRUST_PROXY", "0") not in ("0", "false", "False")


def get_client_ip(request: Request) -> str:
    """Get the real client IP.

    Resolution order:
    1. With TRUST_PROXY enabled: the **first** address in X-Forwarded-For (closest to the client)
    2. With TRUST_PROXY enabled: X-Real-IP (common with Nginx)
    3. Fall back to the direct address request.client.host

    Note: X-Forwarded-For can be forged by clients; only use it when we are certain
    we sit behind a trusted proxy (TRUST_PROXY=1). Single-host direct deployments keep
    the default 0 so forged headers cannot bypass rate limiting.
    """
    if TRUST_PROXY:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            # Format "client, proxy1, proxy2"; the first entry is the original client
            first = forwarded.split(",")[0].strip()
            if first:
                return first
        real_ip = request.headers.get("x-real-ip", "").strip()
        if real_ip:
            return real_ip

    return request.client.host if request.client else "unknown"


def is_https_request(request: Request) -> bool:
    """Whether the current request is HTTPS (reverse proxy aware)"""
    if request.url.scheme == "https":
        return True
    if TRUST_PROXY:
        proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
        return proto == "https"
    return False


def cookie_secure_flag() -> bool:
    """Whether cookies should carry the Secure attribute.

    Controlled by the COOKIE_SECURE env var (default 0, convenient for local http dev).
    Must be 1 in production behind HTTPS, otherwise cookies may be intercepted in transit.
    """
    return os.getenv("COOKIE_SECURE", "0") not in ("0", "false", "False")


def cookie_extra_kwargs() -> dict:
    """Return the security kwargs needed by set_cookie"""
    kwargs = {"httponly": True, "samesite": "lax"}
    if cookie_secure_flag():
        kwargs["secure"] = True
    return kwargs
