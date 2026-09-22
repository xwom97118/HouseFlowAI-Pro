"""License Server 對外 API（Desktop 端呼叫，2026-09-22 Phase 2，規格
第 7、8、9 節）。這裡完全不接收、不儲存任何 Property／CRM／Facebook
相關資料——request body 只有 device_fingerprint／device_name／
app_version／license_key（規格第 27 節：Privacy）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from server.app.database import get_db
from server.app.schemas.license import ActivateRequest, LicenseStateResponse, TrialStartRequest, VerifyRequest
from server.app.services import license_service
from server.app.services.errors import (
    DeviceLimitReachedError,
    DeviceNotBoundError,
    LicenseNotFoundError,
    LicenseRevokedError,
    LicenseSuspendedError,
    TrialAlreadyUsedError,
)
from server.app.services.product_settings_service import get_product_settings

router = APIRouter(prefix="", tags=["license"])


def _respond(db: Session, result: license_service.LicenseStateResult) -> LicenseStateResponse:
    settings = get_product_settings(db)
    return LicenseStateResponse.from_result(
        result,
        minimum_supported_version=settings.minimum_supported_version,
        latest_version=settings.latest_version,
    )


@router.post("/trial/start", response_model=LicenseStateResponse)
def trial_start(payload: TrialStartRequest, db: Session = Depends(get_db)) -> LicenseStateResponse:
    try:
        result = license_service.start_trial(db, payload.device_fingerprint, payload.device_name, payload.app_version)
    except TrialAlreadyUsedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _respond(db, result)


@router.post("/license/activate", response_model=LicenseStateResponse)
def license_activate(payload: ActivateRequest, db: Session = Depends(get_db)) -> LicenseStateResponse:
    try:
        result = license_service.activate_license(
            db, payload.license_key, payload.device_fingerprint, payload.device_name, payload.app_version
        )
    except LicenseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (LicenseRevokedError, LicenseSuspendedError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except DeviceLimitReachedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _respond(db, result)


@router.post("/license/verify", response_model=LicenseStateResponse)
def license_verify(payload: VerifyRequest, db: Session = Depends(get_db)) -> LicenseStateResponse:
    try:
        result = license_service.verify_license(db, payload.license_id, payload.device_fingerprint, payload.app_version)
    except DeviceNotBoundError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return _respond(db, result)
