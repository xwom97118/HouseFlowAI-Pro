"""Phase 2 Source Mode Demonstration 的資料種子腳本（規格第 33
節）——建立 1 Trial / 1 Active / 1 Early Bird / 1 Expired / 1
Suspended，讓人工可以在 Admin 網頁上查看。只對這次 demo 用的獨立
SQLite 檔案操作，不是 production 資料。
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.app.database import SessionLocal, init_db  # noqa: E402
from server.app.services import admin_license_service  # noqa: E402
from server.app.services.license_service import start_trial  # noqa: E402
from server.app.timeutil import utc_now  # noqa: E402


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        # 1) Trial
        start_trial(db, device_fingerprint="demo-trial-device-fp", device_name="Demo Trial 裝置")

        # 2) Active Professional
        active = admin_license_service.create_license(
            db, "demo-seed", plan="professional", is_early_bird=False, duration_days=30, device_limit=1
        )
        print(f"Active License Key: {active.plaintext_key}")

        # 3) Early Bird Professional
        early_bird = admin_license_service.create_license(
            db, "demo-seed", plan="professional", is_early_bird=True, duration_days=365, device_limit=1
        )
        print(f"Early Bird License Key: {early_bird.plaintext_key}")

        # 4) Expired
        expired = admin_license_service.create_license(
            db, "demo-seed", plan="professional", is_early_bird=False, duration_days=1, device_limit=1
        )
        expired.license.expires_at = utc_now() - timedelta(days=5)
        db.commit()
        print(f"Expired License Key: {expired.plaintext_key}")

        # 5) Suspended
        suspended = admin_license_service.create_license(
            db, "demo-seed", plan="professional", is_early_bird=False, duration_days=30, device_limit=1
        )
        admin_license_service.suspend_license(db, "demo-seed", suspended.license.license_id)
        print(f"Suspended License Key: {suspended.plaintext_key}")

        print("\nDemo data seeded: 1 Trial, 1 Active, 1 Early Bird, 1 Expired, 1 Suspended.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
