"""Admin 對 License 的管理操作（2026-09-22 Phase 2，規格第 16～18
節）。每個會改變 License 狀態的函式都會呼叫 audit_service.record()
留下稽核紀錄。這裡完全不碰任何 Property／CRM／Facebook 相關資料表
——Admin 是 License Control Plane，不是使用者業務資料的監看後台。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from server.app.models.license import DeviceBinding, License
from server.app.security import generate_license_key, hash_license_key, license_key_last4
from server.app.services import audit_service
from server.app.services.errors import LicenseNotFoundError
from server.app.timeutil import utc_now
from uuid import uuid4


@dataclass
class CreateLicenseResult:
    license: License
    plaintext_key: str


def create_license(
    db: Session,
    admin_username: str,
    plan: str = "professional",
    is_early_bird: bool = False,
    duration_days: int = 30,
    device_limit: int = 1,
) -> CreateLicenseResult:
    from server.app.services.product_settings_service import get_product_settings

    settings = get_product_settings(db)
    now = utc_now()
    plaintext_key = generate_license_key()

    license_row = License(
        license_id=str(uuid4()),
        license_key_hash=hash_license_key(plaintext_key),
        license_key_last4=license_key_last4(plaintext_key),
        plan=plan,
        status="active",
        is_early_bird=is_early_bird,
        locked_price=settings.current_monthly_price if is_early_bird else None,
        currency=settings.currency,
        activated_at=now,
        expires_at=now + timedelta(days=duration_days),
        device_limit=device_limit,
    )
    db.add(license_row)
    db.commit()
    db.refresh(license_row)

    audit_service.record(
        db,
        admin_username,
        action="create_license",
        license_id=license_row.license_id,
        new_value={
            "plan": plan,
            "is_early_bird": is_early_bird,
            "locked_price": license_row.locked_price,
            "duration_days": duration_days,
            "device_limit": device_limit,
            "license_key_last4": license_row.license_key_last4,
        },
    )

    return CreateLicenseResult(license=license_row, plaintext_key=plaintext_key)


def _require_license(db: Session, license_id: str) -> License:
    license_row = db.query(License).filter_by(license_id=license_id).first()
    if license_row is None:
        raise LicenseNotFoundError(f"找不到 license_id={license_id}")
    return license_row


def extend_license(db: Session, admin_username: str, license_id: str, days: int) -> License:
    license_row = _require_license(db, license_id)
    old_expires = license_row.expires_at

    now = utc_now()
    base = license_row.expires_at if (license_row.expires_at and license_row.expires_at > now) else now
    license_row.expires_at = base + timedelta(days=days)
    if license_row.status in ("expired",):
        license_row.status = "active"

    db.commit()
    db.refresh(license_row)

    audit_service.record(
        db,
        admin_username,
        action="extend_license",
        license_id=license_id,
        old_value={"expires_at": old_expires},
        new_value={"expires_at": license_row.expires_at, "days": days},
    )
    return license_row


def suspend_license(db: Session, admin_username: str, license_id: str) -> License:
    license_row = _require_license(db, license_id)
    old_status = license_row.status
    license_row.status = "suspended"
    db.commit()
    db.refresh(license_row)

    audit_service.record(
        db, admin_username, action="suspend_license", license_id=license_id,
        old_value={"status": old_status}, new_value={"status": "suspended"},
    )
    return license_row


def resume_license(db: Session, admin_username: str, license_id: str) -> License:
    license_row = _require_license(db, license_id)
    old_status = license_row.status
    now = utc_now()
    new_status = "active" if (license_row.expires_at is None or license_row.expires_at > now) else "expired"
    license_row.status = new_status
    db.commit()
    db.refresh(license_row)

    audit_service.record(
        db, admin_username, action="resume_license", license_id=license_id,
        old_value={"status": old_status}, new_value={"status": new_status},
    )
    return license_row


def revoke_license(db: Session, admin_username: str, license_id: str) -> License:
    license_row = _require_license(db, license_id)
    old_status = license_row.status
    license_row.status = "revoked"
    db.commit()
    db.refresh(license_row)

    audit_service.record(
        db, admin_username, action="revoke_license", license_id=license_id,
        old_value={"status": old_status}, new_value={"status": "revoked"},
    )
    return license_row


def set_early_bird(db: Session, admin_username: str, license_id: str, enabled: bool) -> License:
    from server.app.services.product_settings_service import get_product_settings

    license_row = _require_license(db, license_id)
    old_value = {"is_early_bird": license_row.is_early_bird, "locked_price": license_row.locked_price}

    license_row.is_early_bird = enabled
    if enabled and license_row.locked_price is None:
        settings = get_product_settings(db)
        license_row.locked_price = settings.current_monthly_price
    if not enabled:
        license_row.locked_price = None

    db.commit()
    db.refresh(license_row)

    audit_service.record(
        db, admin_username, action="set_early_bird", license_id=license_id,
        old_value=old_value,
        new_value={"is_early_bird": license_row.is_early_bird, "locked_price": license_row.locked_price},
    )
    return license_row


def set_expiration(db: Session, admin_username: str, license_id: str, expires_at) -> License:
    license_row = _require_license(db, license_id)
    old_expires = license_row.expires_at
    license_row.expires_at = expires_at
    db.commit()
    db.refresh(license_row)

    audit_service.record(
        db, admin_username, action="set_expiration", license_id=license_id,
        old_value={"expires_at": old_expires}, new_value={"expires_at": expires_at},
    )
    return license_row


def deactivate_device(db: Session, admin_username: str, license_id: str, device_id: str) -> DeviceBinding:
    license_row = _require_license(db, license_id)
    device = (
        db.query(DeviceBinding)
        .filter_by(license_pk=license_row.id, device_id=device_id)
        .first()
    )
    if device is None:
        raise LicenseNotFoundError(f"找不到 device_id={device_id}")

    old_status = device.status
    device.status = "released"
    db.commit()
    db.refresh(device)

    audit_service.record(
        db, admin_username, action="deactivate_device", license_id=license_id,
        old_value={"device_id": device_id, "status": old_status},
        new_value={"device_id": device_id, "status": "released"},
    )
    return device


def search_licenses(db: Session, query: str = "", status: str = "", limit: int = 200) -> list[License]:
    """`status` 篩選用「有效狀態」判斷（見
    license_service.compute_effective_status()），不是直接比對
    `License.status` 這個欄位本身——一組 `status="active"` 但
    `expires_at` 已經過去的 License，實際上早就是「已到期」，搜尋/
    篩選「已到期」時應該要能找到它，篩選「使用中」時則不應該再出現。
    """
    from server.app.services.license_service import compute_effective_status
    from server.app.timeutil import utc_now

    q = db.query(License)
    if query:
        like = f"%{query}%"
        q = q.outerjoin(DeviceBinding, DeviceBinding.license_pk == License.id).filter(
            or_(
                License.license_id.like(like),
                License.license_key_last4.like(like),
                DeviceBinding.device_name.like(like),
            )
        ).distinct()

    rows = q.order_by(License.created_at.desc()).all()

    if status:
        now = utc_now()
        rows = [row for row in rows if compute_effective_status(row, now) == status]

    return rows[:limit]


@dataclass
class DashboardCounts:
    total: int
    active: int
    trial: int
    expiring_soon: int
    expired: int
    suspended: int
    revoked: int


def dashboard_counts(db: Session, expiring_soon_days: int = 7) -> DashboardCounts:
    now = utc_now()
    soon = now + timedelta(days=expiring_soon_days)

    all_licenses = db.query(License).all()
    total = len(all_licenses)
    active = sum(1 for l in all_licenses if l.status == "active" and (l.expires_at is None or l.expires_at > now))
    trial = sum(1 for l in all_licenses if l.status == "trial" and (l.trial_ends_at is None or l.trial_ends_at > now))
    expiring_soon = sum(
        1 for l in all_licenses
        if l.status == "active" and l.expires_at is not None and now < l.expires_at <= soon
    )
    expired = sum(
        1 for l in all_licenses
        if l.status == "expired"
        or (l.status == "active" and l.expires_at is not None and l.expires_at <= now)
        or (l.status == "trial" and l.trial_ends_at is not None and l.trial_ends_at <= now)
    )
    suspended = sum(1 for l in all_licenses if l.status == "suspended")
    revoked = sum(1 for l in all_licenses if l.status == "revoked")

    return DashboardCounts(
        total=total, active=active, trial=trial, expiring_soon=expiring_soon,
        expired=expired, suspended=suspended, revoked=revoked,
    )
