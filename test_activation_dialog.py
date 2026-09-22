"""ActivationDialog / LicenseInfoPanel 的正式回歸測試（2026-09-22
產品化 Phase 1.1）。

背景：稍早一次 ad-hoc（非正式、沒有存成 test_*.py）的 smoke test 直接
呼叫了 ActivationDialog.activate_key()，但沒有 mock 掉
QMessageBox.information——啟用成功時 activate_key() 內部會彈出一個
真正的、阻塞的 QMessageBox，在 headless 背景執行環境下卡住等不到人去
點掉，最後被判定逾時失敗。這不是 ActivationDialog 本身的邏輯 bug，
是測試方式的問題（跟 Phase 1 round 修 test_schedule_ux.py 遇到的
QMessageBox.critical 阻塞問題是同一種類型）——正確做法是 mock 掉
QMessageBox，驗證「有沒有正確彈出提示」而不是真的卡住等使用者點擊。

這裡完整覆蓋：dialog construction、trial 開始、license key 啟用、
device mismatch、以及 LicenseInfoPanel 在 Trial / Active / Expired /
Suspended / Offline-grace 五種狀態下的顯示文字。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest import mock

from PySide6.QtWidgets import QApplication, QStackedWidget

from app.services.license import LicenseStatus, MockLicenseProvider, compute_device_fingerprint
from app.widgets.license_widgets import ActivationDialog, LicenseInfoPanel

_app = QApplication.instance() or QApplication([])


def _fake_settings() -> tuple[dict, callable, callable]:
    store: dict[str, str] = {}

    def get_setting(key: str, default: str = "") -> str:
        return store.get(key, default)

    def set_setting(key: str, value: str) -> None:
        store[key] = value

    return store, get_setting, set_setting


def test_activation_dialog_constructs_with_two_pages() -> None:
    _, get_setting, set_setting = _fake_settings()
    service = MockLicenseProvider(get_setting, set_setting)
    dialog = ActivationDialog(service, get_setting, set_setting)
    try:
        stack = dialog.findChild(QStackedWidget)
        assert stack.count() == 2
        assert stack.currentIndex() == 0
    finally:
        dialog.close()


def test_activation_dialog_start_trial_success_shows_info_and_accepts() -> None:
    _, get_setting, set_setting = _fake_settings()
    service = MockLicenseProvider(get_setting, set_setting)
    dialog = ActivationDialog(service, get_setting, set_setting)
    try:
        with mock.patch("app.widgets.license_widgets.QMessageBox.information") as mock_info:
            with mock.patch.object(dialog, "accept") as mock_accept:
                dialog.start_trial()
                assert mock_info.called
                assert mock_accept.called

        license_ = service.get_current_license()
        assert license_ is not None
        assert license_.status == LicenseStatus.TRIAL
    finally:
        dialog.close()


def test_activation_dialog_start_trial_twice_shows_warning_and_does_not_accept() -> None:
    _, get_setting, set_setting = _fake_settings()
    service = MockLicenseProvider(get_setting, set_setting)
    fp = compute_device_fingerprint(get_setting, set_setting)
    service.start_trial(fp, "existing-device")

    dialog = ActivationDialog(service, get_setting, set_setting)
    try:
        with mock.patch("app.widgets.license_widgets.QMessageBox.warning") as mock_warning:
            with mock.patch.object(dialog, "accept") as mock_accept:
                dialog.start_trial()
                assert mock_warning.called
                assert not mock_accept.called
    finally:
        dialog.close()


def test_activation_dialog_activate_key_empty_shows_warning() -> None:
    _, get_setting, set_setting = _fake_settings()
    service = MockLicenseProvider(get_setting, set_setting)
    dialog = ActivationDialog(service, get_setting, set_setting)
    try:
        dialog.key_input.setText("")
        with mock.patch("app.widgets.license_widgets.QMessageBox.warning") as mock_warning:
            with mock.patch.object(dialog, "accept") as mock_accept:
                dialog.activate_key()
                assert mock_warning.called
                assert not mock_accept.called
    finally:
        dialog.close()


def test_activation_dialog_activate_key_success_shows_info_and_accepts() -> None:
    _, get_setting, set_setting = _fake_settings()
    service = MockLicenseProvider(get_setting, set_setting)
    dialog = ActivationDialog(service, get_setting, set_setting)
    try:
        dialog.key_input.setText("HF-PRO-AAAA-BBBB-CCCC")
        with mock.patch("app.widgets.license_widgets.QMessageBox.information") as mock_info:
            with mock.patch.object(dialog, "accept") as mock_accept:
                dialog.activate_key()
                assert mock_info.called
                assert mock_accept.called

        license_ = service.get_current_license()
        assert license_.status == LicenseStatus.ACTIVE
    finally:
        dialog.close()


def test_activation_dialog_activate_key_bad_format_shows_critical() -> None:
    _, get_setting, set_setting = _fake_settings()
    service = MockLicenseProvider(get_setting, set_setting)
    dialog = ActivationDialog(service, get_setting, set_setting)
    try:
        dialog.key_input.setText("totally-not-valid")
        with mock.patch("app.widgets.license_widgets.QMessageBox.critical") as mock_critical:
            with mock.patch.object(dialog, "accept") as mock_accept:
                dialog.activate_key()
                assert mock_critical.called
                assert not mock_accept.called
    finally:
        dialog.close()


def test_activation_dialog_device_mismatch_shows_critical() -> None:
    _, get_setting, set_setting = _fake_settings()
    service = MockLicenseProvider(get_setting, set_setting)
    fp = compute_device_fingerprint(get_setting, set_setting)
    service.activate_license("HF-PRO-AAAA-BBBB-CCCC", fp, "device-a")

    # 第二個 dialog 代表「另一台裝置」嘗試啟用同一組 key —— 用另一組
    # 完全獨立的假 settings store 模擬不同裝置的 device fingerprint。
    _, get_setting_b, set_setting_b = _fake_settings()
    dialog_b = ActivationDialog(service, get_setting_b, set_setting_b)
    try:
        dialog_b.key_input.setText("HF-PRO-AAAA-BBBB-CCCC")
        with mock.patch("app.widgets.license_widgets.QMessageBox.critical") as mock_critical:
            with mock.patch.object(dialog_b, "accept") as mock_accept:
                dialog_b.activate_key()
                assert mock_critical.called
                assert not mock_accept.called
    finally:
        dialog_b.close()


def test_license_info_panel_shows_trial_state() -> None:
    _, get_setting, set_setting = _fake_settings()
    service = MockLicenseProvider(get_setting, set_setting)
    fp = compute_device_fingerprint(get_setting, set_setting)
    service.start_trial(fp, "test-device")

    panel = LicenseInfoPanel(service, get_setting, set_setting)
    try:
        assert "試用中" in panel.status_label.text()
        assert panel.remaining_label.text() == "7 天"
    finally:
        panel.close()


def test_license_info_panel_shows_active_state() -> None:
    _, get_setting, set_setting = _fake_settings()
    service = MockLicenseProvider(get_setting, set_setting)
    fp = compute_device_fingerprint(get_setting, set_setting)
    service.activate_license("HF-PRO-AAAA-BBBB-CCCC", fp, "test-device")

    panel = LicenseInfoPanel(service, get_setting, set_setting)
    try:
        assert "使用中" in panel.status_label.text()
        assert panel.remaining_label.text() == "30 天"
    finally:
        panel.close()


def test_license_info_panel_shows_expired_state() -> None:
    """規格上「已到期」最實際能透過 LicenseInfoPanel.refresh() -> 真的
    呼叫 check_license() 重現的情境，是試用期滿——不是「ACTIVE 但
    expires_at/last_verified_at 都是很久以前」，因為 MockLicenseProvider
    的 check_license() 只要 device fingerprint 對得上，就會把
    last_verified_at 更新成「現在」（代表一次成功連線驗證，見
    mock_provider.py 的說明），offline grace 會因此重新從 0 天起算，
    永遠不會真的卡在「離線太久」——這是正確、刻意的設計，不是 bug。
    """
    _, get_setting, set_setting = _fake_settings()
    now = datetime(2026, 6, 1, 12, 0, 0)
    service = MockLicenseProvider(get_setting, set_setting, now_provider=lambda: now, trial_days=7)
    fp = compute_device_fingerprint(get_setting, set_setting)
    service.start_trial(fp, "test-device")

    # 把時間往後推到超過 7 天試用期。
    later = now + timedelta(days=8)
    service_after_trial = MockLicenseProvider(get_setting, set_setting, now_provider=lambda: later, trial_days=7)

    panel = LicenseInfoPanel(service_after_trial, get_setting, set_setting)
    try:
        assert "已到期" in panel.status_label.text()
    finally:
        panel.close()


def test_license_info_panel_shows_suspended_state() -> None:
    _, get_setting, set_setting = _fake_settings()
    service = MockLicenseProvider(get_setting, set_setting)
    fp = compute_device_fingerprint(get_setting, set_setting)
    service.activate_license("HF-PRO-AAAA-BBBB-CCCC", fp, "test-device")
    service._force_status_for_testing(LicenseStatus.SUSPENDED)

    panel = LicenseInfoPanel(service, get_setting, set_setting)
    try:
        assert "已停權" in panel.status_label.text()
    finally:
        panel.close()


def test_license_info_panel_shows_offline_grace_state() -> None:
    store, get_setting, set_setting = _fake_settings()
    now = datetime(2026, 6, 1, 12, 0, 0)
    service = MockLicenseProvider(get_setting, set_setting, now_provider=lambda: now, offline_grace_days=7)
    fp = compute_device_fingerprint(get_setting, set_setting)
    service.activate_license("HF-PRO-AAAA-BBBB-CCCC", fp, "test-device")

    # expires_at 是 2 天前（已過期），但 last_verified_at 也是 2 天前
    # （offline grace 7 天內），所以應該還能用，只是顯示「離線寬限期」。
    two_days_ago = now - timedelta(days=2)
    service._force_status_for_testing(LicenseStatus.ACTIVE, expires_at=two_days_ago.isoformat())
    set_setting("license_last_verified_at", two_days_ago.isoformat())
    set_setting("license_high_water_mark", two_days_ago.isoformat())

    panel = LicenseInfoPanel(service, get_setting, set_setting)
    try:
        assert "離線寬限期" in panel.status_label.text()
    finally:
        panel.close()


def test_license_info_panel_shows_no_license_state() -> None:
    _, get_setting, set_setting = _fake_settings()
    service = MockLicenseProvider(get_setting, set_setting)
    panel = LicenseInfoPanel(service, get_setting, set_setting)
    try:
        assert "尚未開始試用" in panel.status_label.text()
    finally:
        panel.close()


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
