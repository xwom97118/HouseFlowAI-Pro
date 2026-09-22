"""Offline grace 與版本 metadata 回歸測試（2026-09-22 Phase 2，規格第
8、9、13、25、28 節）：verify 回應帶 offline_valid_until、
minimum_supported_version／latest_version，且這些值來自
ProductSettings 而不是寫死。
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from server.app.services import admin_license_service  # noqa: E402
from server.app.services.product_settings_service import update_product_settings  # noqa: E402
from server.tests._helpers import make_test_server  # noqa: E402


def _create_and_activate(srv, duration_days: int = 30):
    db = srv.db()
    result = admin_license_service.create_license(db, "test-admin", duration_days=duration_days)
    key = result.plaintext_key
    license_id = result.license.license_id
    db.close()

    fp = "fp-" + "o" * 20
    resp = srv.client.post("/api/license/activate", json={"license_key": key, "device_fingerprint": fp, "device_name": "d1", "app_version": "3.4.0"})
    assert resp.status_code == 200
    return license_id, fp


def test_verify_response_includes_offline_valid_until() -> None:
    srv = make_test_server()
    try:
        license_id, fp = _create_and_activate(srv)
        resp = srv.client.post("/api/license/verify", json={"license_id": license_id, "device_fingerprint": fp, "app_version": "3.4.0"})
        body = resp.json()
        assert body["offline_valid_until"] is not None
    finally:
        srv.close()


def test_offline_valid_until_respects_configured_grace_days() -> None:
    srv = make_test_server()
    try:
        db = srv.db()
        update_product_settings(db, offline_grace_days=3)
        db.close()

        license_id, fp = _create_and_activate(srv)
        resp = srv.client.post("/api/license/verify", json={"license_id": license_id, "device_fingerprint": fp, "app_version": "3.4.0"})
        body = resp.json()

        from datetime import datetime

        server_time = datetime.fromisoformat(body["server_time"])
        offline_until = datetime.fromisoformat(body["offline_valid_until"])
        delta_days = (offline_until - server_time).total_seconds() / 86400
        assert 2.9 <= delta_days <= 3.1
    finally:
        srv.close()


def test_verify_response_includes_version_metadata() -> None:
    srv = make_test_server()
    try:
        db = srv.db()
        update_product_settings(db, latest_version="4.0.0", minimum_supported_version="3.2.0")
        db.close()

        license_id, fp = _create_and_activate(srv)
        resp = srv.client.post("/api/license/verify", json={"license_id": license_id, "device_fingerprint": fp, "app_version": "3.4.0"})
        body = resp.json()
        assert body["latest_version"] == "4.0.0"
        assert body["minimum_supported_version"] == "3.2.0"
    finally:
        srv.close()


def test_trial_start_also_includes_version_metadata() -> None:
    srv = make_test_server()
    try:
        resp = srv.client.post(
            "/api/trial/start",
            json={"device_fingerprint": "fp-" + "p" * 20, "device_name": "d1", "app_version": "3.4.0"},
        )
        body = resp.json()
        assert body["minimum_supported_version"]
        assert body["latest_version"]
    finally:
        srv.close()


def test_version_metadata_is_not_hardcoded_defaults_only() -> None:
    """規格第 13 節：Desktop 不得把 latest_version/minimum_supported_version
    當成唯一權威——這裡驗證 Admin 改了設定後，API 回應真的反映新值
    （而不是回應裡永遠是同一組寫死字串）。
    """
    srv = make_test_server()
    try:
        license_id, fp = _create_and_activate(srv)
        before = srv.client.post("/api/license/verify", json={"license_id": license_id, "device_fingerprint": fp, "app_version": "3.4.0"}).json()

        db = srv.db()
        update_product_settings(db, latest_version="9.9.9")
        db.close()

        after = srv.client.post("/api/license/verify", json={"license_id": license_id, "device_fingerprint": fp, "app_version": "3.4.0"}).json()
        assert before["latest_version"] != after["latest_version"]
        assert after["latest_version"] == "9.9.9"
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
