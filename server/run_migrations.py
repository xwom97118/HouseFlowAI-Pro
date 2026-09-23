"""CLI 包裝：跑 `alembic upgrade head`（規格第 3、24 節）。

給 Render 的 preDeployCommand（或任何手動的部署前置步驟）用：

    python server/run_migrations.py

底層邏輯全部在 server/app/database.py 的 run_migrations()——這支腳本
只是給部署流程一個穩定的命令列進入點，不重複任何邏輯。任何一個
migration 失敗，Alembic 本身就會讓這個腳本以非 0 結束碼結束（不會
silent continue），部署平台會因此判定這次部署失敗，不會把有問題的
版本切換上線。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.app.database import run_migrations  # noqa: E402


def main() -> int:
    print("[HouseFlow License Server] 開始執行 migration...")
    run_migrations()
    print("[HouseFlow License Server] migration 完成，資料庫已經是最新 schema。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
