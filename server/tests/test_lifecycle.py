"""License 生命週期回歸測試（2026-09-22 Phase 2，規格第 8、16、23、24、
28 節）：Active 驗證、到期、Suspend/Resume、Revoke、+30/+90/自訂天數
延長，全部透過 admin_license_service 直接操作＋API 驗證回應。
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from server.app.models.license import License  # noqa: E402
from server.app.services import admin_license_service  # noqa: E402
from server.app.timeutil import utc_now  # noqa: E402
from server.tests._helpers import make_test_server  # noqa: E402


def _create_and_activate(srv, duration_days: int = 30):
    db = srv.db()
    result = admin_license_service.create_license(db, "test-admin", duration_days=duration_days)
    key = result.plaintext_key
    license_id = result.license.license_id
    db.close()

    fp = "fp-" + "z" * 20
    resp = srv.client.post("/api/license/activate", json={"license_key": key, "device_fingerprint": fp, "device_name": "d1", "app_version": "3.4.0"})
    assert resp.status_code == 200
    return license_id, fp


def test_active_license_verifies_valid() -> None:
    srv = make_test_server()
    try:
        license_id, fp = _create_and_activate(srv)
        resp = srv.client.post("/api/license/verify", json={"license_id": license_id, "device_fingerprint": fp, "app_version": "3.4.0"})
        body = resp.json()
        assert body["valid"] is True
        assert body["status"] == "active"
        assert body["expires_at"] is not None
    finally:
        srv.close()


def test_expired_license_verifies_invalid() -> None:
    srv = make_test_server()
    try:
        license_id, fp = _create_and_activate(srv, duration_days=1)
        db = srv.db()
        license_row = db.query(License).filter_by(license_id=license_id).first()
        license_row.expires_at = utc_now() - timedelta(days=1)
        db.commit()
        db.close()

        resp = srv.client.post("/api/license/verify", json={"license_id": license_id, "device_fingerprint": fp, "app_version": "3.4.0"})
        body = resp.json()
        assert body["valid"] is False
        assert body["status"] == "expired"
    finally:
        srv.close()


def test_suspend_blocks_verification() -> None:
    srv = make_test_server()
    try:
        license_id, fp = _create_and_activate(srv)
        db = srv.db()
        admin_license_service.suspend_license(db, "test-admin", license_id)
        db.close()

        resp = srv.client.post("/api/license/verify", json={"license_id": license_id, "device_fingerprint": fp, "app_version": "3.4.0"})
        body = resp.json()
        assert body["valid"] is False
        assert body["status"] == "suspended"
    finally:
        srv.close()


def test_resume_restores_active_verification() -> None:
    srv = make_test_server()
    try:
        license_id, fp = _create_and_activate(srv)
        db = srv.db()
        admin_license_service.suspend_license(db, "test-admin", license_id)
        admin_license_service.resume_license(db, "test-admin", license_id)
        db.close()

        resp = srv.client.post("/api/license/verify", json={"license_id": license_id, "device_fingerprint": fp, "app_version": "3.4.0"})
        body = resp.json()
        assert body["valid"] is True
        assert body["status"] == "active"
    finally:
        srv.close()


def test_revoke_blocks_verification_permanently() -> None:
    srv = make_test_server()
    try:
        license_id, fp = _create_and_activate(srv)
        db = srv.db()
        admin_license_service.revoke_license(db, "test-admin", license_id)
        db.close()

        resp = srv.client.post("/api/license/verify", json={"license_id": license_id, "device_fingerprint": fp, "app_version": "3.4.0"})
        body = resp.json()
        assert body["valid"] is False
        assert body["status"] == "revoked"
    finally:
        srv.close()


def test_extend_30_days() -> None:
    srv = make_test_server()
    try:
        license_id, _ = _create_and_activate(srv, duration_days=30)
        db = srv.db()
        before = db.query(License).filter_by(license_id=license_id).first().expires_at
        admin_license_service.extend_license(db, "test-admin", license_id, 30)
        after = db.query(License).filter_by(license_id=license_id).first().expires_at
        db.close()
        assert (after - before).days == 30
    finally:
        srv.close()


def test_extend_90_days() -> None:
    srv = make_test_server()
    try:
        license_id, _ = _create_and_activate(srv, duration_days=30)
        db = srv.db()
        before = db.query(License).filter_by(license_id=license_id).first().expires_at
        admin_license_service.extend_license(db, "test-admin", license_id, 90)
        after = db.query(License).filter_by(license_id=license_id).first().expires_at
        db.close()
        assert (after - before).days == 90
    finally:
        srv.close()


def test_extend_custom_days() -> None:
    srv = make_test_server()
    try:
        license_id, _ = _create_and_activate(srv, duration_days=30)
        db = srv.db()
        before = db.query(License).filter_by(license_id=license_id).first().expires_at
        admin_license_service.extend_license(db, "test-admin", license_id, 17)
        after = db.query(License).filter_by(license_id=license_id).first().expires_at
        db.close()
        assert (after - before).days == 17
    finally:
        srv.close()


def test_extend_expired_license_reactivates_from_today() -> None:
    srv = make_test_server()
    try:
        license_id, fp = _create_and_activate(srv, duration_days=1)
        db = srv.db()
        license_row = db.query(License).filter_by(license_id=license_id).first()
        license_row.expires_at = utc_now() - timedelta(days=10)
        db.commit()

        admin_license_service.extend_license(db, "test-admin", license_id, 30)
        db.close()

        resp = srv.client.post("/api/license/verify", json={"license_id": license_id, "device_fingerprint": fp, "app_version": "3.4.0"})
        body = resp.json()
        assert body["valid"] is True
        assert body["status"] == "active"
    finally:
        srv.close()


def test_expiration_does_not_delete_license_row() -> None:
    """規格第 23 節：到期不刪任何資料——License 列本身應該還在，只是
    valid=False。"""
    srv = make_test_server()
    try:
        license_id, fp = _create_and_activate(srv, duration_days=1)
        db = srv.db()
        license_row = db.query(License).filter_by(license_id=license_id).first()
        license_row.expires_at = utc_now() - timedelta(days=1)
        db.commit()
        db.close()

        srv.client.post("/api/license/verify", json={"license_id": license_id, "device_fingerprint": fp, "app_version": "3.4.0"})

        db2 = srv.db()
        still_there = db2.query(License).filter_by(license_id=license_id).first()
        db2.close()
        assert still_there is not None
    finally:
        srv.close()


def test_effective_status_shows_expired_even_though_stored_status_is_active() -> None:
    """Admin 畫面（清單/詳細頁）在人工到期前，License.status 欄位
    仍然停在 "active"（沒有背景排程自動把它改掉）——這裡驗證
    compute_effective_status() 正確依日期回報「實際上已經到期」，
    不是照抄那個沒有自動更新的欄位。
    """
    from server.app.services.license_service import compute_effective_status

    srv = make_test_server()
    try:
        license_id, _ = _create_and_activate(srv, duration_days=1)
        db = srv.db()
        row = db.query(License).filter_by(license_id=license_id).first()
        row.expires_at = utc_now() - timedelta(days=1)
        db.commit()

        assert row.status == "active"  # 原始欄位沒被自動改動
        assert compute_effective_status(row) == "expired"  # 但有效狀態正確反映到期
        db.close()
    finally:
        srv.close()


def test_effective_status_respects_suspended_regardless_of_date() -> None:
    from server.app.services.license_service import compute_effective_status

    srv = make_test_server()
    try:
        license_id, _ = _create_and_activate(srv, duration_days=30)
        db = srv.db()
        admin_license_service.suspend_license(db, "test-admin", license_id)
        row = db.query(License).filter_by(license_id=license_id).first()
        assert compute_effective_status(row) == "suspended"
        db.close()
    finally:
        srv.close()


def test_search_licenses_status_filter_finds_effectively_expired() -> None:
    """搜尋「已到期」應該要找到「原始 status 還是 active、但
    expires_at 已經過去」的 License，這正是規格第 16 節 Admin 清單
    畫面要能正確呈現的情境。
    """
    srv = make_test_server()
    try:
        license_id, _ = _create_and_activate(srv, duration_days=1)
        db = srv.db()
        row = db.query(License).filter_by(license_id=license_id).first()
        row.expires_at = utc_now() - timedelta(days=1)
        db.commit()
        db.close()

        db2 = srv.db()
        expired_results = admin_license_service.search_licenses(db2, status="expired")
        active_results = admin_license_service.search_licenses(db2, status="active")
        db2.close()

        assert any(r.license_id == license_id for r in expired_results)
        assert not any(r.license_id == license_id for r in active_results)
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
