"""License domain model（2026-09-21 產品化 Phase 1，見
docs/PRODUCT_V1_SPEC.md 第 12～16 節）。

這裡只定義資料形狀與純邏輯（LicenseCheckResult 怎麼算出來），完全不
依賴任何特定後端（沒有 import requests、沒有任何 server URL）——
Desktop 端要能同時支援「本機 mock provider（開發／測試用）」跟「未來
真正的 HouseFlow License Cloud」，兩者都實作同一個 LicenseService
介面（見 service.py），這個模組本身不知道、也不需要知道資料實際存在
哪裡。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum


class LicensePlan(str, Enum):
    PROFESSIONAL = "professional"


class LicenseStatus(str, Enum):
    """License 本身（不考慮裝置、不考慮離線）的狀態。"""

    TRIAL = "trial"
    ACTIVE = "active"
    EXPIRED = "expired"
    SUSPENDED = "suspended"
    # 2026-09-22 Phase 2（規格第 4、24 節）：License Server 端多了
    # revoked 這個狀態（Admin 主動撤銷，永久性、比 suspended 更重）。
    # Phase 1 的 evaluate_license()／MockLicenseProvider 從來不會產生
    # 這個狀態（本機 mock 沒有「撤銷」概念），只有 HTTPLicenseProvider
    # 從真正的 License Server 收到 status="revoked" 時才會用到。
    REVOKED = "revoked"


class DeviceStatus(str, Enum):
    ACTIVE = "active"
    RELEASED = "released"  # Admin 解除綁定後


@dataclass
class License:
    """對應規格第 12 節的 License model。license_key 本身（明文）不會
    存在這個物件裡——Desktop 端只需要知道「目前這台裝置的 license 狀態」
    ，不需要、也不應該持有可以拿去別的裝置啟用的明文 key。啟用時輸入
    的 key 只在啟用當下送到 LicenseService，之後只保留
    license_key_hash 供比對／顯示用（例如結尾幾碼），不做明文保存
    （見規格第 12 節：「Admin 不需要在 database 明文保存完整 license
    key，除非 architecture 有合理安全理由」，Desktop 端比 Admin 更沒有
    理由留明文）。
    """

    license_id: str
    license_key_hash: str
    plan: LicensePlan
    status: LicenseStatus

    trial_started_at: str | None = None
    trial_ends_at: str | None = None

    activated_at: str | None = None
    expires_at: str | None = None

    is_early_bird: bool = False
    locked_price: int | None = None
    currency: str = "TWD"

    device_limit: int = 1

    created_at: str = ""
    updated_at: str = ""


@dataclass
class TrialState:
    """單一裝置的試用狀態——跟 License 分開存，因為「這台裝置用過
    試用了嗎」這個問題要在使用者還沒有任何 License 之前就能回答（見
    規格第 14 節：Trial 防濫用不能只靠刪 SQLite 重裝）。
    """

    device_fingerprint: str
    trial_started_at: str
    trial_ends_at: str
    used: bool = True


@dataclass
class DeviceBinding:
    device_id: str
    license_id: str
    device_fingerprint: str
    device_name: str
    first_activated_at: str
    last_seen_at: str
    last_license_check_at: str
    status: DeviceStatus = DeviceStatus.ACTIVE


@dataclass
class LicenseCheckResult:
    """LicenseService.check_license() 的回傳值——UI 只需要看這個物件
    就知道該顯示什麼、該不該擋下主要功能，不需要自己重算到期日／
    offline grace 邏輯。
    """

    can_use_app: bool
    effective_status: LicenseStatus
    message: str

    days_remaining: int | None = None
    requires_reactivation: bool = False
    is_offline_grace: bool = False
    offline_days_remaining: int | None = None

    # 2026-09-22 Phase 2（規格第 25 節）：只有 HTTPLicenseProvider 真的
    # 連上 License Server 時才會填這兩個值（來自 ProductSettings，不是
    # Desktop 寫死）；MockLicenseProvider／離線 fallback 都不知道版本
    # 資訊，維持 None，UI 端看到 None 就不顯示版本相關訊息。
    latest_version: str | None = None
    minimum_supported_version: str | None = None

    @classmethod
    def blocked(
        cls,
        status: LicenseStatus,
        message: str,
        latest_version: str | None = None,
        minimum_supported_version: str | None = None,
    ) -> "LicenseCheckResult":
        return cls(
            can_use_app=False,
            effective_status=status,
            message=message,
            requires_reactivation=True,
            latest_version=latest_version,
            minimum_supported_version=minimum_supported_version,
        )

    @classmethod
    def allowed(
        cls,
        status: LicenseStatus,
        message: str,
        days_remaining: int | None = None,
        is_offline_grace: bool = False,
        offline_days_remaining: int | None = None,
        latest_version: str | None = None,
        minimum_supported_version: str | None = None,
    ) -> "LicenseCheckResult":
        return cls(
            can_use_app=True,
            effective_status=status,
            message=message,
            days_remaining=days_remaining,
            is_offline_grace=is_offline_grace,
            offline_days_remaining=offline_days_remaining,
            latest_version=latest_version,
            minimum_supported_version=minimum_supported_version,
        )


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def days_between(now: datetime, target: datetime) -> int:
    """無條件進位到「還剩幾天」，符合使用者直覺（還剩 0.1 天也算
    「還有 1 天」，不會顯示成 0 天嚇到人）。"""
    delta = target - now
    if delta.total_seconds() <= 0:
        return 0
    return max(1, int(delta.total_seconds() // 86400) + (1 if delta.total_seconds() % 86400 else 0))
