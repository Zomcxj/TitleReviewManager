"""
安全响应头中间件

浏览器默认行为对内部管理系统并不够安全：
- 缺少 CSP 时，一旦有 XSS 注入就能任意加载外部脚本、外发客户资料
- 缺少 X-Frame-Options 时，页面可被嵌套进第三方 iframe 做点击劫持
  （本系统有"通过/退回"这类一键操作，点击劫持后果直接）
- 缺少 nosniff 时，浏览器可能把上传的 .pdf 当 HTML 解析执行

这里统一注入响应头。CSP 需兼顾前端实际用到的能力：
Vue 运行时、Element Plus 的 inline style、图片 blob/data 预览、PDF iframe 预览。
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# 允许的前端能力：
# - script-src 'self'：Vite 产物为本地文件，无需 inline script
# - style-src 'unsafe-inline'：Element Plus 运行时注入内联样式，必须放行
# - img-src blob: data:：材料图片预览用 blob URL
# - frame-src 'self' blob:：PDF 预览用 iframe 加载同源下载接口
# - connect-src 'self'：接口与进度查询都在同源
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
    "X-XSS-Protection": "0",  # 现代浏览器已废弃该头，显式关闭避免旧版误拦截
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Content-Security-Policy": CSP_POLICY,
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """为所有响应注入安全头。"""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            # 不覆盖业务已显式设置的同名头
            response.headers.setdefault(key, value)
        # 生产环境走 HTTPS 时启用 HSTS（由环境变量显式开启，避免本地开发被强制跳转）
        import os
        if os.getenv("ENABLE_HSTS", "0") not in ("0", "false", "False"):
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response
