"""License 啟用相關回歸測試（2026-09-22 Phase 2，規格第 7、11、28
節）：啟用成功、License 不存在、裝置數上限、Deactivate 後重新啟用、
重複啟用（同一裝置）視為冪等。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from server.app.services import admin_license_service  # noqa: E402
from server.tests._helpers import make_test_server  # noqa: E402


def _create_license(srv, device_limit: int = 1, duration_days: int = 30):
    db = srv.db()
    result = admin_license_service.create_license(
        db, "test-admin", plan="professional", is_early_bird=False, duration_days=duration_days, device_limit=device_limit
    )
    key = result.plaintext_key
    license_id = result.license.license_id
    db.close()
    return key, license_id


def test_activate_valid_key_succeeds() -> None:
    srv = make_test_server()
    try:
        key, _ = _create_license(srv)
        resp = srv.client.post(
            "/api/license/activate",
            json={"license_key": key, "device_fingerprint": "fp-" + "a" * 20, "device_name": "device-a", "app_version": "3.4.0"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is True
        assert body["status"] == "active"
    finally:
        srv.close()


def test_activate_invalid_key_returns_404() -> None:
    srv = make_test_server()
    try:
        resp = srv.client.post(
            "/api/license/activate",
            json={"license_key": "HF-PRO-ZZZZ-ZZZZ-ZZZZ-ZZZZ", "device_fingerprint": "fp-" + "b" * 20, "device_name": "d", "app_version": "3.4.0"},
        )
        assert resp.status_code == 404
    finally:
        srv.close()


def test_duplicate_activation_same_device_is_idempotent() -> None:
    srv = make_test_server()
    try:
        key, _ = _create_license(srv)
        fp = "fp-" + "c" * 20
        first = srv.client.post("/api/license/activate", json={"license_key": key, "device_fingerprint": fp, "device_name": "d1", "app_version": "3.4.0"})
        second = srv.client.post("/api/license/activate", json={"license_key": key, "device_fingerprint": fp, "device_name": "d1", "app_version": "3.4.0"})
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["license_id"] == second.json()["license_id"]
    finally:
        srv.close()


def test_device_limit_reached_rejects_second_device() -> None:
    srv = make_test_server()
    try:
        key, _ = _create_license(srv, device_limit=1)
        first = srv.client.post("/api/license/activate", json={"license_key": key, "device_fingerprint": "fp-" + "d" * 20, "device_name": "d1", "app_version": "3.4.0"})
        second = srv.client.post("/api/license/activate", json={"license_key": key, "device_fingerprint": "fp-" + "e" * 20, "device_name": "d2", "app_version": "3.4.0"})
        assert first.status_code == 200
        assert second.status_code == 409
    finally:
        srv.close()


def test_device_limit_two_allows_two_devices() -> None:
    srv = make_test_server()
    try:
        key, _ = _create_license(srv, device_limit=2)
        first = srv.client.post("/api/license/activate", json={"license_key": key, "device_fingerprint": "fp-" + "f" * 20, "device_name": "d1", "app_version": "3.4.0"})
        second = srv.client.post("/api/license/activate", json={"license_key": key, "device_fingerprint": "fp-" + "g" * 20, "device_name": "d2", "app_version": "3.4.0"})
        assert first.status_code == 200
        assert second.status_code == 200
    finally:
        srv.close()


def test_device_deactivate_then_reactivate_allows_new_device() -> None:
    srv = make_test_server()
    try:
        key, license_id = _create_license(srv, device_limit=1)
        fp_old = "fp-" + "h" * 20
        fp_new = "fp-" + "i" * 20

        activate_resp = srv.client.post("/api/license/activate", json={"license_key": key, "device_fingerprint": fp_old, "device_name": "old-device", "app_version": "3.4.0"})
        assert activate_resp.status_code == 200

        blocked_resp = srv.client.post("/api/license/activate", json={"license_key": key, "device_fingerprint": fp_new, "device_name": "new-device", "app_version": "3.4.0"})
        assert blocked_resp.status_code == 409

        # Admin 解除舊裝置綁定
        from server.app.models.license import DeviceBinding

        db = srv.db()
        old_device = db.query(DeviceBinding).filter_by(device_name="old-device").first()
        admin_license_service.deactivate_device(db, "test-admin", license_id, old_device.device_id)
        db.close()

        now_ok_resp = srv.client.post("/api/license/activate", json={"license_key": key, "device_fingerprint": fp_new, "device_name": "new-device", "app_version": "3.4.0"})
        assert now_ok_resp.status_code == 200
    finally:
        srv.close()


def test_activate_suspended_license_rejected() -> None:
    srv = make_test_server()
    try:
        key, license_id = _create_license(srv)
        db = srv.db()
        admin_license_service.suspend_license(db, "test-admin", license_id)
        db.close()

        resp = srv.client.post("/api/license/activate", json={"license_key": key, "device_fingerprint": "fp-" + "j" * 20, "device_name": "d", "app_version": "3.4.0"})
        assert resp.status_code == 403
    finally:
        srv.close()


def test_activate_revoked_license_rejected() -> None:
    srv = make_test_server()
    try:
        key, license_id = _create_license(srv)
        db = srv.db()
        admin_license_service.revoke_license(db, "test-admin", license_id)
        db.close()

        resp = srv.client.post("/api/license/activate", json={"license_key": key, "device_fingerprint": "fp-" + "k" * 20, "device_name": "d", "app_version": "3.4.0"})
        assert resp.status_code == 403
    finally:
        srv.close()


def test_verify_unbound_device_rejected() -> None:
    srv = make_test_server()
    try:
        key, license_id = _create_license(srv)
        srv.client.post("/api/license/activate", json={"license_key": key, "device_fingerprint": "fp-" + "l" * 20, "device_name": "d", "app_version": "3.4.0"})

        resp = srv.client.post("/api/license/verify", json={"license_id": license_id, "device_fingerprint": "fp-" + "m" * 20, "app_version": "3.4.0"})
        assert resp.status_code == 403
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
