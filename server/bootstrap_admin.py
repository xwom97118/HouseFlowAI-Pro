"""明確的 Admin 帳號建立指令（2026-09-22 Phase 2，規格第 14 節）。

HouseFlow Admin 沒有任何預設帳密、沒有 admin/admin。第一個 Admin 帳號
必須透過這支腳本手動建立，密碼只能來自環境變數或互動輸入，兩者都不會
被 commit 進原始碼或印在稽核紀錄裡。

用法：

    # 方式一：互動輸入密碼（不會顯示在終端機、不會留在 shell 歷史）
    python server/bootstrap_admin.py --username admin

    # 方式二：從環境變數帶入（適合腳本化/CI，但要自己注意不要把密碼
    # 留在 shell 歷史紀錄或 log 裡）
    HOUSEFLOW_ADMIN_BOOTSTRAP_PASSWORD=xxxx python server/bootstrap_admin.py --username admin --from-env
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.app.database import SessionLocal, init_db  # noqa: E402
from server.app.services.admin_auth_service import create_admin_user  # noqa: E402
from server.app.services.errors import AdminAuthError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="建立 HouseFlow Admin 的第一個帳號。")
    parser.add_argument("--username", required=True, help="Admin 使用者名稱")
    parser.add_argument(
        "--from-env",
        action="store_true",
        help="從環境變數 HOUSEFLOW_ADMIN_BOOTSTRAP_PASSWORD 讀取密碼，而不是互動輸入",
    )
    args = parser.parse_args()

    if args.from_env:
        password = os.environ.get("HOUSEFLOW_ADMIN_BOOTSTRAP_PASSWORD", "")
        if not password:
            print("錯誤：--from-env 但環境變數 HOUSEFLOW_ADMIN_BOOTSTRAP_PASSWORD 是空的。", file=sys.stderr)
            return 1
    else:
        password = getpass.getpass(f"為 Admin 帳號「{args.username}」設定密碼（至少 12 個字元）：")
        confirm = getpass.getpass("再輸入一次確認：")
        if password != confirm:
            print("錯誤：兩次輸入的密碼不一致。", file=sys.stderr)
            return 1

    init_db()
    db = SessionLocal()
    try:
        admin = create_admin_user(db, args.username, password)
        print(f"已建立 Admin 帳號：{admin.username}（建立時間：{admin.created_at}）")
        return 0
    except AdminAuthError as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
