"""Desktop offline 情境 + 版本強制情境的敘事型回歸測試（2026-09-23
Phase 3A，規格第 28、29 節）。

跟 test_http_license_provider.py / server 端的 test_offline_and_version.py
涵蓋的是同一套底層邏輯，這裡刻意照規格寫的敘事逐字對應寫測試（Day
1/6/8、Desktop 1.0 + latest 1.1 + minimum 1.0/1.1），確保「這個具體
情境」有明確、可以逐項對照規格的測試，不只是邏輯上被涵蓋到。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.services.license.http_provider import HTTPLicenseProvider  # noqa: E402
from server.app.api.license_routes import license_activate, license_verify, trial_start  # noqa: E402
from server.app.schemas.license import ActivateRequest, TrialStartRequest, VerifyRequest  # noqa: E402
from server.app.services import admin_license_service  # noqa: E402
from server.app.services.product_settings_service import update_product_settings  # noqa: E402
from server.tests._helpers import make_test_server  # noqa: E402


def _fake_settings():
    store: dict[str, str] = {}
    return store, (lambda k, d="": store.get(k, d)), (lambda k, v: store.__setitem__(k, v))


class _FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


_ROUTE_TABLE = {
    "/api/trial/start": (trial_start, TrialStartRequest),
    "/api/license/activate": (license_activate, ActivateRequest),
    "/api/license/verify": (license_verify, VerifyRequest),
}


class _DirectCallClient:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, json=None):
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


class _AlwaysFailingClient:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, *a, **kw):
        raise httpx.ConnectError("simulated: server unreachable")


def _make_provider(srv, get_setting, set_setting):
    def factory():
        return _DirectCallClient(srv.session_factory)

    return HTTPLicenseProvider(get_setting, set_setting, base_url="http://127.0.0.1:8799", client_factory=factory)


# ---------------------------------------------------------------------------
# 規格第 28 節：Desktop Offline Scenario
# ---------------------------------------------------------------------------


def test_offline_scenario_day1_day6_day8() -> None:
    """模擬：License Server reachable → verify success，然後 Server
    unavailable。Day 1：PASS。Day 6：PASS。Day 8：要求重新連線。資料：
    全部保留。
    """
    srv = make_test_server()
    try:
        db = srv.db()
        result = admin_license_service.create_license(db, "test-admin", duration_days=1)
        license_id = result.license.license_id
        db.close()

        _, get_setting, set_setting = _fake_settings()
        provider = _make_provider(srv, get_setting, set_setting)
        fp = "fp-" + "day" * 7

        provider.activate_license(result.plaintext_key, fp, "offline-scenario-device")
        provider.check_license(fp)  # 建立成功連線的 last_verified_at 快取

        # 讓 License 過期（1 天後到期），但仍在 7 天離線寬限期內——
        # 這個情境要測的是「連不上 server 期間，寬限期怎麼算」，不是
        # 「License 本身還沒過期」。
        from server.app.models.license import License
        from server.app.timeutil import utc_now

        db = srv.db()
        row = db.query(License).filter_by(license_id=license_id).first()
        row.expires_at = utc_now() - timedelta(hours=1)
        db.commit()
        db.close()

        # 本機快取也要同步反映「已過期」，模擬使用者裝置離線期間
        # License 到期的真實情境（快取內容來自剛剛那次成功驗證，這裡
        # 手動推進代表時間流逝）。
        state = json.loads(get_setting("license_state_json", "{}"))
        state["expires_at"] = row.expires_at.isoformat()
        set_setting("license_state_json", json.dumps(state, ensure_ascii=False))

        provider._client_factory = lambda: _AlwaysFailingClient()

        # Day 1：離線第 1 天，應該還能正常使用。
        provider._now = lambda: datetime.now() + timedelta(days=1)
        day1_result = provider.check_license(fp)
        assert day1_result.can_use_app is True, "Day 1 應該 PASS"

        # Day 6：離線第 6 天，仍在 7 天寬限期內，應該還能使用。
        provider._now = lambda: datetime.now() + timedelta(days=6)
        day6_result = provider.check_license(fp)
        assert day6_result.can_use_app is True, "Day 6 應該 PASS"

        # Day 8：超過 7 天寬限期，要求重新連線驗證。
        provider._now = lambda: datetime.now() + timedelta(days=8)
        day8_result = provider.check_license(fp)
        assert day8_result.can_use_app is False, "Day 8 應該要求重新連線"
        assert day8_result.requires_reactivation is True

        # 資料全部保留：本機快取沒有被清空，License 在 server 端也還在。
        assert get_setting("license_state_json", "") != ""
        db = srv.db()
        still_exists = db.query(License).filter_by(license_id=license_id).first()
        db.close()
        assert still_exists is not None
    finally:
        srv.close()


# ---------------------------------------------------------------------------
# 規格第 29 節：Version Enforcement
# ---------------------------------------------------------------------------


def test_version_scenario_update_available() -> None:
    """Desktop 1.0，latest 1.1，minimum 1.0 → update available（不強制）。"""
    srv = make_test_server()
    try:
        db = srv.db()
        update_product_settings(db, latest_version="1.1", minimum_supported_version="1.0")
        result = admin_license_service.create_license(db, "test-admin", duration_days=30)
        db.close()

        _, get_setting, set_setting = _fake_settings()
        provider = _make_provider(srv, get_setting, set_setting)
        fp = "fp-" + "ver-avail" * 3
        provider.activate_license(result.plaintext_key, fp, "version-scenario-device")

        check_result = provider.check_license(fp)
        assert check_result.can_use_app is True  # 目前版本仍在最低支援版本之上，不強制擋
        assert check_result.latest_version == "1.1"
        assert check_result.minimum_supported_version == "1.0"
    finally:
        srv.close()


def test_version_scenario_update_required() -> None:
    """Desktop 1.0，minimum 1.1 → update required（強制）。"""
    from app.services.updater_service import is_newer_version

    srv = make_test_server()
    try:
        db = srv.db()
        update_product_settings(db, latest_version="1.1", minimum_supported_version="1.1")
        result = admin_license_service.create_license(db, "test-admin", duration_days=30)
        db.close()

        _, get_setting, set_setting = _fake_settings()
        provider = _make_provider(srv, get_setting, set_setting)
        fp = "fp-" + "ver-reqd" * 3
        provider.activate_license(result.plaintext_key, fp, "version-scenario-device-2")

        check_result = provider.check_license(fp)
        # License 本身仍然有效（到期日還沒到），但 UI 應該根據
        # minimum_supported_version 判斷出「這個版本（1.0）已經低於
        # 最低支援版本（1.1），需要更新後才能繼續使用」——這個判斷邏輯
        # 由 LicenseInfoPanel._update_version_label() 使用
        # is_newer_version() 完成（見 app/widgets/license_widgets.py）。
        current_desktop_version = "1.0"
        assert is_newer_version(check_result.minimum_supported_version, current_desktop_version) is True
    finally:
        srv.close()


def test_version_scenario_no_update_needed_when_up_to_date() -> None:
    """對照組：目前版本已經是最新版，不應該顯示任何更新提示。"""
    from app.services.updater_service import is_newer_version

    srv = make_test_server()
    try:
        db = srv.db()
        update_product_settings(db, latest_version="1.0", minimum_supported_version="1.0")
        result = admin_license_service.create_license(db, "test-admin", duration_days=30)
        db.close()

        _, get_setting, set_setting = _fake_settings()
        provider = _make_provider(srv, get_setting, set_setting)
        fp = "fp-" + "ver-uptodate" * 2
        provider.activate_license(result.plaintext_key, fp, "version-scenario-device-3")

        check_result = provider.check_license(fp)
        current_desktop_version = "1.0"
        assert is_newer_version(check_result.latest_version, current_desktop_version) is False
        assert is_newer_version(check_result.minimum_supported_version, current_desktop_version) is False
    finally:
        srv.close()


def test_this_round_does_not_download_any_update() -> None:
    """規格第 29 節：這一輪不要真的下載 updater——確認
    UpdateSteps 預設仍然是 NotImplementedError（Phase 1 Updater
    骨架維持不變，Phase 3A 沒有新增任何真正的下載/安裝邏輯）。
    """
    from app.services.updater_service import UpdateMetadata, UpdateSteps

    steps = UpdateSteps()
    metadata = UpdateMetadata(
        latest_version="9.9.9", minimum_supported_version="0.0.1",
        release_notes="", download_url="https://example.invalid/x", sha256="", published_at="",
    )
    try:
        steps.download_update(metadata, Path("unused"))
        raise AssertionError("expected NotImplementedError - this phase must not actually download anything")
    except NotImplementedError:
        pass


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
