"""Admin UI 的 session cookie 認證（2026-09-22 Phase 2）。

Session token 本身存在 HttpOnly cookie（瀏覽器端 JS 讀不到），server
只保存它的 hash（見 security.hash_session_token）——就算資料庫外洩，
攻擊者也不能直接拿 hash 冒充登入中的 session。
"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from server.app.config import get_settings
from server.app.models.license import AdminUser
from server.app.services.admin_auth_service import resolve_session

SESSION_COOKIE_NAME = "houseflow_admin_session"


def set_session_cookie(response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.require_https,
        max_age=settings.admin_session_ttl_hours * 3600,
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME)


def get_current_admin(request: Request, db: Session) -> AdminUser | None:
    token = request.cookies.get(SESSION_COOKIE_NAME, "")
    return resolve_session(db, token)


def require_admin(request: Request, db: Session) -> AdminUser | RedirectResponse:
    """回傳目前登入的 AdminUser，或（沒登入/session 過期時）一個導去
    登入頁的 RedirectResponse——呼叫端用
    `admin = require_admin(...); if isinstance(admin, RedirectResponse): return admin`
    這個明確的模式，不依賴 FastAPI exception-as-redirect 的行為細節。
    """
    admin = get_current_admin(request, db)
    if admin is None:
        next_path = request.url.path
        return RedirectResponse(url=f"/admin/login?next={next_path}", status_code=303)
    return admin
