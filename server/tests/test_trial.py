"""Trial 相關回歸測試（2026-09-22 Phase 2，規格第 6、28 節）：開始試用、
同一裝置重複試用被拒絕、試用到期後 verify 回傳 invalid。
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from server.tests._helpers import make_test_server  # noqa: E402


def test_trial_start_returns_valid_trial_state() -> None:
    srv = make_test_server()
    try:
        resp = srv.client.post(
            "/api/trial/start",
            json={"device_fingerprint": "fp-" + "a" * 20, "device_name": "device-a", "app_version": "3.4.0"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is True
        assert body["status"] == "trial"
        assert body["license_id"]
        assert body["trial_ends_at"] is not None
    finally:
        srv.close()


def test_trial_second_attempt_same_device_rejected() -> None:
    srv = make_test_server()
    try:
        fp = "fp-" + "b" * 20
        first = srv.client.post("/api/trial/start", json={"device_fingerprint": fp, "device_name": "d1", "app_version": "3.4.0"})
        assert first.status_code == 200

        second = srv.client.post("/api/trial/start", json={"device_fingerprint": fp, "device_name": "d1-again", "app_version": "3.4.0"})
        assert second.status_code == 409
    finally:
        srv.close()


def test_trial_survives_even_if_license_row_would_be_deleted() -> None:
    """規格第 6 節：即使「刪除 HouseFlow / 刪除 SQLite / 重新安裝」，也
    不能單靠這樣拿到第二次試用——這裡驗證 TrialFingerprint 記錄獨立於
    License 本身存在，就算 license 列被砍掉，試用資格判斷依然正確。
    """
    from server.app.models.license import License

    srv = make_test_server()
    try:
        fp = "fp-" + "c" * 20
        first = srv.client.post("/api/trial/start", json={"device_fingerprint": fp, "device_name": "d1", "app_version": "3.4.0"})
        assert first.status_code == 200

        db = srv.db()
        db.query(License).delete()
        db.commit()
        db.close()

        second = srv.client.post("/api/trial/start", json={"device_fingerprint": fp, "device_name": "d1", "app_version": "3.4.0"})
        assert second.status_code == 409
    finally:
        srv.close()


def test_different_devices_can_each_start_a_trial() -> None:
    srv = make_test_server()
    try:
        r1 = srv.client.post("/api/trial/start", json={"device_fingerprint": "fp-" + "d" * 20, "device_name": "d1", "app_version": "3.4.0"})
        r2 = srv.client.post("/api/trial/start", json={"device_fingerprint": "fp-" + "e" * 20, "device_name": "d2", "app_version": "3.4.0"})
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["license_id"] != r2.json()["license_id"]
    finally:
        srv.close()


def test_trial_expiration_makes_verify_invalid() -> None:
    from server.app.models.license import License

    srv = make_test_server()
    try:
        fp = "fp-" + "f" * 20
        start_resp = srv.client.post("/api/trial/start", json={"device_fingerprint": fp, "device_name": "d1", "app_version": "3.4.0"})
        license_id = start_resp.json()["license_id"]

        db = srv.db()
        license_row = db.query(License).filter_by(license_id=license_id).first()
        license_row.trial_ends_at = license_row.trial_ends_at - timedelta(days=8)
        license_row.trial_started_at = license_row.trial_started_at - timedelta(days=8)
        db.commit()
        db.close()

        verify_resp = srv.client.post("/api/license/verify", json={"license_id": license_id, "device_fingerprint": fp, "app_version": "3.4.0"})
        assert verify_resp.status_code == 200
        body = verify_resp.json()
        assert body["valid"] is False
        assert body["status"] == "expired"
    finally:
        srv.close()


def test_trial_response_never_includes_property_or_crm_fields() -> None:
    """規格第 27 節：License Server 完全不接收/回傳 Property/CRM/
    Facebook 相關資料——這裡確認回應裡沒有任何這類欄位名稱。
    """
    srv = make_test_server()
    try:
        resp = srv.client.post(
            "/api/trial/start",
            json={"device_fingerprint": "fp-" + "g" * 20, "device_name": "d1", "app_version": "3.4.0"},
        )
        body = resp.json()
        forbidden_keys = {"property", "properties", "crm", "facebook_cookie", "schedule", "images"}
        assert not (set(body.keys()) & forbidden_keys)
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
