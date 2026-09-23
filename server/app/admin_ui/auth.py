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
from server.app.csrf import generate_csrf_token, verify_csrf_token
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


def get_session_token(request: Request) -> str:
    return request.cookies.get(SESSION_COOKIE_NAME, "")


def get_current_admin(request: Request, db: Session) -> AdminUser | None:
    token = get_session_token(request)
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


def csrf_token_for(request: Request) -> str:
    """給 GET route 渲染表單時用——把這個值放進 hidden input，POST 時
    用 require_admin_and_csrf() 驗證。"""
    return generate_csrf_token(get_session_token(request))


def require_admin_and_csrf(request: Request, db: Session, submitted_csrf_token: str) -> AdminUser | RedirectResponse:
    """POST route 專用：先確認有登入，再驗證 CSRF token 是否跟目前
    session 對得上。CSRF 驗證失敗一律當成「沒有有效 session」處理
    （導回登入頁），不特別回傳「CSRF 錯誤」的訊息給呼叫端——這樣不會
    洩漏「你的 session 存在，只是 CSRF token 不對」這種對攻擊者有用
    的資訊。
    """
    admin = require_admin(request, db)
    if isinstance(admin, RedirectResponse):
        return admin
    session_token = get_session_token(request)
    if not verify_csrf_token(session_token, submitted_csrf_token):
        return RedirectResponse(url="/admin/login?err=請重新登入後再試一次", status_code=303)
    return admin
