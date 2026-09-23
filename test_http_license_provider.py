"""HTTPLicenseProvider 的正式回歸測試（2026-09-22 Phase 2，規格第 20、
29 節）。

用 httpx 的 ASGITransport 直接對 FastAPI app 送真正的 HTTP 語意請求
（不需要真的開一個 TCP port），DB 用 server/tests/_helpers.py 同一套
暫存 SQLite 隔離機制——完全不會碰 production Desktop DB，也不需要真的
啟動 uvicorn。

離線情境（offline within/beyond grace、clock rollback）改用一個會
主動拋出連線錯誤的假 client_factory 模擬「連不上 server」，驗證
HTTPLicenseProvider 正確退回本機快取 + evaluate_license() 的離線
判斷邏輯。
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.services.license import DeviceLimitReachedError, LicenseError, LicenseStatus, TrialAlreadyUsedError  # noqa: E402
from app.services.license.http_provider import HTTPLicenseProvider  # noqa: E402
from server.app.api.license_routes import license_activate, license_verify, trial_start  # noqa: E402
from server.app.schemas.license import ActivateRequest, TrialStartRequest, VerifyRequest  # noqa: E402
from server.app.services import admin_license_service  # noqa: E402
from server.tests._helpers import make_test_server  # noqa: E402


def _fake_settings() -> tuple[dict, callable, callable]:
    store: dict[str, str] = {}

    def get_setting(key: str, default: str = "") -> str:
        return store.get(key, default)

    def set_setting(key: str, value: str) -> None:
        store[key] = value

    return store, get_setting, set_setting


class _FakeResponse:
    """模擬 httpx.Response 的最小介面（.status_code / .json()）——
    HTTPLicenseProvider._post() 只用到這兩個。"""

    def __init__(self, status_code: int, body: dict) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> dict:
        return self._body


_ROUTE_TABLE = {
    "/api/trial/start": (trial_start, TrialStartRequest),
    "/api/license/activate": (license_activate, ActivateRequest),
    "/api/license/verify": (license_verify, VerifyRequest),
}


class _DirectCallClient:
    """繞過真正的網路層，直接呼叫 FastAPI route handler 函式本身
    （它們就是一般的 Python function，接受 Pydantic model + db
    session）——這樣可以完整測試 HTTPLicenseProvider 真正的請求/回應
    處理邏輯（包含它怎麼處理 4xx/5xx/連線錯誤），同時不需要真的起一個
    網路 server、不需要 async。真正端到端會不會通過真實 TCP，見本檔案
    下面單獨的 test_real_http_round_trip_via_live_uvicorn_server()。
    """

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    def __enter__(self) -> "_DirectCallClient":
        return self

    def __exit__(self, *_args) -> bool:
        return False

    def post(self, url: str, json: dict | None = None) -> _FakeResponse:
        path = "/" + url.split("://", 1)[-1].split("/", 1)[-1]
        handler, schema = _ROUTE_TABLE[path]
        db = self._session_factory()
        try:
            payload = schema(**(json or {}))
            try:
                result = handler(payload, db)
                return _FakeResponse(200, result.model_dump(mode="json"))
            except HTTPException as exc:
                return _FakeResponse(exc.status_code, {"detail": exc.detail})
        finally:
            db.close()


def _asgi_client_factory(session_factory):
    def factory():
        return _DirectCallClient(session_factory)
    return factory


def _make_provider(srv, get_setting, set_setting, now_provider=datetime.now, offline_grace_days=7):
    return HTTPLicenseProvider(
        get_setting, set_setting,
        base_url="http://127.0.0.1:8799",
        now_provider=now_provider,
        offline_grace_days=offline_grace_days,
        client_factory=_asgi_client_factory(srv.session_factory),
    )


class _AlwaysFailingClient:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, *a, **kw):
        raise httpx.ConnectError("simulated: server unreachable")


def _unreachable_client_factory():
    return _AlwaysFailingClient()


# ---------------------------------------------------------------------------
# First Run Trial
# ---------------------------------------------------------------------------


def test_first_run_trial_via_http() -> None:
    srv = make_test_server()
    try:
        _, get_setting, set_setting = _fake_settings()
        provider = _make_provider(srv, get_setting, set_setting)

        license_ = provider.start_trial("fp-" + "a" * 20, "desktop-a")
        assert license_.status == LicenseStatus.TRIAL

        cached = provider.get_current_license()
        assert cached is not None
        assert cached.status == LicenseStatus.TRIAL
    finally:
        srv.close()


def test_trial_second_attempt_raises_trial_already_used() -> None:
    srv = make_test_server()
    try:
        _, get_setting, set_setting = _fake_settings()
        provider = _make_provider(srv, get_setting, set_setting)
        fp = "fp-" + "b" * 20
        provider.start_trial(fp, "desktop-b")
        try:
            provider.start_trial(fp, "desktop-b")
            raise AssertionError("expected TrialAlreadyUsedError")
        except TrialAlreadyUsedError:
            pass
    finally:
        srv.close()


# ---------------------------------------------------------------------------
# Activation
# ---------------------------------------------------------------------------


def test_license_activation_success() -> None:
    srv = make_test_server()
    try:
        db = srv.db()
        result = admin_license_service.create_license(db, "test-admin", duration_days=30)
        db.close()

        _, get_setting, set_setting = _fake_settings()
        provider = _make_provider(srv, get_setting, set_setting)
        license_ = provider.activate_license(result.plaintext_key, "fp-" + "c" * 20, "desktop-c")
        assert license_.status == LicenseStatus.ACTIVE
    finally:
        srv.close()


def test_bad_key_raises_lookup_error() -> None:
    srv = make_test_server()
    try:
        _, get_setting, set_setting = _fake_settings()
        provider = _make_provider(srv, get_setting, set_setting)
        try:
            provider.activate_license("HF-PRO-ZZZZ-ZZZZ-ZZZZ-ZZZZ", "fp-" + "d" * 20, "desktop-d")
            raise AssertionError("expected LookupError")
        except LookupError:
            pass
    finally:
        srv.close()


def test_device_limit_raises_device_limit_reached_error() -> None:
    srv = make_test_server()
    try:
        db = srv.db()
        result = admin_license_service.create_license(db, "test-admin", duration_days=30, device_limit=1)
        db.close()

        _, get_setting_a, set_setting_a = _fake_settings()
        provider_a = _make_provider(srv, get_setting_a, set_setting_a)
        provider_a.activate_license(result.plaintext_key, "fp-" + "e" * 20, "desktop-e")

        _, get_setting_b, set_setting_b = _fake_settings()
        provider_b = _make_provider(srv, get_setting_b, set_setting_b)
        try:
            provider_b.activate_license(result.plaintext_key, "fp-" + "f" * 20, "desktop-f")
            raise AssertionError("expected DeviceLimitReachedError")
        except DeviceLimitReachedError:
            pass
    finally:
        srv.close()


# ---------------------------------------------------------------------------
# check_license(): Active / Expired / Suspended / Revoked
# ---------------------------------------------------------------------------


def _activate_and_get_provider(srv, duration_days: int = 30):
    db = srv.db()
    result = admin_license_service.create_license(db, "test-admin", duration_days=duration_days)
    license_id = result.license.license_id
    db.close()

    _, get_setting, set_setting = _fake_settings()
    provider = _make_provider(srv, get_setting, set_setting)
    fp = "fp-" + "g" * 20
    provider.activate_license(result.plaintext_key, fp, "desktop-g")
    return provider, fp, license_id


def test_check_license_active() -> None:
    srv = make_test_server()
    try:
        provider, fp, _ = _activate_and_get_provider(srv)
        result = provider.check_license(fp)
        assert result.can_use_app is True
        assert result.effective_status == LicenseStatus.ACTIVE
    finally:
        srv.close()


def test_check_license_expired() -> None:
    from server.app.models.license import License
    from server.app.timeutil import utc_now

    srv = make_test_server()
    try:
        provider, fp, license_id = _activate_and_get_provider(srv, duration_days=1)
        db = srv.db()
        row = db.query(License).filter_by(license_id=license_id).first()
        row.expires_at = utc_now() - timedelta(days=1)
        db.commit()
        db.close()

        result = provider.check_license(fp)
        assert result.can_use_app is False
        assert result.effective_status == LicenseStatus.EXPIRED
    finally:
        srv.close()


def test_check_license_suspended() -> None:
    srv = make_test_server()
    try:
        provider, fp, license_id = _activate_and_get_provider(srv)
        db = srv.db()
        admin_license_service.suspend_license(db, "test-admin", license_id)
        db.close()

        result = provider.check_license(fp)
        assert result.can_use_app is False
        assert result.effective_status == LicenseStatus.SUSPENDED
    finally:
        srv.close()


def test_check_license_revoked() -> None:
    srv = make_test_server()
    try:
        provider, fp, license_id = _activate_and_get_provider(srv)
        db = srv.db()
        admin_license_service.revoke_license(db, "test-admin", license_id)
        db.close()

        result = provider.check_license(fp)
        assert result.can_use_app is False
    finally:
        srv.close()


# ---------------------------------------------------------------------------
# Offline grace / clock rollback（用連線失敗的假 client 模擬離線）
# ---------------------------------------------------------------------------


def _expire_cached_license(provider: HTTPLicenseProvider, days_past: int) -> None:
    """離線 fallback（_offline_fallback()）用的是本機快取（
    provider._load_state()），完全不會去問 server 現在的狀態——這正是
    「離線」這件事的意義。所以要測試離線寬限期/時鐘回撥邏輯，必須直接
    竄改本機快取裡的 expires_at，模擬「這組被快取的 License 資料，
    在離線期間過期了」，而不是去改 server 端的 DB（server DB 的變化
    在真正離線時，Desktop 本來就不可能知道）。
    """
    import json

    state = json.loads(provider._get_setting("license_state_json", "{}"))
    expired_at = (datetime.now() - timedelta(days=days_past)).isoformat()
    state["expires_at"] = expired_at
    provider._set_setting("license_state_json", json.dumps(state, ensure_ascii=False))


def test_offline_within_seven_days_still_allowed() -> None:
    srv = make_test_server()
    try:
        provider, fp, license_id = _activate_and_get_provider(srv)
        assert provider.check_license(fp).can_use_app is True  # 先建立 last_verified_at 快取（此時仍在有效期內）

        # 本機快取的 License 現在過期了（2 天前到期），但上一次成功
        # 驗證是「剛剛」（last_verified_at 幾乎等於現在）——2 天遠小於
        # 7 天寬限期。
        _expire_cached_license(provider, days_past=2)

        provider._client_factory = _unreachable_client_factory
        result = provider.check_license(fp)
        assert result.can_use_app is True
        assert result.is_offline_grace is True
    finally:
        srv.close()


def test_offline_beyond_seven_days_blocked() -> None:
    srv = make_test_server()
    try:
        provider, fp, license_id = _activate_and_get_provider(srv)
        provider.check_license(fp)  # 建立 last_verified_at 快取

        _expire_cached_license(provider, days_past=2)

        # 把快取的 last_verified_at 往回撥 10 天，模擬「已經 10 天沒連上 server」。
        store_key = "license_last_verified_at"
        ten_days_ago = (datetime.now() - timedelta(days=10)).isoformat()
        provider._set_setting(store_key, ten_days_ago)

        provider._client_factory = _unreachable_client_factory
        result = provider.check_license(fp)
        assert result.can_use_app is False
        assert result.requires_reactivation is True
    finally:
        srv.close()


def test_clock_rollback_forces_reactivation() -> None:
    srv = make_test_server()
    try:
        provider, fp, license_id = _activate_and_get_provider(srv)
        provider.check_license(fp)  # 建立 high_water_mark（等於「現在」）

        _expire_cached_license(provider, days_past=2)  # 過期但仍在 7 天寬限期內

        # 模擬使用者把系統時鐘往回調——關鍵是要回撥到「還在 expires_at
        # 之後」（不然會落回 evaluate_license() 的『根本還沒過期』分支，
        # 那條分支不會檢查 clock tamper），但「比 high_water_mark
        # 早」（1 天前：晚於 2 天前到期的 expires_at，早於剛剛才記錄的
        # high_water_mark）——這樣才會真的走到 clock-tamper 檢查那條
        # 路徑。如果沒有這個防護，單看「離線天數」會誤判成還在寬限期內。
        rolled_back_time = datetime.now() - timedelta(days=1)
        provider._now = lambda: rolled_back_time
        provider._client_factory = _unreachable_client_factory

        result = provider.check_license(fp)
        assert result.can_use_app is False
        assert result.requires_reactivation is True
    finally:
        srv.close()


# ---------------------------------------------------------------------------
# License refresh / Settings 顯示 / 版本提示
# ---------------------------------------------------------------------------


def test_check_license_refreshes_local_cache() -> None:
    from server.app.models.license import License

    srv = make_test_server()
    try:
        provider, fp, license_id = _activate_and_get_provider(srv, duration_days=30)
        first = provider.get_current_license()
        first_expires = first.expires_at

        db = srv.db()
        admin_license_service.extend_license(db, "test-admin", license_id, 90)
        db.close()

        provider.check_license(fp)
        refreshed = provider.get_current_license()
        assert refreshed.expires_at != first_expires
    finally:
        srv.close()


def test_settings_panel_displays_active_license_via_http_provider() -> None:
    from app.services.license.fingerprint import compute_device_fingerprint
    from app.widgets.license_widgets import LicenseInfoPanel
    from PySide6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication([])

    srv = make_test_server()
    try:
        db = srv.db()
        result = admin_license_service.create_license(db, "test-admin", duration_days=30)
        db.close()

        _, get_setting, set_setting = _fake_settings()
        provider = _make_provider(srv, get_setting, set_setting)
        # LicenseInfoPanel 自己會用 compute_device_fingerprint() 算指紋，
        # 這裡活化時必須用同一個值，否則之後 panel 呼叫 check_license()
        # 會因為指紋對不上被 server 判定成「裝置未綁定」。
        fingerprint = compute_device_fingerprint(get_setting, set_setting)
        provider.activate_license(result.plaintext_key, fingerprint, "desktop-h")

        panel = LicenseInfoPanel(provider, get_setting, set_setting)
        try:
            assert "使用中" in panel.status_label.text()
        finally:
            panel.close()
    finally:
        srv.close()


def test_version_warning_shown_when_below_minimum() -> None:
    from app.services.license.fingerprint import compute_device_fingerprint
    from app.widgets.license_widgets import LicenseInfoPanel
    from PySide6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication([])

    srv = make_test_server()
    try:
        db = srv.db()
        from server.app.services.product_settings_service import update_product_settings
        update_product_settings(db, minimum_supported_version="99.0.0", latest_version="99.0.0")
        result = admin_license_service.create_license(db, "test-admin", duration_days=30)
        db.close()

        _, get_setting, set_setting = _fake_settings()
        provider = _make_provider(srv, get_setting, set_setting)
        fingerprint = compute_device_fingerprint(get_setting, set_setting)
        provider.activate_license(result.plaintext_key, fingerprint, "desktop-i")

        panel = LicenseInfoPanel(provider, get_setting, set_setting)
        try:
            # isVisible() 需要整個 top-level window 真的被 show() 過
            # 才會反映實際狀態；這裡的 panel 從沒 show()，所以要看
            # isHidden()（純粹反映 setVisible() 設的旗標本身）。
            assert panel.version_label.isHidden() is False
            assert "更新" in panel.version_label.text()
        finally:
            panel.close()
    finally:
        srv.close()


def test_no_version_warning_when_up_to_date() -> None:
    from app.services.license.fingerprint import compute_device_fingerprint
    from app.widgets.license_widgets import LicenseInfoPanel
    from PySide6.QtWidgets import QApplication

    from app.version import APP_VERSION

    _app = QApplication.instance() or QApplication([])

    srv = make_test_server()
    try:
        db = srv.db()
        from server.app.services.product_settings_service import update_product_settings
        update_product_settings(db, minimum_supported_version="0.1.0", latest_version=APP_VERSION)
        result = admin_license_service.create_license(db, "test-admin", duration_days=30)
        db.close()

        _, get_setting, set_setting = _fake_settings()
        provider = _make_provider(srv, get_setting, set_setting)
        fingerprint = compute_device_fingerprint(get_setting, set_setting)
        provider.activate_license(result.plaintext_key, fingerprint, "desktop-j")

        panel = LicenseInfoPanel(provider, get_setting, set_setting)
        try:
            assert panel.version_label.isHidden() is True
        finally:
            panel.close()
    finally:
        srv.close()


def test_real_http_round_trip_via_live_uvicorn_server() -> None:
    """跟上面其他測試不同——這裡真的啟動一個 uvicorn server（真正的
    TCP port，不是 direct-call 或 ASGITransport），HTTPLicenseProvider
    用預設的 httpx.Client（沒有注入假 client_factory）打真正的 HTTP
    請求過去。證明整條路徑（httpx → TCP → uvicorn → FastAPI →
    SQLAlchemy）真的能通，不只是繞過網路層的邏輯測試。
    """
    from server.tests._live_server import start_live_test_server

    live = start_live_test_server(port=8799)
    try:
        db = live.db()
        result = admin_license_service.create_license(db, "test-admin", duration_days=30)
        db.close()

        _, get_setting, set_setting = _fake_settings()
        provider = HTTPLicenseProvider(get_setting, set_setting, base_url=live.base_url)

        license_ = provider.activate_license(result.plaintext_key, "fp-" + "real" * 5, "desktop-real")
        assert license_.status == LicenseStatus.ACTIVE

        check_result = provider.check_license("fp-" + "real" * 5)
        assert check_result.can_use_app is True
    finally:
        live.stop()


if __name__ == "__main__":
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
