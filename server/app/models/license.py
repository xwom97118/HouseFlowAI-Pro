"""SQLAlchemy ORM 模型（2026-09-22 Phase 2）。

時間一律用 naive UTC datetime 儲存（見 server/app/timeutil.py 的
utc_now()）——SQLite 對 timezone-aware datetime 的往返支援不穩定，
所以統一存「語意上是 UTC，但欄位本身不帶 tzinfo」的值，讀寫都經過
utc_now()/確保一致，避免 SQLite ↔ 未來 PostgreSQL 遷移時的時區踩雷。

License Key 明文從來不會被寫進資料庫，只存 license_key_hash（見
server/app/security.py）。Admin session token 也是同樣的原則，只存
session_token_hash。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server.app.models.base import Base
from server.app.timeutil import utc_now


class License(Base):
    __tablename__ = "licenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    license_id: Mapped[str] = mapped_column(String(36), unique=True, index=True, nullable=False)

    # 明文 license key 從不落地；只存 hash + 顯示用的末四碼。
    license_key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    license_key_last4: Mapped[str] = mapped_column(String(4), nullable=False)

    plan: Mapped[str] = mapped_column(String(32), nullable=False, default="professional")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="trial", index=True)

    is_early_bird: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    locked_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="TWD")

    trial_started_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)

    activated_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)

    device_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    created_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False, default=utc_now, onupdate=utc_now)

    devices: Mapped[list["DeviceBinding"]] = relationship(
        "DeviceBinding", back_populates="license", cascade="all, delete-orphan"
    )


class DeviceBinding(Base):
    __tablename__ = "device_bindings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(36), unique=True, index=True, nullable=False)

    license_pk: Mapped[int] = mapped_column(ForeignKey("licenses.id"), nullable=False, index=True)
    license: Mapped["License"] = relationship("License", back_populates="devices")

    # 只存 fingerprint 的 hash，不存 Desktop 傳來的原始值本身以外的任何
    # 額外硬體資訊——Desktop 端傳來的 device_fingerprint 本身已經是
    # 「本機持久化隨機 UUID 的 sha256」（見 app/services/license/
    # fingerprint.py），這裡再雜湊一次純粹是防禦性深度，不代表 server
    # 端有能力逆推出任何真正的硬體識別資訊。
    device_fingerprint_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    device_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")

    first_activated_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False, default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False, default=utc_now)
    last_verified_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False, default=utc_now)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")  # active / released


class TrialFingerprint(Base):
    """獨立於任何一組 License 之外，單純記錄「這個裝置用過試用資格了
    嗎」——即使對應的 License 之後被刪除，這筆記錄仍然存在，防止單靠
    刪除本機資料重新安裝就能重複領取試用（規格第 6 節）。
    """

    __tablename__ = "trial_fingerprints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_fingerprint_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    first_trial_started_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False, default=utc_now)
    license_id: Mapped[str] = mapped_column(String(36), nullable=False)


class ProductSettings(Base):
    """全域商業設定——單一列（id 固定為 1）。Admin 可修改，Desktop 不得
    把這些值當成唯一權威來源寫死（規格第 13 節）。
    """

    __tablename__ = "product_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)

    current_monthly_price: Mapped[int] = mapped_column(Integer, nullable=False, default=688)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="TWD")

    trial_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    offline_grace_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)

    latest_version: Mapped[str] = mapped_column(String(32), nullable=False, default="3.4.0")
    minimum_supported_version: Mapped[str] = mapped_column(String(32), nullable=False, default="3.0.0")

    updated_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False, default=utc_now, onupdate=utc_now)


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False, default=utc_now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # 2026-09-23 Phase 3A（規格第 10 節）：登入暴力嘗試防護。
    # failed_login_count 連續失敗達到門檻時，設定 locked_until，在那
    # 之前即使密碼正確也拒絕登入——見 admin_auth_service.authenticate()。
    # 密碼登入成功會把這兩個欄位重置。
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    admin_user_id: Mapped[int] = mapped_column(ForeignKey("admin_users.id"), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False, default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    admin_username: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    license_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    # JSON 編碼的欄位快照，只記錄跟這次操作相關的欄位（例如 status、
    # expires_at），絕對不記錄：password、完整 license key、session
    # token、任何 secret（規格第 19 節）。
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False, default=utc_now, index=True)
