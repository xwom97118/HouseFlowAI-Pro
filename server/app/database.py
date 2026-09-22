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
    Base.metadata.create_all(bind=engine or _engine)


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
