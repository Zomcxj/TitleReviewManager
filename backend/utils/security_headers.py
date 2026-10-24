"""
Security response header middleware

Default browser behavior is not safe enough for an internal management system:
- Without CSP, a single XSS injection can load arbitrary external scripts and
  exfiltrate customer data
- Without X-Frame-Options, pages can be embedded in third-party iframes for
  clickjacking (this system has one-click actions like "approve/return", so the
  impact is direct)
- Without nosniff, browsers may parse an uploaded .pdf as HTML and execute it

This module injects the headers uniformly. The CSP must accommodate what the
frontend actually uses: the Vue runtime, Element Plus inline styles, image
blob/data previews, and PDF iframe previews.
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# Allowed frontend capabilities:
# - script-src 'self': Vite output is local files, no inline script needed
# - style-src 'unsafe-inline': Element Plus injects inline styles at runtime, must be allowed
# - img-src blob: data:: material image previews use blob URLs
# - frame-src 'self' blob:: PDF previews load the same-origin download endpoint in an iframe
# - connect-src 'self': API and progress polling are same-origin
CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "frame-src 'self' blob:; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "X-XSS-Protection": "0",  # Deprecated by modern browsers; explicitly off so legacy versions do not misfire
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Content-Security-Policy": CSP_POLICY,
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject security headers into every response."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            # Do not override headers the business code has explicitly set
            response.headers.setdefault(key, value)
        # Enable HSTS in production behind HTTPS (opt-in via env var, so local dev is not force-redirected)
        import os
        if os.getenv("ENABLE_HSTS", "0") not in ("0", "false", "False"):
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


class HttpsRedirectMiddleware(BaseHTTPMiddleware):
    """Force HTTPS redirects (active when FORCE_HTTPS=1).

    Redirecting at the Nginx/Caddy layer is usually more efficient; this provides an
    application-level fallback for setups that expose the app port directly or whose
    proxy is not configured to redirect.

    Health check path exemption: the container HEALTHCHECK uses in-container http;
    if redirected, the probe would keep failing and the container would restart repeatedly.
    """

    # Path prefixes exempt from redirecting (health probes must be exempt)
    EXEMPT_PREFIXES = ("/api/health",)

    async def dispatch(self, request: Request, call_next):
        import os
        if os.getenv("FORCE_HTTPS", "0") not in ("0", "false", "False"):
            from utils.request_context import is_https_request
            path = request.url.path
            if not any(path.startswith(p) for p in self.EXEMPT_PREFIXES) and not is_https_request(request):
                # Keep the original host and query string, redirect to https
                host = request.headers.get("host", "")
                url = request.url.replace(scheme="https", netloc=host)
                from starlette.responses import RedirectResponse
                return RedirectResponse(url=str(url), status_code=301)
        return await call_next(request)
