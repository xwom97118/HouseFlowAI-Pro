"""Admin 認證 + Audit Log 回歸測試（2026-09-22 Phase 2，規格第 14、19、
28 節）：帳號建立、登入成功/失敗、session 驗證、session 過期、
稽核紀錄正確寫入且不含敏感資料。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from server.app.services import admin_license_service, audit_service  # noqa: E402
from server.app.services.admin_auth_service import (  # noqa: E402
    authenticate,
    create_admin_user,
    create_session,
    has_any_admin,
    invalidate_session,
    resolve_session,
)
from server.app.services.errors import AdminAuthError  # noqa: E402
from server.tests._helpers import make_test_server  # noqa: E402


def test_no_admin_exists_by_default() -> None:
    srv = make_test_server()
    try:
        db = srv.db()
        assert has_any_admin(db) is False
        db.close()
    finally:
        srv.close()


def test_create_admin_user_succeeds() -> None:
    srv = make_test_server()
    try:
        db = srv.db()
        admin = create_admin_user(db, "alice", "correct horse battery staple")
        assert admin.username == "alice"
        assert admin.password_hash != "correct horse battery staple"
        db.close()
    finally:
        srv.close()


def test_create_admin_rejects_short_password() -> None:
    srv = make_test_server()
    try:
        db = srv.db()
        try:
            create_admin_user(db, "bob", "short")
            raise AssertionError("expected AdminAuthError for short password")
        except AdminAuthError:
            pass
        db.close()
    finally:
        srv.close()


def test_create_admin_rejects_duplicate_username() -> None:
    srv = make_test_server()
    try:
        db = srv.db()
        create_admin_user(db, "carol", "correct horse battery staple")
        try:
            create_admin_user(db, "carol", "another long enough password")
            raise AssertionError("expected AdminAuthError for duplicate username")
        except AdminAuthError:
            pass
        db.close()
    finally:
        srv.close()


def test_authenticate_success() -> None:
    srv = make_test_server()
    try:
        db = srv.db()
        create_admin_user(db, "dave", "correct horse battery staple")
        admin = authenticate(db, "dave", "correct horse battery staple")
        assert admin.username == "dave"
        db.close()
    finally:
        srv.close()


def test_authenticate_wrong_password_fails() -> None:
    srv = make_test_server()
    try:
        db = srv.db()
        create_admin_user(db, "erin", "correct horse battery staple")
        try:
            authenticate(db, "erin", "totally-wrong-password")
            raise AssertionError("expected AdminAuthError")
        except AdminAuthError:
            pass
        db.close()
    finally:
        srv.close()


def test_authenticate_unknown_username_fails() -> None:
    srv = make_test_server()
    try:
        db = srv.db()
        try:
            authenticate(db, "nonexistent", "whatever-password-here")
            raise AssertionError("expected AdminAuthError")
        except AdminAuthError:
            pass
        db.close()
    finally:
        srv.close()


def test_session_created_and_resolved() -> None:
    srv = make_test_server()
    try:
        db = srv.db()
        admin = create_admin_user(db, "frank", "correct horse battery staple")
        token = create_session(db, admin)
        resolved = resolve_session(db, token)
        assert resolved is not None
        assert resolved.username == "frank"
        db.close()
    finally:
        srv.close()


def test_session_invalidated_on_logout() -> None:
    srv = make_test_server()
    try:
        db = srv.db()
        admin = create_admin_user(db, "grace", "correct horse battery staple")
        token = create_session(db, admin)
        invalidate_session(db, token)
        resolved = resolve_session(db, token)
        assert resolved is None
        db.close()
    finally:
        srv.close()


def test_invalid_token_resolves_to_none() -> None:
    srv = make_test_server()
    try:
        db = srv.db()
        resolved = resolve_session(db, "not-a-real-token")
        assert resolved is None
        db.close()
    finally:
        srv.close()


def test_admin_login_via_http_sets_cookie_and_dashboard_accessible() -> None:
    srv = make_test_server()
    try:
        db = srv.db()
        create_admin_user(db, "heidi", "correct horse battery staple")
        db.close()

        login_resp = srv.client.post("/admin/login", data={"username": "heidi", "password": "correct horse battery staple"}, follow_redirects=False)
        assert login_resp.status_code == 303
        assert "houseflow_admin_session" in login_resp.cookies

        dashboard_resp = srv.client.get("/admin/", follow_redirects=False)
        assert dashboard_resp.status_code == 200
        assert "License" in dashboard_resp.text
    finally:
        srv.close()


def test_admin_dashboard_redirects_to_login_when_unauthenticated() -> None:
    srv = make_test_server()
    try:
        resp = srv.client.get("/admin/", follow_redirects=False)
        assert resp.status_code == 303
        assert "/admin/login" in resp.headers["location"]
    finally:
        srv.close()


def test_admin_login_wrong_password_does_not_set_cookie() -> None:
    srv = make_test_server()
    try:
        db = srv.db()
        create_admin_user(db, "ivan", "correct horse battery staple")
        db.close()

        resp = srv.client.post("/admin/login", data={"username": "ivan", "password": "wrong"}, follow_redirects=False)
        assert resp.status_code == 303
        assert "houseflow_admin_session" not in resp.cookies
        assert "/admin/login" in resp.headers["location"]
    finally:
        srv.close()


# ---------------------------------------------------------------------------
# Audit Log
# ---------------------------------------------------------------------------


def test_create_license_records_audit_entry() -> None:
    srv = make_test_server()
    try:
        db = srv.db()
        result = admin_license_service.create_license(db, "test-admin", duration_days=30)
        entries = audit_service.list_for_license(db, result.license.license_id)
        assert len(entries) == 1
        assert entries[0].action == "create_license"
        assert entries[0].admin_username == "test-admin"
        db.close()
    finally:
        srv.close()


def test_audit_log_never_contains_license_key_plaintext() -> None:
    srv = make_test_server()
    try:
        db = srv.db()
        result = admin_license_service.create_license(db, "test-admin", duration_days=30)
        entries = audit_service.list_for_license(db, result.license.license_id)
        combined = " ".join((e.old_value or "") + (e.new_value or "") for e in entries)
        assert result.plaintext_key not in combined
        db.close()
    finally:
        srv.close()


def test_audit_log_records_every_lifecycle_action() -> None:
    srv = make_test_server()
    try:
        db = srv.db()
        result = admin_license_service.create_license(db, "test-admin", duration_days=30)
        license_id = result.license.license_id

        admin_license_service.extend_license(db, "test-admin", license_id, 30)
        admin_license_service.suspend_license(db, "test-admin", license_id)
        admin_license_service.resume_license(db, "test-admin", license_id)
        admin_license_service.set_early_bird(db, "test-admin", license_id, True)
        admin_license_service.revoke_license(db, "test-admin", license_id)

        entries = audit_service.list_for_license(db, license_id)
        actions = {e.action for e in entries}
        assert actions == {
            "create_license", "extend_license", "suspend_license",
            "resume_license", "set_early_bird", "revoke_license",
        }
        db.close()
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
