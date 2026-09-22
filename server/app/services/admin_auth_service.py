"""Admin 帳號認證（2026-09-22 Phase 2，規格第 14 節）。

沒有任何預設帳密——第一個 Admin 帳號必須透過明確的 bootstrap 指令
（見 server/bootstrap_admin.py）建立，密碼只透過環境變數或互動輸入
傳入，絕對不會 commit 進原始碼。
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from server.app.config import get_settings
from server.app.models.license import AdminSession, AdminUser
from server.app.security import generate_session_token, hash_password, hash_session_token, verify_password
from server.app.services.errors import AdminAuthError
from server.app.timeutil import utc_now


def create_admin_user(db: Session, username: str, password: str) -> AdminUser:
    username = username.strip()
    if not username:
        raise AdminAuthError("使用者名稱不能是空白。")
    if len(password) < 12:
        raise AdminAuthError("密碼長度至少需要 12 個字元。")

    existing = db.query(AdminUser).filter_by(username=username).first()
    if existing is not None:
        raise AdminAuthError(f"帳號 {username} 已經存在。")

    admin = AdminUser(username=username, password_hash=hash_password(password), is_active=True)
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


def authenticate(db: Session, username: str, password: str) -> AdminUser:
    admin = db.query(AdminUser).filter_by(username=username.strip()).first()
    if admin is None or not admin.is_active:
        raise AdminAuthError("帳號或密碼不正確。")
    if not verify_password(password, admin.password_hash):
        raise AdminAuthError("帳號或密碼不正確。")

    admin.last_login_at = utc_now()
    db.commit()
    return admin


def create_session(db: Session, admin: AdminUser) -> str:
    settings = get_settings()
    token = generate_session_token()
    session = AdminSession(
        session_token_hash=hash_session_token(token),
        admin_user_id=admin.id,
        expires_at=utc_now() + timedelta(hours=settings.admin_session_ttl_hours),
    )
    db.add(session)
    db.commit()
    return token


def resolve_session(db: Session, token: str) -> AdminUser | None:
    if not token:
        return None
    token_hash = hash_session_token(token)
    session = db.query(AdminSession).filter_by(session_token_hash=token_hash).first()
    if session is None:
        return None
    if session.expires_at <= utc_now():
        return None
    admin = db.get(AdminUser, session.admin_user_id)
    if admin is None or not admin.is_active:
        return None
    return admin


def invalidate_session(db: Session, token: str) -> None:
    if not token:
        return
    token_hash = hash_session_token(token)
    db.query(AdminSession).filter_by(session_token_hash=token_hash).delete()
    db.commit()


def has_any_admin(db: Session) -> bool:
    return db.query(AdminUser).first() is not None
