"""CSRF 保護 + Admin 登入 brute-force 防護的回歸測試（2026-09-23
Phase 3A，規格第 9、10 節）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from server.app.csrf import generate_csrf_token, verify_csrf_token  # noqa: E402
from server.app.middleware import admin_login_rate_limiter  # noqa: E402
from server.app.services.admin_auth_service import (  # noqa: E402
    MAX_FAILED_LOGIN_ATTEMPTS,
    authenticate,
    create_admin_user,
)
from server.app.services.errors import AdminAuthError  # noqa: E402
from server.tests._helpers import make_test_server  # noqa: E402


def _login(srv, username: str, password: str):
    admin_login_rate_limiter.reset()
    return srv.client.post("/admin/login", data={"username": username, "password": password}, follow_redirects=False)


def _get_csrf_token_from_page(srv, path: str) -> str:
    resp = srv.client.get(path)
    html = resp.text
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    end = html.index('"', start)
    return html[start:end]


# ---------------------------------------------------------------------------
# CSRF：純函式層
# ---------------------------------------------------------------------------


def test_csrf_token_deterministic_for_same_session() -> None:
    token_a = generate_csrf_token("session-abc")
    token_b = generate_csrf_token("session-abc")
    assert token_a == token_b


def test_csrf_token_differs_for_different_sessions() -> None:
    assert generate_csrf_token("session-1") != generate_csrf_token("session-2")


def test_csrf_verify_accepts_matching_token() -> None:
    token = generate_csrf_token("session-xyz")
    assert verify_csrf_token("session-xyz", token) is True


def test_csrf_verify_rejects_wrong_token() -> None:
    assert verify_csrf_token("session-xyz", "not-the-real-token") is False


def test_csrf_verify_rejects_empty() -> None:
    assert verify_csrf_token("", "") is False
    assert verify_csrf_token("session-xyz", "") is False


# ---------------------------------------------------------------------------
# CSRF：透過真正的 Admin HTTP route
# ---------------------------------------------------------------------------


def test_create_license_without_csrf_token_rejected() -> None:
    srv = make_test_server()
    try:
        db = srv.db()
        create_admin_user(db, "csrftest", "correct horse battery staple")
        db.close()
        _login(srv, "csrftest", "correct horse battery staple")

        # 完全不帶 csrf_token 欄位 -> FastAPI 因為缺少必填欄位回 422，
        # 不會走到任何真正的建立邏輯。
        resp = srv.client.post(
            "/admin/licenses/new",
            data={"plan": "professional", "duration_days": "30", "device_limit": "1"},
            follow_redirects=False,
        )
        assert resp.status_code == 422
    finally:
        srv.close()


def test_create_license_with_wrong_csrf_token_redirects_to_login() -> None:
    srv = make_test_server()
    try:
        db = srv.db()
        create_admin_user(db, "csrftest2", "correct horse battery staple")
        db.close()
        _login(srv, "csrftest2", "correct horse battery staple")

        resp = srv.client.post(
            "/admin/licenses/new",
            data={"csrf_token": "totally-forged-token", "plan": "professional", "duration_days": "30", "device_limit": "1"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/admin/login" in resp.headers["location"]

        # 而且確定沒有真的建立任何 License
        licenses_resp = srv.client.get("/admin/licenses")
        assert "License 清單（0）" in licenses_resp.text
    finally:
        srv.close()


def test_create_license_with_correct_csrf_token_succeeds() -> None:
    srv = make_test_server()
    try:
        db = srv.db()
        create_admin_user(db, "csrftest3", "correct horse battery staple")
        db.close()
        _login(srv, "csrftest3", "correct horse battery staple")

        token = _get_csrf_token_from_page(srv, "/admin/licenses/new")
        resp = srv.client.post(
            "/admin/licenses/new",
            data={"csrf_token": token, "plan": "professional", "duration_days": "30", "device_limit": "1"},
            follow_redirects=False,
        )
        assert resp.status_code == 200
        assert "建立成功" in resp.text
    finally:
        srv.close()


def test_csrf_token_from_stale_session_rejected_after_relogin() -> None:
    """CSRF token 是跟 session token 綁定的——重新登入之後（拿到新的
    session），舊的 csrf_token 應該就不再有效。"""
    srv = make_test_server()
    try:
        db = srv.db()
        create_admin_user(db, "csrftest4", "correct horse battery staple")
        db.close()

        _login(srv, "csrftest4", "correct horse battery staple")
        old_token = _get_csrf_token_from_page(srv, "/admin/licenses/new")

        srv.client.get("/admin/logout")
        _login(srv, "csrftest4", "correct horse battery staple")  # 拿到新 session

        resp = srv.client.post(
            "/admin/licenses/new",
            data={"csrf_token": old_token, "plan": "professional", "duration_days": "30", "device_limit": "1"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/admin/login" in resp.headers["location"]
    finally:
        srv.close()


# ---------------------------------------------------------------------------
# 登入 brute-force 防護
# ---------------------------------------------------------------------------


def test_account_locks_after_max_failed_attempts() -> None:
    srv = make_test_server()
    try:
        db = srv.db()
        create_admin_user(db, "lockouttest", "correct horse battery staple")

        for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
            try:
                authenticate(db, "lockouttest", "wrong-password")
                raise AssertionError("expected AdminAuthError")
            except AdminAuthError:
                pass

        # 現在即使密碼正確，也應該因為帳號被鎖定而拒絕
        try:
            authenticate(db, "lockouttest", "correct horse battery staple")
            raise AssertionError("expected AdminAuthError due to lockout")
        except AdminAuthError as exc:
            assert "鎖定" in str(exc)
        db.close()
    finally:
        srv.close()


def test_successful_login_resets_failed_count() -> None:
    srv = make_test_server()
    try:
        db = srv.db()
        create_admin_user(db, "lockouttest2", "correct horse battery staple")

        try:
            authenticate(db, "lockouttest2", "wrong")
        except AdminAuthError:
            pass

        admin = authenticate(db, "lockouttest2", "correct horse battery staple")
        assert admin.failed_login_count == 0
        db.close()
    finally:
        srv.close()


def test_lockout_error_message_does_not_reveal_which_field_was_wrong() -> None:
    """規格第 10 節：不要洩漏帳號是否存在。"""
    srv = make_test_server()
    try:
        db = srv.db()
        create_admin_user(db, "realuser", "correct horse battery staple")

        error_for_wrong_password = None
        error_for_nonexistent_user = None
        try:
            authenticate(db, "realuser", "wrong-password-here")
        except AdminAuthError as exc:
            error_for_wrong_password = str(exc)
        try:
            authenticate(db, "nonexistent-user-xyz", "whatever-password")
        except AdminAuthError as exc:
            error_for_nonexistent_user = str(exc)

        assert error_for_wrong_password == error_for_nonexistent_user
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
