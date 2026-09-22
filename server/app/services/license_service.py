"""License Server 核心商業邏輯（2026-09-22 Phase 2）。

這裡是唯一真正操作 License / DeviceBinding / TrialFingerprint 資料表
的地方——API 層（server/app/api/）跟 Admin 層（server/app/admin_ui/）
都只透過這裡的函式操作資料，不直接寫 SQLAlchemy query，確保「License
是誰簽發的、狀態怎麼變」永遠只有一套邏輯。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy.orm import Session

from server.app.models.license import DeviceBinding, License, TrialFingerprint
from server.app.security import (
    generate_license_key,
    hash_device_fingerprint,
    hash_license_key,
    license_key_last4,
)
from server.app.services.errors import (
    DeviceLimitReachedError,
    DeviceNotBoundError,
    LicenseNotFoundError,
    LicenseRevokedError,
    LicenseSuspendedError,
    TrialAlreadyUsedError,
)
from server.app.services.product_settings_service import get_product_settings
from server.app.timeutil import utc_now

ACTIVE_STATUSES = {"trial", "active"}


@dataclass
class LicenseStateResult:
    """API 回傳給 Desktop 的「目前授權狀態」——server 是 authority，
    Desktop 端只把這個結果快取起來當離線時的 fallback 依據。
    """

    valid: bool
    status: str  # trial / active / expired / suspended / revoked
    message: str
    license_id: str | None = None
    plan: str | None = None
    is_early_bird: bool = False
    price: int | None = None
    currency: str = "TWD"
    trial_ends_at: datetime | None = None
    expires_at: datetime | None = None
    offline_valid_until: datetime | None = None
    server_time: datetime = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.server_time is None:
            self.server_time = utc_now()


def compute_effective_status(license_row: License, now: datetime | None = None) -> str:
    """`License.status` 這個欄位只在 Admin 明確操作時才會改變
    （create/suspend/resume/revoke）——單純時間到了 expires_at/
    trial_ends_at 並不會自動把這個欄位改成 "expired"（避免需要一支
    背景排程去掃全部 License），實際的到期判斷永遠是即時算的（見
    `_compute_status_result()`）。

    但這代表任何直接顯示 `license_row.status` 的畫面（Admin 清單/
    詳細頁）都會誤導管理者——一組早就過了 expires_at 的 License，
    `status` 欄位可能還停在 "active"。這個函式回傳「現在看起來」的
    真實狀態，只給畫面顯示用；`license_row.status` 本身完全不變，
    Admin 操作按鈕（Suspend/Resume/Revoke 的顯示邏輯）仍然照舊看
    Admin 自己設定過的旗標，跟這裡的「日期到了沒」是兩個獨立的概念。
    """
    now = now or utc_now()

    if license_row.status in ("suspended", "revoked"):
        return license_row.status
    if license_row.status == "trial":
        if license_row.trial_ends_at is not None and now >= license_row.trial_ends_at:
            return "expired"
        return "trial"
    if license_row.status == "active":
        if license_row.expires_at is not None and now >= license_row.expires_at:
            return "expired"
        return "active"
    return license_row.status


def _effective_price(license_row: License, current_monthly_price: int) -> int:
    if license_row.is_early_bird and license_row.locked_price is not None:
        return license_row.locked_price
    return current_monthly_price


def _compute_status_result(db: Session, license_row: License, device: DeviceBinding | None) -> LicenseStateResult:
    settings = get_product_settings(db)
    now = utc_now()
    price = _effective_price(license_row, settings.current_monthly_price)

    offline_valid_until = None
    if device is not None:
        offline_valid_until = device.last_verified_at + timedelta(days=settings.offline_grace_days)

    if license_row.status == "revoked":
        return LicenseStateResult(
            valid=False,
            status="revoked",
            message="這組授權已被撤銷，請聯絡 HouseFlow。",
            license_id=license_row.license_id,
            plan=license_row.plan,
            is_early_bird=license_row.is_early_bird,
            price=price,
            currency=license_row.currency,
        )

    if license_row.status == "suspended":
        return LicenseStateResult(
            valid=False,
            status="suspended",
            message="授權目前已暫停，請聯絡 HouseFlow。",
            license_id=license_row.license_id,
            plan=license_row.plan,
            is_early_bird=license_row.is_early_bird,
            price=price,
            currency=license_row.currency,
            trial_ends_at=license_row.trial_ends_at,
            expires_at=license_row.expires_at,
            offline_valid_until=offline_valid_until,
        )

    if license_row.status == "trial":
        if license_row.trial_ends_at is not None and now >= license_row.trial_ends_at:
            return LicenseStateResult(
                valid=False,
                status="expired",
                message="7 天免費試用已結束，請輸入 License Key 或訂閱 HouseFlow Professional。",
                license_id=license_row.license_id,
                plan=license_row.plan,
                trial_ends_at=license_row.trial_ends_at,
            )
        return LicenseStateResult(
            valid=True,
            status="trial",
            message="試用中。",
            license_id=license_row.license_id,
            plan=license_row.plan,
            is_early_bird=license_row.is_early_bird,
            price=price,
            currency=license_row.currency,
            trial_ends_at=license_row.trial_ends_at,
            offline_valid_until=offline_valid_until,
        )

    if license_row.status == "active":
        if license_row.expires_at is not None and now >= license_row.expires_at:
            return LicenseStateResult(
                valid=False,
                status="expired",
                message="HouseFlow 訂閱已到期，請續訂或重新驗證。",
                license_id=license_row.license_id,
                plan=license_row.plan,
                is_early_bird=license_row.is_early_bird,
                price=price,
                currency=license_row.currency,
                expires_at=license_row.expires_at,
            )
        return LicenseStateResult(
            valid=True,
            status="active",
            message="HouseFlow Professional 使用中。",
            license_id=license_row.license_id,
            plan=license_row.plan,
            is_early_bird=license_row.is_early_bird,
            price=price,
            currency=license_row.currency,
            expires_at=license_row.expires_at,
            offline_valid_until=offline_valid_until,
        )

    # status == "expired"（已經明確被標記過期，例如 admin 手動操作）
    return LicenseStateResult(
        valid=False,
        status="expired",
        message="HouseFlow 訂閱已到期，請續訂或重新驗證。",
        license_id=license_row.license_id,
        plan=license_row.plan,
        expires_at=license_row.expires_at,
    )


# ---------------------------------------------------------------------------
# Trial
# ---------------------------------------------------------------------------


def start_trial(db: Session, device_fingerprint: str, device_name: str, app_version: str = "") -> LicenseStateResult:
    fp_hash = hash_device_fingerprint(device_fingerprint)

    existing_trial = db.query(TrialFingerprint).filter_by(device_fingerprint_hash=fp_hash).first()
    if existing_trial is not None:
        raise TrialAlreadyUsedError("這台裝置已經使用過免費試用。")

    settings = get_product_settings(db)
    now = utc_now()
    trial_ends = now + timedelta(days=settings.trial_days)

    # Trial 內部仍然需要一組 key 才能符合 license_key_hash 的
    # NOT NULL/UNIQUE 約束，但這組 key 永遠不會顯示或回傳給使用者
    # ——試用流程本來就不需要使用者輸入/保管任何 key。
    internal_key = generate_license_key()

    license_row = License(
        license_id=str(uuid4()),
        license_key_hash=hash_license_key(internal_key),
        license_key_last4=license_key_last4(internal_key),
        plan="professional",
        status="trial",
        trial_started_at=now,
        trial_ends_at=trial_ends,
        device_limit=1,
    )
    db.add(license_row)
    db.flush()

    device = DeviceBinding(
        device_id=str(uuid4()),
        license_pk=license_row.id,
        device_fingerprint_hash=fp_hash,
        device_name=device_name,
        first_activated_at=now,
        last_seen_at=now,
        last_verified_at=now,
        status="active",
    )
    db.add(device)
    db.add(TrialFingerprint(device_fingerprint_hash=fp_hash, first_trial_started_at=now, license_id=license_row.license_id))
    db.commit()
    db.refresh(license_row)

    return _compute_status_result(db, license_row, device)


# ---------------------------------------------------------------------------
# Activation
# ---------------------------------------------------------------------------


def activate_license(
    db: Session,
    license_key: str,
    device_fingerprint: str,
    device_name: str,
    app_version: str = "",
) -> LicenseStateResult:
    key_hash = hash_license_key(license_key)
    license_row = db.query(License).filter_by(license_key_hash=key_hash).first()
    if license_row is None:
        raise LicenseNotFoundError("License Key 不存在，請確認輸入是否正確。")

    if license_row.status == "revoked":
        raise LicenseRevokedError("這組授權已被撤銷，請聯絡 HouseFlow。")
    if license_row.status == "suspended":
        raise LicenseSuspendedError("授權目前已暫停，請聯絡 HouseFlow。")

    fp_hash = hash_device_fingerprint(device_fingerprint)
    now = utc_now()

    device = (
        db.query(DeviceBinding)
        .filter_by(license_pk=license_row.id, device_fingerprint_hash=fp_hash)
        .first()
    )

    if device is None:
        active_count = (
            db.query(DeviceBinding)
            .filter_by(license_pk=license_row.id, status="active")
            .count()
        )
        if active_count >= license_row.device_limit:
            raise DeviceLimitReachedError(
                "這組 License 的裝置數已達上限，請先請 Admin 解除舊裝置的綁定。"
            )
        device = DeviceBinding(
            device_id=str(uuid4()),
            license_pk=license_row.id,
            device_fingerprint_hash=fp_hash,
            device_name=device_name,
            first_activated_at=now,
            last_seen_at=now,
            last_verified_at=now,
            status="active",
        )
        db.add(device)
    else:
        if device.status == "released":
            active_count = (
                db.query(DeviceBinding)
                .filter_by(license_pk=license_row.id, status="active")
                .count()
            )
            if active_count >= license_row.device_limit:
                raise DeviceLimitReachedError(
                    "這組 License 的裝置數已達上限，請先請 Admin 解除舊裝置的綁定。"
                )
            device.status = "active"
        device.last_seen_at = now
        device.last_verified_at = now
        if device_name:
            device.device_name = device_name

    if license_row.activated_at is None:
        license_row.activated_at = now
    if license_row.status == "trial":
        license_row.status = "active"

    db.commit()
    db.refresh(license_row)

    return _compute_status_result(db, license_row, device)


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def verify_license(db: Session, license_id: str, device_fingerprint: str, app_version: str = "") -> LicenseStateResult:
    license_row = db.query(License).filter_by(license_id=license_id).first()
    if license_row is None:
        return LicenseStateResult(valid=False, status="expired", message="找不到這組授權，請重新啟用。")

    fp_hash = hash_device_fingerprint(device_fingerprint)
    device = (
        db.query(DeviceBinding)
        .filter_by(license_pk=license_row.id, device_fingerprint_hash=fp_hash, status="active")
        .first()
    )
    if device is None:
        raise DeviceNotBoundError("這台裝置未跟這組授權綁定，請重新啟用。")

    now = utc_now()
    device.last_seen_at = now
    device.last_verified_at = now
    db.commit()
    db.refresh(license_row)

    return _compute_status_result(db, license_row, device)


def get_license_by_id(db: Session, license_id: str) -> License | None:
    return db.query(License).filter_by(license_id=license_id).first()
