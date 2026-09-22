"""Admin 操作稽核紀錄（2026-09-22 Phase 2，規格第 19 節）。

record() 只接受呼叫端已經過濾好的欄位快照（old_value/new_value 都是
呼叫端組好的 plain dict，這裡再 json.dumps）——刻意不接受任意物件，
逼呼叫端自己決定「這次操作真正需要記錄哪些欄位」，避免不小心把
password／完整 license key／token 等敏感值整包序列化進稽核紀錄。
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from server.app.models.license import AdminAuditLog

_FORBIDDEN_KEYS = {"password", "password_hash", "license_key", "session_token", "token", "secret"}


def _sanitize(value: dict | None) -> str | None:
    if value is None:
        return None
    safe = {k: v for k, v in value.items() if k.lower() not in _FORBIDDEN_KEYS}
    return json.dumps(safe, ensure_ascii=False, default=str)


def record(
    db: Session,
    admin_username: str,
    action: str,
    license_id: str | None = None,
    old_value: dict | None = None,
    new_value: dict | None = None,
) -> AdminAuditLog:
    entry = AdminAuditLog(
        admin_username=admin_username,
        action=action,
        license_id=license_id,
        old_value=_sanitize(old_value),
        new_value=_sanitize(new_value),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def list_recent(db: Session, limit: int = 200) -> list[AdminAuditLog]:
    return (
        db.query(AdminAuditLog)
        .order_by(AdminAuditLog.created_at.desc())
        .limit(limit)
        .all()
    )


def list_for_license(db: Session, license_id: str, limit: int = 100) -> list[AdminAuditLog]:
    return (
        db.query(AdminAuditLog)
        .filter(AdminAuditLog.license_id == license_id)
        .order_by(AdminAuditLog.created_at.desc())
        .limit(limit)
        .all()
    )
