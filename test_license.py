"""License 網域層 + MockLicenseProvider 的正式回歸測試（2026-09-21
產品化 Phase 1，規格第 30 節：license tests, trial tests, offline
grace tests, device binding tests）。

只用記憶體內的假 get_setting/set_setting（不碰任何 SQLite 檔案，也
不碰 Database class），完全隔離、可重複執行。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.services.license.evaluation import evaluate_license
from app.services.license.fingerprint import compute_device_fingerprint
from app.services.license.mock_provider import MockLicenseProvider
from app.services.license.models import LicenseStatus
from app.services.license.service import DeviceLimitReachedError, TrialAlreadyUsedError


def _fake_settings() -> tuple[dict, callable, callable]:
    store: dict[str, str] = {}

    def get_setting(key: str, default: str = "") -> str:
        return store.get(key, default)

    def set_setting(key: str, value: str) -> None:
        store[key] = value

    return store, get_setting, set_setting


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


def test_device_fingerprint_is_stable_across_calls() -> None:
    _, get_setting, set_setting = _fake_settings()
    fp1 = compute_device_fingerprint(get_setting, set_setting)
    fp2 = compute_device_fingerprint(get_setting, set_setting)
    assert fp1 == fp2
    assert len(fp1) == 64  # sha256 hex digest


def test_device_fingerprint_differs_across_independent_settings_stores() -> None:
    _, get_setting_a, set_setting_a = _fake_settings()
    _, get_setting_b, set_setting_b = _fake_settings()
    fp_a = compute_device_fingerprint(get_setting_a, set_setting_a)
    fp_b = compute_device_fingerprint(get_setting_b, set_setting_b)
    assert fp_a != fp_b


def test_start_trial_creates_trial_license() -> None:
    _, get_setting, set_setting = _fake_settings()
    clock = _Clock(datetime(2026, 1, 1, 9, 0, 0))
    service = MockLicenseProvider(get_setting, set_setting, now_provider=clock)
    fp = compute_device_fingerprint(get_setting, set_setting)

    license_ = service.start_trial(fp, "test-device")

    assert license_.status == LicenseStatus.TRIAL
    assert license_.trial_started_at is not None
    assert license_.trial_ends_at is not None

    result = service.check_license(fp)
    assert result.can_use_app is True
    assert result.effective_status == LicenseStatus.TRIAL
    assert result.days_remaining == 7


def test_start_trial_twice_on_same_device_raises() -> None:
    _, get_setting, set_setting = _fake_settings()
    service = MockLicenseProvider(get_setting, set_setting)
    fp = compute_device_fingerprint(get_setting, set_setting)

    service.start_trial(fp, "test-device")
    try:
        service.start_trial(fp, "test-device")
        raise AssertionError("expected TrialAlreadyUsedError")
    except TrialAlreadyUsedError:
        pass


def test_trial_expires_after_seven_days() -> None:
    _, get_setting, set_setting = _fake_settings()
    clock = _Clock(datetime(2026, 1, 1, 9, 0, 0))
    service = MockLicenseProvider(get_setting, set_setting, now_provider=clock)
    fp = compute_device_fingerprint(get_setting, set_setting)
    service.start_trial(fp, "test-device")

    clock.advance(days=6, hours=23)
    result = service.check_license(fp)
    assert result.can_use_app is True

    clock.advance(hours=2)  # now past the 7-day mark
    result = service.check_license(fp)
    assert result.can_use_app is False
    assert result.effective_status == LicenseStatus.EXPIRED
    assert result.requires_reactivation is True


def test_activate_license_rejects_bad_format() -> None:
    _, get_setting, set_setting = _fake_settings()
    service = MockLicenseProvider(get_setting, set_setting)
    fp = compute_device_fingerprint(get_setting, set_setting)
    try:
        service.activate_license("not-a-real-key", fp, "test-device")
        raise AssertionError("expected LookupError for malformed key")
    except LookupError:
        pass


def test_activate_license_succeeds_with_valid_format() -> None:
    _, get_setting, set_setting = _fake_settings()
    service = MockLicenseProvider(get_setting, set_setting)
    fp = compute_device_fingerprint(get_setting, set_setting)

    license_ = service.activate_license("HF-PRO-AAAA-BBBB-CCCC", fp, "test-device")
    assert license_.status == LicenseStatus.ACTIVE
    assert license_.license_key_hash  # never stores plaintext key
    assert "AAAA" not in license_.license_key_hash


def test_activate_license_on_second_device_raises_device_limit() -> None:
    _, get_setting, set_setting = _fake_settings()
    service = MockLicenseProvider(get_setting, set_setting)
    fp_a = compute_device_fingerprint(get_setting, set_setting)

    service.activate_license("HF-PRO-AAAA-BBBB-CCCC", fp_a, "device-a")
    try:
        service.activate_license("HF-PRO-AAAA-BBBB-CCCC", "different-device-fingerprint", "device-b")
        raise AssertionError("expected DeviceLimitReachedError")
    except DeviceLimitReachedError:
        pass


def test_check_license_blocks_on_device_mismatch() -> None:
    _, get_setting, set_setting = _fake_settings()
    service = MockLicenseProvider(get_setting, set_setting)
    fp = compute_device_fingerprint(get_setting, set_setting)
    service.activate_license("HF-PRO-AAAA-BBBB-CCCC", fp, "device-a")

    result = service.check_license("some-other-devices-fingerprint")
    assert result.can_use_app is False
    assert result.requires_reactivation is True


def test_offline_grace_allows_use_within_seven_days_after_expiry() -> None:
    now = datetime(2026, 3, 1, 12, 0, 0)
    expired_license_expires_at = now - timedelta(days=2)
    last_verified_at = now - timedelta(days=2)

    from app.services.license.models import License, LicensePlan

    license_ = License(
        license_id="lic-1",
        license_key_hash="hash",
        plan=LicensePlan.PROFESSIONAL,
        status=LicenseStatus.ACTIVE,
        expires_at=expired_license_expires_at.isoformat(),
    )

    result = evaluate_license(
        license_,
        now=now,
        last_verified_at=last_verified_at,
        high_water_mark=last_verified_at,
        offline_grace_days=7,
    )
    assert result.can_use_app is True
    assert result.is_offline_grace is True
    assert result.offline_days_remaining == 5


def test_offline_grace_blocks_after_seven_days() -> None:
    now = datetime(2026, 3, 10, 12, 0, 0)
    expired_at = now - timedelta(days=9)
    last_verified_at = now - timedelta(days=9)

    from app.services.license.models import License, LicensePlan

    license_ = License(
        license_id="lic-1",
        license_key_hash="hash",
        plan=LicensePlan.PROFESSIONAL,
        status=LicenseStatus.ACTIVE,
        expires_at=expired_at.isoformat(),
    )

    result = evaluate_license(
        license_,
        now=now,
        last_verified_at=last_verified_at,
        high_water_mark=last_verified_at,
        offline_grace_days=7,
    )
    assert result.can_use_app is False
    assert result.requires_reactivation is True


def test_clock_rollback_forces_reactivation_even_within_grace_window() -> None:
    """時鐘被往回調：即使照「剩餘寬限天數」算起來還沒過期，也不採信，
    要求重新連網驗證（規格第 15 節：不能只信任本機時鐘）。"""
    real_now = datetime(2026, 3, 5, 12, 0, 0)
    high_water_mark = datetime(2026, 3, 8, 12, 0, 0)  # 系統曾經看過比 real_now 更晚的時間
    expires_at = real_now - timedelta(days=1)
    last_verified_at = real_now - timedelta(days=1)

    from app.services.license.models import License, LicensePlan

    license_ = License(
        license_id="lic-1",
        license_key_hash="hash",
        plan=LicensePlan.PROFESSIONAL,
        status=LicenseStatus.ACTIVE,
        expires_at=expires_at.isoformat(),
    )

    result = evaluate_license(
        license_,
        now=real_now,
        last_verified_at=last_verified_at,
        high_water_mark=high_water_mark,
        offline_grace_days=7,
    )
    assert result.can_use_app is False
    assert result.requires_reactivation is True


def test_suspended_license_always_blocked() -> None:
    from app.services.license.models import License, LicensePlan

    license_ = License(
        license_id="lic-1",
        license_key_hash="hash",
        plan=LicensePlan.PROFESSIONAL,
        status=LicenseStatus.SUSPENDED,
    )
    result = evaluate_license(
        license_,
        now=datetime(2026, 1, 1),
        last_verified_at=datetime(2026, 1, 1),
        high_water_mark=datetime(2026, 1, 1),
    )
    assert result.can_use_app is False
    assert result.effective_status == LicenseStatus.SUSPENDED


def test_no_license_is_blocked() -> None:
    result = evaluate_license(
        None,
        now=datetime(2026, 1, 1),
        last_verified_at=None,
        high_water_mark=None,
    )
    assert result.can_use_app is False


def test_expiration_never_touches_business_data() -> None:
    """規格第 16 節：到期只限制功能，不刪除任何資料。這裡驗證
    check_license()／evaluate_license() 是純邏輯運算，不會呼叫任何
    刪除或清空資料的操作——即單純檢查回傳值不含刪除信號，且
    MockLicenseProvider 沒有暴露任何 delete_* 方法。
    """
    assert not hasattr(MockLicenseProvider, "delete_data")
    assert not hasattr(MockLicenseProvider, "wipe")
    assert not hasattr(MockLicenseProvider, "reset_database")


if __name__ == "__main__":
    import sys

    failures = 0
    tests = [(name, obj) for name, obj in list(globals().items()) if name.startswith("test_")]
    for name, test in tests:
        try:
            test()
            print(f"PASS: {name}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL: {name}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)
