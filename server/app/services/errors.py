from __future__ import annotations


class LicenseServerError(Exception):
    """License 相關操作失敗的基底類別。"""


class LicenseNotFoundError(LicenseServerError):
    pass


class DeviceLimitReachedError(LicenseServerError):
    pass


class TrialAlreadyUsedError(LicenseServerError):
    pass


class LicenseSuspendedError(LicenseServerError):
    pass


class LicenseRevokedError(LicenseServerError):
    pass


class DeviceNotBoundError(LicenseServerError):
    pass


class AdminAuthError(Exception):
    pass
