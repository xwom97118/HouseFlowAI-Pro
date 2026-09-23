"""License API 的 Pydantic request/response schema（2026-09-22 Phase
2，規格第 7、8 節）。回傳內容刻意只包含 Desktop 真正需要的欄位，不
回傳任何 internal id、hash 或其他不必要的內部資料（規格第 7 節：
「不要回傳不必要的 internal data」）。
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from server.app.services.license_service import LicenseStateResult


class TrialStartRequest(BaseModel):
    device_fingerprint: str = Field(..., min_length=8, max_length=256)
    device_name: str = Field("", max_length=128)
    app_version: str = Field("", max_length=32)


class ActivateRequest(BaseModel):
    license_key: str = Field(..., min_length=8, max_length=64)
    device_fingerprint: str = Field(..., min_length=8, max_length=256)
    device_name: str = Field("", max_length=128)
    app_version: str = Field("", max_length=32)


class VerifyRequest(BaseModel):
    license_id: str = Field(..., min_length=8, max_length=64)
    device_fingerprint: str = Field(..., min_length=8, max_length=256)
    app_version: str = Field("", max_length=32)


class LicenseStateResponse(BaseModel):
    valid: bool
    status: str
    message: str
    license_id: str | None = None
    plan: str | None = None
    is_early_bird: bool = False
    price: int | None = None
    currency: str = "TWD"
    trial_ends_at: datetime | None = None
    expires_at: datetime | None = None
    offline_valid_until: datetime | None = None
    server_time: datetime
    minimum_supported_version: str
    latest_version: str
    signature: str = ""

    @classmethod
    def from_result(cls, result: LicenseStateResult, minimum_supported_version: str, latest_version: str) -> "LicenseStateResponse":
        return cls(
            valid=result.valid,
            status=result.status,
            message=result.message,
            license_id=result.license_id,
            plan=result.plan,
            is_early_bird=result.is_early_bird,
            price=result.price,
            currency=result.currency,
            trial_ends_at=result.trial_ends_at,
            expires_at=result.expires_at,
            offline_valid_until=result.offline_valid_until,
            server_time=result.server_time,
            minimum_supported_version=minimum_supported_version,
            latest_version=latest_version,
            signature=result.signature,
        )


class ErrorResponse(BaseModel):
    detail: str
