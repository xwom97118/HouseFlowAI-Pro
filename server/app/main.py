"""HouseFlow License Server + Admin — FastAPI 進入點（2026-09-22 Phase
2，2026-09-23 Phase 3A 補強：正式環境啟動流程、health/readiness、
CORS、structured logging、全域例外處理、rate limiting）。

Phase 2 刻意讓 License API（/trial、/license/…）和 Admin UI
（/admin/…）跑在同一個 process 裡，方便本機開發環境一個指令啟動、
一次驗收完整流程；兩者在程式碼層完全分離（不同 router、不同 service
呼叫路徑、Admin 永遠不直接碰 SQLAlchemy），Phase 3 如果要拆成兩個
獨立部署的服務，只需要把這裡的兩個 include_router 拆到兩個 app，
不需要改動 server/app/services/ 底下任何邏輯。

啟動方式（本機開發）：

    uvicorn server.app.main:app --reload --port 8000

正式環境啟動方式（見 docs/RENDER_DEPLOYMENT.md）：

    uvicorn server.app.main:app --host 0.0.0.0 --port $PORT

不加 --reload（正式環境不應該監看檔案變更自動重啟）。啟動前必須先用
server/bootstrap_admin.py 建立第一個 Admin 帳號，沒有任何預設帳密。
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from server.app.admin_ui.routes import router as admin_ui_router
from server.app.api.license_routes import router as license_router
from server.app.config import get_settings
from server.app.database import SessionLocal, init_db, run_migrations
from server.app.logging_config import configure_logging, get_logger, log_event
from server.app.middleware import LicenseAPIRateLimitMiddleware, RequestIDMiddleware
from server.app.version import SERVER_VERSION

app = FastAPI(title="HouseFlow License Server", version=SERVER_VERSION)


@app.on_event("startup")
def _on_startup() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = get_logger()

    if settings.skip_startup_db_init:
        # 測試環境（見 server/tests/_live_server.py）已經自己處理好
        # 資料庫，這裡不要再動不相干的預設 DB（見 config.py
        # skip_startup_db_init 的說明）。
        logger.info("startup_db_init_skipped")
    elif settings.is_production:
        # 正式環境：一律走 Alembic migration，不用
        # Base.metadata.create_all()——沒有版本記錄，沒辦法安全處理
        # 「已經有資料的正式資料庫要怎麼升級」（見 database.py
        # run_migrations() 的說明）。
        run_migrations()
        logger.info("startup_migrations_applied")
    else:
        # 本機開發：create_all() 圖方便，跟 Phase 2 行為一致。
        init_db()
        logger.info("startup_dev_db_initialized")

    if not settings.require_https:
        print(
            "[HouseFlow License Server] 目前允許 HTTP（本機開發用）。"
            "正式部署前必須設定 HOUSEFLOW_LICENSE_REQUIRE_HTTPS=1 並透過 HTTPS 提供服務。"
        )


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

app.add_middleware(RequestIDMiddleware)
app.add_middleware(LicenseAPIRateLimitMiddleware)

# CORS：HouseFlow Desktop 是 native client（用 httpx 發請求），不是
# 瀏覽器裡的 SPA——CORS 本來就只限制「瀏覽器」發出的跨來源請求，對
# httpx 完全沒有作用。這裡的 CORS 設定只跟「有沒有人打算從瀏覽器 JS
# 呼叫這個 API」有關；目前沒有這個需求，所以用最小權限（只允許
# APP_BASE_URL 這一個來源，沒有設定就不允許任何跨來源請求），不用
# "*"（規格第 13 節）。
_settings_for_cors = get_settings()
_cors_origins = [_settings_for_cors.app_base_url] if _settings_for_cors.app_base_url else []
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# 全域例外處理（規格第 14 節）：不把 traceback/SQL/檔案路徑/環境變數
# 回傳給 client，只回傳穩定的 error code + 人類看得懂的訊息；完整細節
# 進 log（server 端保留，不對外）。
# ---------------------------------------------------------------------------


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    log_event(
        "unhandled_exception",
        level="error",
        request_id=request_id,
        path=request.url.path,
        exception_type=type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error_code": "internal_error",
            "detail": "伺服器發生非預期錯誤，請稍後再試。",
            "request_id": request_id,
        },
    )


# ---------------------------------------------------------------------------
# Health / Readiness
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    """Liveness：process 本身有沒有活著。刻意不碰資料庫、不回傳任何
    設定值——只回答「這個 process 還在跑」這一個問題（規格第 5 節：
    「只能回傳必要資訊」）。
    """
    return {"status": "ok", "service": "houseflow-license-server", "version": SERVER_VERSION}


@app.get("/health/ready")
def health_ready() -> JSONResponse:
    """Readiness：資料庫連得上、查得到資料才算 ready。任何失敗原因
    （連線字串錯、DB 掛了、密碼錯）一律回傳同一句話，不把
    DATABASE_URL／SQL／exception 訊息暴露給呼叫端；真正的原因只寫進
    server log。
    """
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()
        return JSONResponse(status_code=200, content={"status": "ready"})
    except Exception as exc:  # noqa: BLE001
        log_event("readiness_check_failed", level="error", exception_type=type(exc).__name__)
        return JSONResponse(status_code=503, content={"status": "not_ready"})


app.include_router(license_router, prefix="/api")
app.include_router(admin_ui_router)
