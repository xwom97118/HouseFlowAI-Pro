"""Signed license state 的正式回歸測試（2026-09-23 Phase 3A，規格第
20 節）：Server 簽章 + Desktop 驗證 + 本機快取遭竄改時能被偵測到。

跟 test_http_license_provider.py 用同一套 direct-call 測試手法，額外
設定 HOUSEFLOW_LICENSE_SERVER_PUBLIC_KEY 環境變數，讓簽章驗證真的
「啟用」起來（預設沒設定這個變數時，Phase 3A 刻意不強制擋——見
app/services/license/signing.py 檔案開頭的說明）。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.services.license import LicenseStatus  # noqa: E402
from app.services.license.http_provider import HTTPLicenseProvider  # noqa: E402
from app.services.license.signing import verify_license_state_signature  # noqa: E402
from server.app.api.license_routes import license_activate, license_verify, trial_start  # noqa: E402
from server.app.schemas.license import ActivateRequest, TrialStartRequest, VerifyRequest  # noqa: E402
from server.app.services import admin_license_service  # noqa: E402
from server.app.services.signing_service import current_public_key_base64  # noqa: E402
from server.tests._helpers import make_test_server  # noqa: E402

_TEST_PUBLIC_KEY_ENV = "HOUSEFLOW_LICENSE_SERVER_PUBLIC_KEY"


def _fake_settings() -> tuple[dict, callable, callable]:
    store: dict[str, str] = {}

    def get_setting(key: str, default: str = "") -> str:
        return store.get(key, default)

    def set_setting(key: str, value: str) -> None:
        store[key] = value

    return store, get_setting, set_setting


class _FakeResponse:
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


def _make_provider(srv, get_setting, set_setting):
    def factory():
        return _DirectCallClient(srv.session_factory)

    return HTTPLicenseProvider(get_setting, set_setting, base_url="http://127.0.0.1:8799", client_factory=factory)


def _with_test_public_key(fn):
    """裝飾器：讓這個測試在真正的（跟目前 server 私鑰配對的）公鑰
    環境變數下執行，結束後還原環境變數，不汙染其他測試。"""

    def wrapper():
        original = os.environ.get(_TEST_PUBLIC_KEY_ENV)
        try:
            public_key = current_public_key_base64()
            os.environ[_TEST_PUBLIC_KEY_ENV] = public_key
            fn()
        finally:
            if original is None:
                os.environ.pop(_TEST_PUBLIC_KEY_ENV, None)
            else:
                os.environ[_TEST_PUBLIC_KEY_ENV] = original

    wrapper.__name__ = fn.__name__
    return wrapper


@_with_test_public_key
def test_server_response_includes_valid_signature() -> None:
    srv = make_test_server()
    try:
        db = srv.db()
        result = admin_license_service.create_license(db, "test-admin", duration_days=30)
        db.close()

        _, get_setting, set_setting = _fake_settings()
        provider = _make_provider(srv, get_setting, set_setting)
        provider.activate_license(result.plaintext_key, "fp-" + "a" * 20, "desktop-a")

        state = json.loads(get_setting("license_state_json", "{}"))
        assert state.get("signature")

        valid = verify_license_state_signature(
            license_id=state["license_id"], status=state["status"],
            expires_at=state.get("expires_at") or "", trial_ends_at=state.get("trial_ends_at") or "",
            server_time=state["server_time"], signature_b64=state["signature"],
        )
        assert valid is True
    finally:
        srv.close()


@_with_test_public_key
def test_tampered_local_cache_is_detected_and_rejected_offline() -> None:
    """核心情境：使用者直接改本機快取的 expires_at 想繞過授權，離線時
    應該被簽章驗證擋下，不能被 evaluate_license() 誤判成「還有效」。
    """
    srv = make_test_server()
    try:
        db = srv.db()
        result = admin_license_service.create_license(db, "test-admin", duration_days=30)
        db.close()

        _, get_setting, set_setting = _fake_settings()
        provider = _make_provider(srv, get_setting, set_setting)
        fp = "fp-" + "b" * 20
        provider.activate_license(result.plaintext_key, fp, "desktop-b")
        provider.check_license(fp)  # 建立離線寬限期判斷需要的 last_verified_at 快取

        # 使用者手動竄改本機快取——把 expires_at 改到很久以後，想繞過到期判斷。
        state = json.loads(get_setting("license_state_json", "{}"))
        state["expires_at"] = "2099-01-01T00:00:00"
        set_setting("license_state_json", json.dumps(state, ensure_ascii=False))

        # 模擬離線（連不上 server）
        class _AlwaysFailingClient:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def post(self, *a, **kw):
                raise httpx.ConnectError("simulated: offline")

        provider._client_factory = lambda: _AlwaysFailingClient()

        check_result = provider.check_license(fp)
        assert check_result.can_use_app is False
        assert check_result.requires_reactivation is True
    finally:
        srv.close()


@_with_test_public_key
def test_untampered_local_cache_still_works_offline() -> None:
    """對照組：沒有被竄改的快取，離線時應該照常能用（不是「有簽章
    驗證功能」就變得比 Phase 2 更嚴格，只是多了竄改偵測）。
    """
    srv = make_test_server()
    try:
        db = srv.db()
        result = admin_license_service.create_license(db, "test-admin", duration_days=30)
        db.close()

        _, get_setting, set_setting = _fake_settings()
        provider = _make_provider(srv, get_setting, set_setting)
        fp = "fp-" + "c" * 20
        provider.activate_license(result.plaintext_key, fp, "desktop-c")
        provider.check_license(fp)

        class _AlwaysFailingClient:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def post(self, *a, **kw):
                raise httpx.ConnectError("simulated: offline")

        provider._client_factory = lambda: _AlwaysFailingClient()

        check_result = provider.check_license(fp)
        assert check_result.can_use_app is True
    finally:
        srv.close()


def test_wrong_public_key_rejects_valid_server_response() -> None:
    """公鑰設定錯誤（不是這個 server 私鑰配對的公鑰）——必須拒絕，不能
    誤信。"""
    srv = make_test_server()
    try:
        db = srv.db()
        result = admin_license_service.create_license(db, "test-admin", duration_days=30)
        db.close()

        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
        import base64

        wrong_key = Ed25519PrivateKey.generate()
        wrong_public_b64 = base64.b64encode(
            wrong_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        ).decode("ascii")

        original = os.environ.get(_TEST_PUBLIC_KEY_ENV)
        os.environ[_TEST_PUBLIC_KEY_ENV] = wrong_public_b64
        try:
            _, get_setting, set_setting = _fake_settings()
            provider = _make_provider(srv, get_setting, set_setting)
            try:
                provider.activate_license(result.plaintext_key, "fp-" + "d" * 20, "desktop-d")
                raise AssertionError("expected LicenseError due to signature mismatch")
            except Exception as exc:  # noqa: BLE001
                assert "簽章" in str(exc)
        finally:
            if original is None:
                os.environ.pop(_TEST_PUBLIC_KEY_ENV, None)
            else:
                os.environ[_TEST_PUBLIC_KEY_ENV] = original
    finally:
        srv.close()


def test_signature_verification_disabled_by_default() -> None:
    """沒設定 HOUSEFLOW_LICENSE_SERVER_PUBLIC_KEY 時（Phase 2 既有安裝
    的預設狀態），維持原本行為，不會因為新功能而意外鎖住既有使用者。
    """
    from app.services.license.signing import is_signature_verification_enabled

    original = os.environ.pop(_TEST_PUBLIC_KEY_ENV, None)
    try:
        assert is_signature_verification_enabled() is False
    finally:
        if original is not None:
            os.environ[_TEST_PUBLIC_KEY_ENV] = original


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
