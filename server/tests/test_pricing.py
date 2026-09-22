"""Early Bird 定價回歸測試（2026-09-22 Phase 2，規格第 12、13、28
節）：688 早鳥價、全域漲價後早鳥不受影響、非早鳥 License 跟隨全域價格。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from server.app.services import admin_license_service  # noqa: E402
from server.app.services.product_settings_service import update_product_settings  # noqa: E402
from server.tests._helpers import make_test_server  # noqa: E402


def test_early_bird_license_locks_in_688() -> None:
    srv = make_test_server()
    try:
        db = srv.db()
        result = admin_license_service.create_license(db, "test-admin", is_early_bird=True, duration_days=30)
        db.close()
        assert result.license.is_early_bird is True
        assert result.license.locked_price == 688

        fp = "fp-" + "a" * 20
        activate = srv.client.post("/api/license/activate", json={"license_key": result.plaintext_key, "device_fingerprint": fp, "device_name": "d", "app_version": "3.4.0"})
        assert activate.json()["price"] == 688
        assert activate.json()["is_early_bird"] is True
    finally:
        srv.close()


def test_global_price_change_does_not_affect_early_bird() -> None:
    srv = make_test_server()
    try:
        db = srv.db()
        result = admin_license_service.create_license(db, "test-admin", is_early_bird=True, duration_days=30)
        license_id = result.license.license_id

        update_product_settings(db, current_monthly_price=988)
        db.close()

        fp = "fp-" + "b" * 20
        activate = srv.client.post("/api/license/activate", json={"license_key": result.plaintext_key, "device_fingerprint": fp, "device_name": "d", "app_version": "3.4.0"})
        assert activate.json()["price"] == 688  # 早鳥永久不受全域漲價影響

        verify = srv.client.post("/api/license/verify", json={"license_id": license_id, "device_fingerprint": fp, "app_version": "3.4.0"})
        assert verify.json()["price"] == 688
    finally:
        srv.close()


def test_non_early_bird_license_follows_global_price() -> None:
    srv = make_test_server()
    try:
        db = srv.db()
        result = admin_license_service.create_license(db, "test-admin", is_early_bird=False, duration_days=30)
        update_product_settings(db, current_monthly_price=888)
        db.close()

        fp = "fp-" + "c" * 20
        activate = srv.client.post("/api/license/activate", json={"license_key": result.plaintext_key, "device_fingerprint": fp, "device_name": "d", "app_version": "3.4.0"})
        assert activate.json()["price"] == 888
        assert activate.json()["is_early_bird"] is False
    finally:
        srv.close()


def test_set_early_bird_on_existing_license_locks_current_price() -> None:
    srv = make_test_server()
    try:
        db = srv.db()
        result = admin_license_service.create_license(db, "test-admin", is_early_bird=False, duration_days=30)
        license_id = result.license.license_id

        admin_license_service.set_early_bird(db, "test-admin", license_id, True)
        db.close()

        fp = "fp-" + "d" * 20
        activate = srv.client.post("/api/license/activate", json={"license_key": result.plaintext_key, "device_fingerprint": fp, "device_name": "d", "app_version": "3.4.0"})
        assert activate.json()["is_early_bird"] is True
        assert activate.json()["price"] == 688  # 建立時的全域價格（預設值）
    finally:
        srv.close()


def test_disable_early_bird_reverts_to_global_price() -> None:
    srv = make_test_server()
    try:
        db = srv.db()
        result = admin_license_service.create_license(db, "test-admin", is_early_bird=True, duration_days=30)
        license_id = result.license.license_id
        update_product_settings(db, current_monthly_price=888)

        admin_license_service.set_early_bird(db, "test-admin", license_id, False)
        db.close()

        fp = "fp-" + "e" * 20
        activate = srv.client.post("/api/license/activate", json={"license_key": result.plaintext_key, "device_fingerprint": fp, "device_name": "d", "app_version": "3.4.0"})
        assert activate.json()["is_early_bird"] is False
        assert activate.json()["price"] == 888
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
