"""License Server 設定（2026-09-22 Phase 2，2026-09-23 擴充 Phase
3A）。全部透過環境變數注入，沒有任何密碼或密鑰寫死在原始碼裡（規格第
14、26 節）。完整清單與說明見 docs/PRODUCTION_ENVIRONMENT.md 與
.env.example。

刻意不引入 pydantic-settings——目前只有少數幾個設定值，用一個簡單的
dataclass 讀 os.environ 就足夠，不需要多一個依賴。
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

_SERVER_ROOT = Path(__file__).resolve().parent.parent


def _default_sqlite_url() -> str:
    data_dir = _SERVER_ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "license_server.db"
    return f"sqlite:///{db_path.as_posix()}"


def _resolve_database_url() -> str:
    # HOUSEFLOW_LICENSE_DB_URL：這個專案從 Phase 2 就在用的明確名稱。
    # DATABASE_URL：Render（以及大多數 PaaS）把 PostgreSQL 資料庫連結
    # 到 Web Service 時，會自動注入這個名稱的環境變數——沒有這個
    # fallback，部署到 Render 之後 App 會連錯資料庫（或連到 Phase 2
    # 的 SQLite 預設路徑），完全連不上真正配置好的 PostgreSQL。
    # HOUSEFLOW_LICENSE_DB_URL 優先，方便本機開發跟 Render 的自動注入
    # 分開設定、互不干擾。
    explicit = os.environ.get("HOUSEFLOW_LICENSE_DB_URL", "").strip()
    if explicit:
        return explicit
    render_provided = os.environ.get("DATABASE_URL", "").strip()
    if render_provided:
        return render_provided
    return _default_sqlite_url()


# get_settings() 每次呼叫都會建立一個新的 Settings()——如果自動產生的
# 臨時金鑰每次呼叫都重新 secrets.token_urlsafe() 一次，同一個 process
# 內的「產生 CSRF token」跟「驗證 CSRF token」會用到兩把不同的臨時
# 金鑰，永遠對不起來。這裡用一個 process 內的模組級快取，確保沒有明確
# 設定 HOUSEFLOW_SECRET_KEY 時，同一次啟動全程只產生、只使用同一把
# 臨時金鑰（重啟就會換一把新的，這是刻意的——不想讓臨時金鑰意外變成
# 事實上的固定值）。
_ephemeral_secret_key_cache: str | None = None


def _resolve_secret_key(environment: str) -> str:
    global _ephemeral_secret_key_cache

    explicit = os.environ.get("HOUSEFLOW_SECRET_KEY", "").strip()
    if explicit:
        return explicit
    if environment == "production":
        raise RuntimeError(
            "缺少環境變數 HOUSEFLOW_SECRET_KEY。正式環境（ENVIRONMENT=production）"
            "必須明確設定這個值（用於 CSRF token 等安全用途），不能使用自動產生的"
            "臨時金鑰——每次重啟都會不一樣，會讓所有現有 session/CSRF token 失效。"
        )
    if _ephemeral_secret_key_cache is None:
        # 開發環境：自動產生一個臨時的、僅供本次 process 使用的金鑰，
        # 並且明確警告——這跟「允許 HTTP」是同一種「本機開發圖方便，
        # 正式環境必須明確設定」的精神（規格第 26 節）。
        print(
            "[HouseFlow License Server] 未設定 HOUSEFLOW_SECRET_KEY，"
            "已自動產生一組僅供本次啟動使用的暫時金鑰（重啟後會失效，正式環境必須明確設定）。"
        )
        _ephemeral_secret_key_cache = secrets.token_urlsafe(32)
    return _ephemeral_secret_key_cache


@dataclass
class Settings:
    # 重要：每一個欄位都必須用 field(default_factory=lambda: ...)，
    # 不能寫成 `field: str = os.environ.get(...)`——後者這種寫法的
    # 預設值只會在 Settings 這個 class 第一次被定義（也就是這個模組
    # 第一次被 import）的當下算一次，之後不管呼叫幾次 Settings()、
    # 環境變數在中途被改成什麼，都不會反映出來。這個 bug 曾經讓
    # 「測試裡先改 os.environ 再建立 Settings() 期待看到新值」的測試
    # 全部失敗（get_settings() 每次呼叫都新建一個 Settings()，卻永遠
    # 讀到 import 當下的舊值）。
    environment: str = field(default_factory=lambda: os.environ.get("ENVIRONMENT", "development").strip().lower())

    # 見 docs/LICENSE_SERVER.md「資料庫選擇」一節：業務邏輯只透過
    # SQLAlchemy ORM 操作，DATABASE_URL 從 sqlite:/// 換成
    # postgresql+psycopg:// 就能切換到正式 PostgreSQL，不需要改
    # server/app/services/ 底下任何一行程式碼。
    database_url: str = field(default_factory=_resolve_database_url)

    admin_session_ttl_hours: int = field(
        default_factory=lambda: int(os.environ.get("HOUSEFLOW_ADMIN_SESSION_TTL_HOURS", "12"))
    )

    # Phase 2 只在 localhost 開發環境跑，允許 HTTP；正式部署前必須是
    # HTTPS（規格第 26 節）。這個旗標只用來在啟動時印出提醒/決定 cookie
    # 的 Secure 旗標，不做任何強制的 TLS 檢查（那是部署環境本身的
    # 責任）。
    require_https: bool = field(
        default_factory=lambda: os.environ.get("HOUSEFLOW_LICENSE_REQUIRE_HTTPS", "0").strip() == "1"
    )

    # 2026-09-23 Phase 3A：見 database.py run_migrations() /
    # server/tests/_live_server.py 的說明——測試用真正的 uvicorn 啟動
    # server 時，FastAPI startup event 照樣會觸發，這個旗標讓測試
    # 明確告訴 startup handler「DB 我自己已經處理好了，不要又跑一次
    # migration 動到不相干的預設 DB」。
    skip_startup_db_init: bool = field(
        default_factory=lambda: os.environ.get("HOUSEFLOW_LICENSE_SKIP_STARTUP_DB_INIT", "0").strip() == "1"
    )

    # CSRF token 產生用的密鑰（見 server/app/csrf.py）。正式環境必須
    # 明確設定，本機開發沒設定時會自動產生一組臨時的並印出警告。
    secret_key: str = field(default_factory=lambda: "")  # 由 __post_init__ 填入，這裡先佔位避免 dataclass 欄位順序問題

    app_base_url: str = field(default_factory=lambda: os.environ.get("APP_BASE_URL", "").strip())
    log_level: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO").strip().upper())

    # License 狀態簽章（見 server/app/services/signing_service.py，
    # 規格第 20 節）：Ed25519 私鑰，PEM 格式，用 base64 包一層方便放進
    # 環境變數（PEM 本身有換行字元，很多環境變數系統對多行值不友善）。
    # 正式環境必須明確設定；本機開發沒設定時，signing_service 會自動
    # 產生一組僅供本次啟動使用的臨時金鑰對並印出警告——這組臨時公鑰
    # 只在該次啟動的 log 裡看得到，不會被任何地方持久化，重啟就換了
    # 新的一組。
    license_signing_private_key_b64: str = field(
        default_factory=lambda: os.environ.get("HOUSEFLOW_LICENSE_SIGNING_PRIVATE_KEY", "").strip()
    )

    def __post_init__(self) -> None:
        if not self.secret_key:
            self.secret_key = _resolve_secret_key(self.environment)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


def get_settings() -> Settings:
    return Settings()
