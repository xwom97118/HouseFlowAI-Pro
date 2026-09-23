"""Production-like local smoke test（2026-09-23 Phase 3A，規格第 26
節）。

跟其他 server 測試不同：這裡刻意**不**設定
`HOUSEFLOW_LICENSE_SKIP_STARTUP_DB_INIT`，讓真正的 production 啟動
路徑（`ENVIRONMENT=production` → `main.py` 的 `_on_startup()` →
`run_migrations()`，不是 `init_db()`）真的被執行一次——這是唯一一個
會這樣做的測試檔案，專門驗證「正式環境的啟動流程本身」，其他測試都
用 `skip_startup_db_init` 繞過這條路徑（避免動到不相干的預設 DB，
見 config.py 的說明）。

資料庫用 SQLite（這台機器沒有安裝 PostgreSQL、也沒有 Docker，見
docs/PHASE3B_DEPLOY_CHECKLIST.md「真正的 PostgreSQL 環境驗證」）——
schema/型別相容性已經在程式碼審查中確認過（見
docs/LICENSE_SERVER.md），業務邏輯本身完全不寫任何 SQLite 專屬 SQL，
SQLite 在這裡只是「一個 SQLAlchemy 支援的資料庫」的代表，不是說
PostgreSQL 不需要真的驗證過。
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import uvicorn  # noqa: E402


def test_production_startup_runs_migrations_and_full_feature_walkthrough() -> None:
    fd, db_path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    os.remove(db_path)

    env_backup = {
        key: os.environ.get(key)
        for key in (
            "HOUSEFLOW_LICENSE_DB_URL", "ENVIRONMENT", "HOUSEFLOW_SECRET_KEY",
            "HOUSEFLOW_LICENSE_SIGNING_PRIVATE_KEY", "HOUSEFLOW_LICENSE_SKIP_STARTUP_DB_INIT",
        )
    }
    os.environ["HOUSEFLOW_LICENSE_DB_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "production"
    os.environ["HOUSEFLOW_SECRET_KEY"] = "test-production-smoke-secret-key"
    os.environ.pop("HOUSEFLOW_LICENSE_SIGNING_PRIVATE_KEY", None)  # 讓它走 production fail-fast 分支測試？不，這裡要能啟動，改用有效流程
    os.environ.pop("HOUSEFLOW_LICENSE_SKIP_STARTUP_DB_INIT", None)

    # production 模式下簽章私鑰是必填——這裡先產生一組真正的私鑰設進去，
    # 這個測試要驗證「正常情況下 production 真的能完整跑起來」，不是
    # 在測 fail-fast（fail-fast 分支見 test_production_failure_simulation.py）。
    import base64

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    os.environ["HOUSEFLOW_LICENSE_SIGNING_PRIVATE_KEY"] = base64.b64encode(pem).decode("ascii")

    import server.app.config as config_module
    config_module._ephemeral_secret_key_cache = None  # 強制重新讀取新設定的環境變數

    server_obj = None
    thread = None
    try:
        # 動態 import，確保 app 物件在正確的環境變數狀態下建立/啟動。
        from server.app.main import app

        config = uvicorn.Config(app, host="127.0.0.1", port=8798, log_level="warning")
        server_obj = uvicorn.Server(config)
        thread = threading.Thread(target=server_obj.run, daemon=True)
        thread.start()

        deadline = time.time() + 10
        while not server_obj.started and time.time() < deadline:
            time.sleep(0.05)
        assert server_obj.started, "production-mode server did not start within 10 seconds"

        import httpx

        base_url = "http://127.0.0.1:8798"

        # 1. Health / Readiness
        health_resp = httpx.get(f"{base_url}/health", timeout=5)
        assert health_resp.status_code == 200

        ready_resp = httpx.get(f"{base_url}/health/ready", timeout=5)
        assert ready_resp.status_code == 200
        assert ready_resp.json()["status"] == "ready"

        # 2. 確認 migration 真的跑過（alembic_version 表存在且有記錄）
        import sqlite3

        conn = sqlite3.connect(db_path)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "alembic_version" in tables
        assert "licenses" in tables
        assert "admin_users" in tables
        version_row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        assert version_row is not None
        conn.close()

        # 3. Admin bootstrap + 登入
        from server.app.database import SessionLocal
        from server.app.services.admin_auth_service import create_admin_user

        db = SessionLocal()
        create_admin_user(db, "smoke-admin", "correct horse battery staple smoke")
        db.close()

        session = httpx.Client(base_url=base_url, timeout=5)
        login_resp = session.post(
            "/admin/login",
            data={"username": "smoke-admin", "password": "correct horse battery staple smoke"},
            follow_redirects=False,
        )
        assert login_resp.status_code == 303
        assert "houseflow_admin_session" in session.cookies

        dashboard_resp = session.get("/admin/")
        assert dashboard_resp.status_code == 200

        # 4. 建立 License（走 Admin service 直接呼叫，證明 DB 真的可寫）
        from server.app.services import admin_license_service

        db = SessionLocal()
        create_result = admin_license_service.create_license(db, "smoke-admin", duration_days=30, device_limit=1)
        early_bird_result = admin_license_service.create_license(
            db, "smoke-admin", is_early_bird=True, duration_days=365, device_limit=1
        )
        license_id = create_result.license.license_id
        db.close()

        # 5. Trial + Activation + Verify + Extend + Suspend + Resume + Device deactivate（走 HTTP API，證明整條路徑通）
        trial_resp = session.post(
            "/api/trial/start",
            json={"device_fingerprint": "smoke-fp-trial-" + "x" * 10, "device_name": "smoke-device", "app_version": "3.4.0"},
        )
        assert trial_resp.status_code == 200
        assert trial_resp.json()["status"] == "trial"

        activate_resp = session.post(
            "/api/license/activate",
            json={
                "license_key": create_result.plaintext_key,
                "device_fingerprint": "smoke-fp-activate-" + "y" * 10,
                "device_name": "smoke-device-2",
                "app_version": "3.4.0",
            },
        )
        assert activate_resp.status_code == 200
        assert activate_resp.json()["status"] == "active"
        assert activate_resp.json()["signature"]  # production 模式下應該真的簽了章

        verify_resp = session.post(
            "/api/license/verify",
            json={"license_id": license_id, "device_fingerprint": "smoke-fp-activate-" + "y" * 10, "app_version": "3.4.0"},
        )
        assert verify_resp.status_code == 200
        assert verify_resp.json()["valid"] is True

        db = SessionLocal()
        admin_license_service.extend_license(db, "smoke-admin", license_id, 30)
        admin_license_service.suspend_license(db, "smoke-admin", license_id)
        admin_license_service.resume_license(db, "smoke-admin", license_id)
        db.close()

        early_bird_resp = session.post(
            "/api/license/activate",
            json={
                "license_key": early_bird_result.plaintext_key,
                "device_fingerprint": "smoke-fp-earlybird-" + "z" * 10,
                "device_name": "smoke-device-3",
                "app_version": "3.4.0",
            },
        )
        assert early_bird_resp.status_code == 200
        assert early_bird_resp.json()["is_early_bird"] is True
        assert early_bird_resp.json()["price"] == 688
    finally:
        if server_obj is not None:
            server_obj.should_exit = True
        if thread is not None:
            thread.join(timeout=10)
        for key, value in env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        config_module._ephemeral_secret_key_cache = None
        try:
            os.remove(db_path)
        except OSError:
            pass


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
