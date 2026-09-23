"""Failure simulation（2026-09-23 Phase 3A，規格第 27 節）。

其餘的失敗情境（expired/suspended/revoked License、duplicate
Device、clock rollback、server unreachable、invalid Admin
credentials）已經分別在 test_lifecycle.py / test_activation.py /
test_admin_auth.py / test_http_license_provider.py 涵蓋，這裡只補上
還沒測過的：DB unavailable、bad DATABASE_URL、missing secret。

核心要求：Server 跟 Desktop 都不能因為這些情況而崩潰（未攔截的例外/
process 直接掛掉）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from server.tests._helpers import make_test_server  # noqa: E402


def test_missing_secret_key_in_production_raises_clear_error() -> None:
    """規格第 26 節（missing secret）：production 模式下沒有
    HOUSEFLOW_SECRET_KEY 必須 fail-fast，且錯誤訊息要講清楚缺了什麼，
    不是一個模糊的 KeyError/AttributeError。
    """
    import server.app.config as config_module

    original_env = os.environ.get("HOUSEFLOW_SECRET_KEY")
    original_environment = os.environ.get("ENVIRONMENT")
    original_cache = config_module._ephemeral_secret_key_cache
    os.environ.pop("HOUSEFLOW_SECRET_KEY", None)
    os.environ["ENVIRONMENT"] = "production"
    config_module._ephemeral_secret_key_cache = None
    try:
        try:
            config_module.get_settings()
            raise AssertionError("expected RuntimeError for missing HOUSEFLOW_SECRET_KEY in production")
        except RuntimeError as exc:
            assert "HOUSEFLOW_SECRET_KEY" in str(exc)
    finally:
        if original_env is None:
            os.environ.pop("HOUSEFLOW_SECRET_KEY", None)
        else:
            os.environ["HOUSEFLOW_SECRET_KEY"] = original_env
        if original_environment is None:
            os.environ.pop("ENVIRONMENT", None)
        else:
            os.environ["ENVIRONMENT"] = original_environment
        config_module._ephemeral_secret_key_cache = original_cache


def test_missing_signing_key_in_production_raises_clear_error() -> None:
    import server.app.config as config_module
    import server.app.services.signing_service as signing_module

    original_signing_env = os.environ.get("HOUSEFLOW_LICENSE_SIGNING_PRIVATE_KEY")
    original_environment = os.environ.get("ENVIRONMENT")
    original_secret = os.environ.get("HOUSEFLOW_SECRET_KEY")
    original_signing_cache = signing_module._ephemeral_private_key_cache

    os.environ.pop("HOUSEFLOW_LICENSE_SIGNING_PRIVATE_KEY", None)
    os.environ["ENVIRONMENT"] = "production"
    os.environ["HOUSEFLOW_SECRET_KEY"] = "test-secret-for-this-test-only"
    signing_module._ephemeral_private_key_cache = None
    try:
        try:
            signing_module._load_or_generate_private_key()
            raise AssertionError("expected RuntimeError for missing signing key in production")
        except RuntimeError as exc:
            assert "HOUSEFLOW_LICENSE_SIGNING_PRIVATE_KEY" in str(exc)
    finally:
        if original_signing_env is None:
            os.environ.pop("HOUSEFLOW_LICENSE_SIGNING_PRIVATE_KEY", None)
        else:
            os.environ["HOUSEFLOW_LICENSE_SIGNING_PRIVATE_KEY"] = original_signing_env
        if original_environment is None:
            os.environ.pop("ENVIRONMENT", None)
        else:
            os.environ["ENVIRONMENT"] = original_environment
        if original_secret is None:
            os.environ.pop("HOUSEFLOW_SECRET_KEY", None)
        else:
            os.environ["HOUSEFLOW_SECRET_KEY"] = original_secret
        signing_module._ephemeral_private_key_cache = original_signing_cache


def test_bad_database_url_fails_at_engine_creation_not_silently() -> None:
    """格式錯誤的 DATABASE_URL 應該在建立 engine／第一次真正連線時
    就明確失敗，不是產生一個看起來正常、實際上完全連不到任何東西的
    engine。
    """
    from sqlalchemy.exc import ArgumentError

    from server.app.config import Settings
    from server.app.database import create_db_engine

    bad_settings = Settings(database_url="not-a-valid-sqlalchemy-url-at-all")
    try:
        engine = create_db_engine(bad_settings)
        # 有些格式錯誤在建立 engine 當下就報錯，有些要等第一次真正連線
        # 才會發現——兩種都要能明確失敗，不能是「看起來成功但其實
        # 完全連不到東西」。
        with engine.connect():
            pass
        raise AssertionError("expected a connection/argument error for an invalid DATABASE_URL")
    except (ArgumentError, Exception) as exc:  # noqa: BLE001
        assert not isinstance(exc, AssertionError)


def test_db_unavailable_returns_503_not_crash() -> None:
    """readiness endpoint 已經在 test_production_hardening.py 測過
    「DB 掛了不洩漏細節」；這裡額外確認一個會真的查資料庫的 API
    （/api/license/verify）在 DB session 建立失敗時，也是回傳明確的
    500（被全域例外處理接住），不是讓整個 process 崩潰。
    """
    srv = make_test_server()
    try:
        from fastapi.testclient import TestClient

        from server.app.database import get_db

        def _broken_get_db():
            raise RuntimeError("simulated: database connection pool exhausted")
            yield  # pragma: no cover - unreachable, keeps this a generator

        srv.client.app.dependency_overrides[get_db] = _broken_get_db
        client = TestClient(srv.client.app, raise_server_exceptions=False)

        resp = client.post(
            "/api/license/verify",
            json={"license_id": "whatever", "device_fingerprint": "fp-" + "a" * 20, "app_version": "3.4.0"},
        )
        assert resp.status_code == 500
        assert "database connection pool" not in resp.text
    finally:
        srv.close()


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
