"""License Server 設定（2026-09-22 Phase 2）。全部透過環境變數注入，
沒有任何密碼或密鑰寫死在原始碼裡（規格第 14、26 節）。

刻意不引入 pydantic-settings——目前只有少數幾個設定值，用一個簡單的
dataclass 讀 os.environ 就足夠，不需要多一個依賴。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_SERVER_ROOT = Path(__file__).resolve().parent.parent


def _default_sqlite_url() -> str:
    data_dir = _SERVER_ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "license_server.db"
    return f"sqlite:///{db_path.as_posix()}"


@dataclass
class Settings:
    # 見 docs/LICENSE_SERVER.md「資料庫選擇」一節：業務邏輯只透過
    # SQLAlchemy ORM 操作，DATABASE_URL 從 sqlite:/// 換成
    # postgresql+psycopg2:// 就能切換到正式 PostgreSQL，不需要改
    # server/app/services/ 底下任何一行程式碼。
    database_url: str = field(default_factory=lambda: os.environ.get("HOUSEFLOW_LICENSE_DB_URL", "").strip() or _default_sqlite_url())

    admin_session_ttl_hours: int = int(os.environ.get("HOUSEFLOW_ADMIN_SESSION_TTL_HOURS", "12"))

    # Phase 2 只在 localhost 開發環境跑，允許 HTTP；正式部署前必須是
    # HTTPS（規格第 26 節）。這個旗標只用來在啟動時印出提醒，不做任何
    # 強制的 TLS 檢查（那是部署環境的責任，不是這個 Phase 的範圍）。
    require_https: bool = os.environ.get("HOUSEFLOW_LICENSE_REQUIRE_HTTPS", "0").strip() == "1"


def get_settings() -> Settings:
    return Settings()
