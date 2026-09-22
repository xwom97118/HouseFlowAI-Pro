"""Server 測試共用工具（2026-09-22 Phase 2）。每個測試都用一個獨立的
暫存 SQLite 檔案，透過 FastAPI 的 dependency_overrides 把 get_db 換成
指向這個暫存 DB 的 session——完全不會碰到 server/data/ 底下真正的
開發用資料庫。
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.app.database import get_db, init_db
from server.app.main import app


@dataclass
class TestServer:
    client: TestClient
    session_factory: sessionmaker
    db_path: str

    def db(self):
        return self.session_factory()

    def close(self) -> None:
        app.dependency_overrides.pop(get_db, None)
        try:
            os.remove(self.db_path)
        except OSError:
            pass


def make_test_server() -> TestServer:
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    os.remove(path)

    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    init_db(engine)
    # expire_on_commit=False：測試常常在呼叫 db.close() 之後還想讀
    # 剛剛建立的 ORM 物件（例如 result.license.is_early_bird）方便斷言
    # ——正式的 request-scoped session（見 database.py 的 get_db()）
    # 不用這個設定，因為正式流程一定在同一個 session 生命週期內就把
    # 資料序列化成 Pydantic response，不會有「session 關掉後還要讀
    # ORM 物件」的需求。
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    return TestServer(client=client, session_factory=session_factory, db_path=path)
