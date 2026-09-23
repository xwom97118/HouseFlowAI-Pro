"""請求層級的 middleware（2026-09-23 Phase 3A）：
- Request correlation id（規格第 15 節）
- 簡易 in-memory rate limiting（規格第 11、10 節，Phase 3A local
  implementation，明確標記「單一 process 內有效」，之後如果 Render
  上跑多個 instance，需要換成集中式儲存如 Redis——這個限制寫在
  RateLimiter 的 docstring 裡）。
"""
from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from server.app.logging_config import log_event

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:16]
        request.state.request_id = request_id

        start = time.monotonic()
        response = await call_next(request)
        duration_ms = int((time.monotonic() - start) * 1000)

        response.headers[REQUEST_ID_HEADER] = request_id
        log_event(
            "http_request",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response


class RateLimiter:
    """固定視窗 + 記憶體內計數的最小可行 rate limiter。

    限制：只在單一 process 記憶體內有效——如果之後在 Render 上跑多個
    instance（水平擴展），各 instance 各算各的，達不到「全域每分鐘
    N 次」的效果，只能擋住單一 instance 收到的濫用流量。要做到跨
    instance 的限制，需要換成 Redis 之類的集中式儲存（留給正式規模
    擴大後決定，不在 Phase 3A 範圍內，已記錄在
    docs/PHASE3B_DEPLOY_CHECKLIST.md）。
    """

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window_seconds:
            hits.popleft()
        if len(hits) >= self.max_requests:
            return False
        hits.append(now)
        return True

    def reset(self) -> None:
        self._hits.clear()


# 給 License API 用（trial/start、license/activate、license/verify）
# ——每個 client IP 每分鐘最多 30 次，正常 HouseFlow 使用（定期
# verify、偶爾 activate）遠低於這個量，但能擋掉暴力嘗試 License Key
# 的行為。
license_api_rate_limiter = RateLimiter(max_requests=30, window_seconds=60)

# 給 Admin 登入用——每個 (username, IP) 組合每 5 分鐘最多 5 次失敗嘗試
# （見 admin_auth_service 的 record_failed_login/is_locked_out）。
admin_login_rate_limiter = RateLimiter(max_requests=10, window_seconds=300)


def rate_limit_response(retry_after_seconds: int = 60) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "請求過於頻繁，請稍後再試。"},
        headers={"Retry-After": str(retry_after_seconds)},
    )


class LicenseAPIRateLimitMiddleware(BaseHTTPMiddleware):
    _LIMITED_PATHS = {"/api/trial/start", "/api/license/activate", "/api/license/verify"}

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self._LIMITED_PATHS:
            client_ip = request.client.host if request.client else "unknown"
            if not license_api_rate_limiter.allow(client_ip):
                return rate_limit_response()
        return await call_next(request)
