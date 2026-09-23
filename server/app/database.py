"""SQLAlchemy engine / session（2026-09-22 Phase 2）。

Phase 2 用 SQLite（見 config.py），啟動時用
`Base.metadata.create_all()` 建表——這對「還沒有任何正式使用者資料」
的開發環境是安全、冪等的作法。正式要換成 PostgreSQL、且資料庫裡已經
有真實資料時，應該改用 Alembic 做版本化 migration（呼應 Desktop 端
app/services/db_migrations.py 同樣的「先建好架構、正式接上生產資料庫
前再決定」原則）——這是明確留給 Phase 3 的工作，Phase 2 的範圍只到
「架構上允許」，不包含真的導入 Alembic。
"""
from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from server.app.config import Settings, get_settings
from server.app.models.base import Base


def create_db_engine(settings: Settings | None = None):
    settings = settings or get_settings()
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    return create_engine(settings.database_url, connect_args=connect_args)


_engine = create_db_engine()
SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)


def init_db(engine=None) -> None:
    """給測試 / 一次性暫存資料庫使用：直接建表，不記錄 Alembic 版本。
    正式環境一律用 run_migrations()（見下）——不要在正式資料庫上呼叫
    這個函式，否則 Alembic 會不知道這個資料庫「已經是哪個版本」，
    之後跑 `alembic upgrade head` 會嘗試重新建立已經存在的 table 而
    失敗。
    """
    Base.metadata.create_all(bind=engine or _engine)


def run_migrations(database_url: str | None = None) -> None:
    """執行 `alembic upgrade head`（見 server/migrations/）。這是正式
    環境（production/staging）建表與升級 schema 的唯一管道——不用
    Base.metadata.create_all()，因為那個方式沒有版本記錄，沒辦法安全
    處理「已經有資料的正式資料庫要怎麼升級」這種情境（見規格第 3
    節）。

    fresh database（沒有任何 table）：從頭套用所有 migration，等同於
    建出完整的最新 schema。
    existing database（已經在某個版本）：只套用還沒套用過的
    migration，冪等——重複呼叫不會出錯、不會重複套用。
    任何一個 migration 失敗，Alembic 本身就會讓整個 upgrade 動作失敗
    並拋出例外（不會 silent continue），呼叫端（main.py 的 startup
    handler）不會吞掉這個例外。
    """
    from alembic import command
    from alembic.config import Config

    settings = get_settings()
    url = database_url or settings.database_url

    server_root = Path(__file__).resolve().parent.parent
    alembic_cfg = Config(str(server_root / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(server_root / "migrations"))
    alembic_cfg.set_main_option("sqlalchemy.url", url)

    command.upgrade(alembic_cfg, "head")


def get_session_factory(engine=None) -> sessionmaker:
    if engine is None:
        return SessionLocal
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency：每個請求一個 Session，結束後自動關閉。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
