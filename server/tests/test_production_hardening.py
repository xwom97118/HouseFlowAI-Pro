"""Production readiness 相關回歸測試（2026-09-23 Phase 3A，規格第 5、
11、14 節）：health/readiness endpoint、License API rate limiting、
全域例外處理不洩漏內部細節。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from server.app.middleware import RateLimiter, license_api_rate_limiter  # noqa: E402
from server.tests._helpers import make_test_server  # noqa: E402


def test_health_endpoint_returns_minimal_info() -> None:
    srv = make_test_server()
    try:
        resp = srv.client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "service" in body
        assert "version" in body
        # 規格第 5 節：不能暴露 DB password/DATABASE_URL/secret/license/admin data
        forbidden_substrings = ["password", "DATABASE_URL", "secret", "sqlite", "postgres"]
        body_text = str(body).lower()
        for token in forbidden_substrings:
            assert token.lower() not in body_text
    finally:
        srv.close()


def test_readiness_endpoint_succeeds_when_db_reachable() -> None:
    srv = make_test_server()
    try:
        resp = srv.client.get("/health/ready")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"
    finally:
        srv.close()


def test_readiness_endpoint_does_not_leak_exception_details_on_failure() -> None:
    """模擬 DB 查詢失敗（用一個會拋例外的假 db session factory 取代
    SessionLocal）——確認 /health/ready 回傳的內容裡沒有任何 exception
    訊息、SQL、檔案路徑。
    """
    import server.app.main as main_module

    class _BrokenSession:
        def execute(self, *a, **kw):
            raise RuntimeError("simulated: could not connect to host 10.0.0.5 user=admin password=hunter2")

        def close(self):
            pass

    original_session_local = main_module.SessionLocal
    main_module.SessionLocal = lambda: _BrokenSession()
    try:
        srv = make_test_server()
        try:
            resp = srv.client.get("/health/ready")
            assert resp.status_code == 503
            body_text = str(resp.json())
            assert "hunter2" not in body_text
            assert "10.0.0.5" not in body_text
            assert "RuntimeError" not in body_text
            assert resp.json()["status"] == "not_ready"
        finally:
            srv.close()
    finally:
        main_module.SessionLocal = original_session_local


def test_rate_limiter_allows_within_limit() -> None:
    limiter = RateLimiter(max_requests=3, window_seconds=60)
    assert limiter.allow("client-a") is True
    assert limiter.allow("client-a") is True
    assert limiter.allow("client-a") is True


def test_rate_limiter_blocks_beyond_limit() -> None:
    limiter = RateLimiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        assert limiter.allow("client-b") is True
    assert limiter.allow("client-b") is False


def test_rate_limiter_tracks_keys_independently() -> None:
    limiter = RateLimiter(max_requests=1, window_seconds=60)
    assert limiter.allow("client-x") is True
    assert limiter.allow("client-x") is False
    assert limiter.allow("client-y") is True  # 不同 key 互不影響


def test_license_api_rate_limit_enforced_on_trial_start() -> None:
    srv = make_test_server()
    try:
        license_api_rate_limiter.reset()
        for i in range(30):
            resp = srv.client.post(
                "/api/trial/start",
                json={"device_fingerprint": f"fp-rate-{i:03d}" + "x" * 10, "device_name": "d", "app_version": "3.4.0"},
            )
            assert resp.status_code in (200, 409)

        # 第 31 次（同一個 client IP，60 秒視窗內）應該被擋下
        blocked_resp = srv.client.post(
            "/api/trial/start",
            json={"device_fingerprint": "fp-rate-over-limit" + "y" * 10, "device_name": "d", "app_version": "3.4.0"},
        )
        assert blocked_resp.status_code == 429
        assert "Retry-After" in blocked_resp.headers
    finally:
        license_api_rate_limiter.reset()
        srv.close()


def test_unhandled_exception_returns_generic_error_without_traceback() -> None:
    """規格第 14 節：production API 不能把 traceback/SQL/檔案路徑/
    environment/internal exception 回傳給 client。用一個會在 route
    handler 內部拋出非預期例外的情境來驗證全域例外處理有正確接住。
    """
    from server.app.services import license_service as license_service_module

    original = license_service_module.verify_license

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated internal failure: /etc/secret/config.yaml unreadable")

    license_service_module.verify_license = _boom
    try:
        srv = make_test_server()
        try:
            # TestClient 預設 raise_server_exceptions=True 會把伺服器端
            # 未攔截的例外直接在測試裡重新拋出（方便平常寫測試時除錯），
            # 但這樣就繞過了真正在 production ASGI server 下會生效的
            # 全域例外處理——這裡特別關掉，才是在測「真正對外的行為」。
            from fastapi.testclient import TestClient

            client = TestClient(srv.client.app, raise_server_exceptions=False)
            resp = client.post(
                "/api/license/verify",
                json={"license_id": "does-not-matter", "device_fingerprint": "fp-" + "z" * 20, "app_version": "3.4.0"},
            )
            assert resp.status_code == 500
            body = resp.json()
            assert body["error_code"] == "internal_error"
            body_text = str(body)
            assert "/etc/secret" not in body_text
            assert "RuntimeError" not in body_text
            assert "Traceback" not in body_text
        finally:
            srv.close()
    finally:
        license_service_module.verify_license = original


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
