"""在背景執行緒啟動一個真正的 uvicorn server（真正的 TCP，不是
ASGITransport 模擬），供：
1. test_http_license_provider.py 的一個端到端真實 HTTP 測試使用；
2. Phase 2 Source Mode Demonstration 使用——完全同一套機制，
   保證「demonstration 用的是真正在跑的 server」不是另一套邏輯。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import uvicorn
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.app.database import get_db, init_db
from server.app.main import app


@dataclass
class LiveTestServer:
    host: str
    port: int
    session_factory: sessionmaker
    db_path: str
    _server: uvicorn.Server
    _thread: threading.Thread

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def db(self):
        return self.session_factory()

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10)
        app.dependency_overrides.pop(get_db, None)


def start_live_test_server(host: str = "127.0.0.1", port: int = 8799, db_path: str | None = None) -> LiveTestServer:
    import os
    import tempfile

    if db_path is None:
        fd, db_path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(fd)
        os.remove(db_path)

    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    init_db(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("uvicorn test server did not start within 10 seconds")

    return LiveTestServer(host=host, port=port, session_factory=session_factory, db_path=db_path, _server=server, _thread=thread)
