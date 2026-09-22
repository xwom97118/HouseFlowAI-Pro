"""HouseFlow License Server + Admin — FastAPI 進入點（2026-09-22 Phase
2）。Phase 2 刻意讓 License API（/trial、/license/…）和 Admin UI
（/admin/…）跑在同一個 process 裡，方便本機開發環境一個指令啟動、
一次驗收完整流程；兩者在程式碼層完全分離（不同 router、不同 service
呼叫路徑、Admin 永遠不直接碰 SQLAlchemy），Phase 3 如果要拆成兩個
獨立部署的服務，只需要把這裡的兩個 include_router 拆到兩個 app，
不需要改動 server/app/services/ 底下任何邏輯。

啟動方式（本機開發）：

    uvicorn server.app.main:app --reload --port 8000

啟動前必須先用 server/bootstrap_admin.py 建立第一個 Admin 帳號，
沒有任何預設帳密。
"""
from __future__ import annotations

from fastapi import FastAPI

from server.app.admin_ui.routes import router as admin_ui_router
from server.app.api.license_routes import router as license_router
from server.app.config import get_settings
from server.app.database import init_db

app = FastAPI(title="HouseFlow License Server", version="0.1.0")


@app.on_event("startup")
def _on_startup() -> None:
    init_db()
    settings = get_settings()
    if not settings.require_https:
        print(
            "[HouseFlow License Server] 目前允許 HTTP（本機開發用）。"
            "正式部署前必須設定 HOUSEFLOW_LICENSE_REQUIRE_HTTPS=1 並透過 HTTPS 提供服務。"
        )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


app.include_router(license_router, prefix="/api")
app.include_router(admin_ui_router)
