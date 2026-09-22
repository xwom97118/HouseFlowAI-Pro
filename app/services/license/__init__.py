from __future__ import annotations

from app.services.license.evaluation import evaluate_license
from app.services.license.fingerprint import compute_device_fingerprint
from app.services.license.http_provider import DEFAULT_BASE_URL, HTTPLicenseProvider
from app.services.license.mock_provider import MockLicenseProvider
from app.services.license.models import (
    DeviceBinding,
    DeviceStatus,
    License,
    LicenseCheckResult,
    LicensePlan,
    LicenseStatus,
    TrialState,
)
from app.services.license.service import (
    DeviceLimitReachedError,
    LicenseError,
    LicenseService,
    TrialAlreadyUsedError,
)

__all__ = [
    "DEFAULT_BASE_URL",
    "DeviceBinding",
    "DeviceLimitReachedError",
    "DeviceStatus",
    "HTTPLicenseProvider",
    "License",
    "LicenseCheckResult",
    "LicenseError",
    "LicensePlan",
    "LicenseService",
    "LicenseStatus",
    "MockLicenseProvider",
    "TrialAlreadyUsedError",
    "TrialState",
    "compute_device_fingerprint",
    "evaluate_license",
]
