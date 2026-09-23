"""HouseFlow Admin 網頁介面（2026-09-22 Phase 2，2026-09-23 Phase 3A
補強：CSRF、登入 rate limit）。

刻意用 server-rendered Jinja2 頁面＋一般 HTML form（不是 SPA），
Phase 2 的目標是「必須實際可用」而不是「漂亮到 production marketing
site」，避免多引入一整套前端框架/建置流程。

每一個會改變 License/Device/Settings 狀態的 route，都透過
server/app/services/ 底下的函式操作（帶入 admin.username 供稽核紀錄
使用），這個檔案本身不直接寫任何 SQLAlchemy 寫入邏輯。

所有會修改資料的 POST route 都要求一個跟目前 session 綁定的
csrf_token（見 server/app/csrf.py）——`require_admin_and_csrf()` 一次
處理「有沒有登入」+「CSRF token 對不對」，驗證失敗一律導回登入頁，
不區分兩種失敗原因（避免洩漏 session 存在與否的資訊）。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from server.app.admin_ui.auth import (
    clear_session_cookie,
    csrf_token_for,
    require_admin,
    require_admin_and_csrf,
    set_session_cookie,
)
from server.app.database import get_db
from server.app.middleware import admin_login_rate_limiter
from server.app.models.license import DeviceBinding, License
from server.app.services import admin_license_service, audit_service
from server.app.services.admin_auth_service import authenticate, create_session, invalidate_session
from server.app.services.errors import AdminAuthError, LicenseNotFoundError
from server.app.services.license_service import compute_effective_status
from server.app.services.product_settings_service import get_product_settings, update_product_settings

router = APIRouter(prefix="/admin", tags=["admin-ui"])

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _ctx(request: Request, **extra) -> dict:
    """共用的 template context 組合——自動帶入這個 request 對應的
    csrf_token，避免每個 route 都要手動加一行。"""
    base = {"csrf_token": csrf_token_for(request)}
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
# 登入 / 登出
# ---------------------------------------------------------------------------


@router.get("/login")
def login_page(request: Request, next: str = "/admin/"):
    return templates.TemplateResponse(request, "login.html", {"admin": None, "next": next})


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = "/admin/",
    db: Session = Depends(get_db),
):
    # 規格第 10 節：基本 brute-force 防護，除了 admin_auth_service 裡
    # 「單一帳號連續失敗鎖定」，這裡再加一層「單一來源 IP 短時間內
    # 大量嘗試不同帳號」的防護——兩者互補，各自防不同的攻擊模式。
    client_ip = request.client.host if request.client else "unknown"
    if not admin_login_rate_limiter.allow(client_ip):
        return RedirectResponse(url="/admin/login?err=嘗試次數過多，請稍後再試", status_code=303)

    try:
        admin = authenticate(db, username, password)
    except AdminAuthError as exc:
        return RedirectResponse(url=f"/admin/login?err={exc}", status_code=303)

    token = create_session(db, admin)
    response = RedirectResponse(url=next or "/admin/", status_code=303)
    set_session_cookie(response, token)
    return response


@router.get("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    # 登出用 GET 是刻意的：被 CSRF 強制登出頂多是騷擾（使用者要重新
    # 登入一次），不是真正的安全風險，不需要為了這個低風險動作要求
    # 使用者一定要透過表單登出。
    token = request.cookies.get("houseflow_admin_session", "")
    invalidate_session(db, token)
    response = RedirectResponse(url="/admin/login", status_code=303)
    clear_session_cookie(response)
    return response


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    if isinstance(admin, RedirectResponse):
        return admin

    counts = admin_license_service.dashboard_counts(db)
    return templates.TemplateResponse(
        request, "dashboard.html", _ctx(request, admin=admin, active="dashboard", counts=counts)
    )


# ---------------------------------------------------------------------------
# License 清單 / 搜尋
# ---------------------------------------------------------------------------


@router.get("/licenses")
def licenses_list(request: Request, q: str = "", status: str = "", db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    if isinstance(admin, RedirectResponse):
        return admin

    settings = get_product_settings(db)
    rows = []
    for license_row in admin_license_service.search_licenses(db, query=q, status=status):
        device_count = (
            db.query(DeviceBinding)
            .filter_by(license_pk=license_row.id, status="active")
            .count()
        )
        last_device = (
            db.query(DeviceBinding)
            .filter_by(license_pk=license_row.id)
            .order_by(DeviceBinding.last_verified_at.desc())
            .first()
        )
        effective_price = license_row.locked_price if license_row.is_early_bird else settings.current_monthly_price
        rows.append(
            {
                "license": license_row,
                "device_count": device_count,
                "last_verified_at": last_device.last_verified_at if last_device else None,
                "effective_price": effective_price,
                "effective_status": compute_effective_status(license_row),
            }
        )

    return templates.TemplateResponse(
        request,
        "licenses_list.html",
        _ctx(request, admin=admin, active="licenses", licenses=rows, query=q, status_filter=status),
    )


# ---------------------------------------------------------------------------
# License 建立
# ---------------------------------------------------------------------------


@router.get("/licenses/new")
def license_new_page(request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    if isinstance(admin, RedirectResponse):
        return admin
    return templates.TemplateResponse(
        request, "license_new.html", _ctx(request, admin=admin, active="new", created_key=None)
    )


@router.post("/licenses/new")
def license_new_submit(
    request: Request,
    csrf_token: str = Form(...),
    plan: str = Form("professional"),
    duration_days: int = Form(30),
    device_limit: int = Form(1),
    is_early_bird: str = Form(""),
    db: Session = Depends(get_db),
):
    admin = require_admin_and_csrf(request, db, csrf_token)
    if isinstance(admin, RedirectResponse):
        return admin

    result = admin_license_service.create_license(
        db,
        admin.username,
        plan=plan,
        is_early_bird=bool(is_early_bird),
        duration_days=duration_days,
        device_limit=device_limit,
    )
    return templates.TemplateResponse(
        request,
        "license_new.html",
        _ctx(
            request,
            admin=admin,
            active="new",
            created_key=result.plaintext_key,
            created_license_id=result.license.license_id,
        ),
    )


# ---------------------------------------------------------------------------
# License 詳細 + 操作
# ---------------------------------------------------------------------------


def _load_detail_context(request: Request, db: Session, admin, license_id: str) -> dict:
    license_row = db.query(License).filter_by(license_id=license_id).first()
    if license_row is None:
        raise LicenseNotFoundError(license_id)
    devices = (
        db.query(DeviceBinding)
        .filter_by(license_pk=license_row.id)
        .order_by(DeviceBinding.first_activated_at.desc())
        .all()
    )
    audit_entries = audit_service.list_for_license(db, license_id)
    return _ctx(
        request,
        admin=admin, active="licenses", license=license_row,
        devices=devices, audit_entries=audit_entries,
        effective_status=compute_effective_status(license_row),
    )


@router.get("/licenses/{license_id}")
def license_detail(request: Request, license_id: str, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    if isinstance(admin, RedirectResponse):
        return admin
    try:
        context = _load_detail_context(request, db, admin, license_id)
    except LicenseNotFoundError:
        return RedirectResponse(url="/admin/licenses?err=找不到這組 License", status_code=303)
    return templates.TemplateResponse(request, "license_detail.html", context)


@router.post("/licenses/{license_id}/extend")
def license_extend(
    request: Request, license_id: str, csrf_token: str = Form(...), days: int = Form(...), db: Session = Depends(get_db)
):
    admin = require_admin_and_csrf(request, db, csrf_token)
    if isinstance(admin, RedirectResponse):
        return admin
    admin_license_service.extend_license(db, admin.username, license_id, days)
    return RedirectResponse(url=f"/admin/licenses/{license_id}?msg=已延長 {days} 天", status_code=303)


@router.post("/licenses/{license_id}/suspend")
def license_suspend(request: Request, license_id: str, csrf_token: str = Form(...), db: Session = Depends(get_db)):
    admin = require_admin_and_csrf(request, db, csrf_token)
    if isinstance(admin, RedirectResponse):
        return admin
    admin_license_service.suspend_license(db, admin.username, license_id)
    return RedirectResponse(url=f"/admin/licenses/{license_id}?msg=已暫停", status_code=303)


@router.post("/licenses/{license_id}/resume")
def license_resume(request: Request, license_id: str, csrf_token: str = Form(...), db: Session = Depends(get_db)):
    admin = require_admin_and_csrf(request, db, csrf_token)
    if isinstance(admin, RedirectResponse):
        return admin
    admin_license_service.resume_license(db, admin.username, license_id)
    return RedirectResponse(url=f"/admin/licenses/{license_id}?msg=已恢復", status_code=303)


@router.post("/licenses/{license_id}/revoke")
def license_revoke(request: Request, license_id: str, csrf_token: str = Form(...), db: Session = Depends(get_db)):
    admin = require_admin_and_csrf(request, db, csrf_token)
    if isinstance(admin, RedirectResponse):
        return admin
    admin_license_service.revoke_license(db, admin.username, license_id)
    return RedirectResponse(url=f"/admin/licenses/{license_id}?msg=已撤銷", status_code=303)


@router.post("/licenses/{license_id}/early-bird")
def license_early_bird(
    request: Request, license_id: str, csrf_token: str = Form(...), enabled: str = Form(...), db: Session = Depends(get_db)
):
    admin = require_admin_and_csrf(request, db, csrf_token)
    if isinstance(admin, RedirectResponse):
        return admin
    admin_license_service.set_early_bird(db, admin.username, license_id, enabled == "1")
    return RedirectResponse(url=f"/admin/licenses/{license_id}?msg=已更新 Early Bird 設定", status_code=303)


@router.post("/licenses/{license_id}/set-expiration")
def license_set_expiration(
    request: Request, license_id: str, csrf_token: str = Form(...), expires_at: str = Form(...), db: Session = Depends(get_db)
):
    admin = require_admin_and_csrf(request, db, csrf_token)
    if isinstance(admin, RedirectResponse):
        return admin
    try:
        parsed = datetime.strptime(expires_at.strip(), "%Y-%m-%d")
    except ValueError:
        return RedirectResponse(url=f"/admin/licenses/{license_id}?err=日期格式錯誤，請用 YYYY-MM-DD", status_code=303)
    admin_license_service.set_expiration(db, admin.username, license_id, parsed)
    return RedirectResponse(url=f"/admin/licenses/{license_id}?msg=已設定到期日", status_code=303)


@router.post("/licenses/{license_id}/devices/{device_id}/deactivate")
def device_deactivate(
    request: Request, license_id: str, device_id: str, csrf_token: str = Form(...), db: Session = Depends(get_db)
):
    admin = require_admin_and_csrf(request, db, csrf_token)
    if isinstance(admin, RedirectResponse):
        return admin
    admin_license_service.deactivate_device(db, admin.username, license_id, device_id)
    return RedirectResponse(url=f"/admin/licenses/{license_id}?msg=已解除裝置綁定", status_code=303)


# ---------------------------------------------------------------------------
# Audit Log
# ---------------------------------------------------------------------------


@router.get("/audit")
def audit_log_page(request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    if isinstance(admin, RedirectResponse):
        return admin
    entries = audit_service.list_recent(db)
    return templates.TemplateResponse(request, "audit.html", _ctx(request, admin=admin, active="audit", entries=entries))


# ---------------------------------------------------------------------------
# Global Product Settings
# ---------------------------------------------------------------------------


@router.get("/settings")
def settings_page(request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    if isinstance(admin, RedirectResponse):
        return admin
    settings = get_product_settings(db)
    return templates.TemplateResponse(
        request, "settings.html", _ctx(request, admin=admin, active="settings", settings=settings)
    )


@router.post("/settings")
def settings_submit(
    request: Request,
    csrf_token: str = Form(...),
    current_monthly_price: int = Form(...),
    currency: str = Form(...),
    trial_days: int = Form(...),
    offline_grace_days: int = Form(...),
    latest_version: str = Form(...),
    minimum_supported_version: str = Form(...),
    db: Session = Depends(get_db),
):
    admin = require_admin_and_csrf(request, db, csrf_token)
    if isinstance(admin, RedirectResponse):
        return admin

    old = get_product_settings(db)
    old_snapshot = {
        "current_monthly_price": old.current_monthly_price, "trial_days": old.trial_days,
        "offline_grace_days": old.offline_grace_days, "latest_version": old.latest_version,
        "minimum_supported_version": old.minimum_supported_version,
    }
    # 規格第 23 節：全域漲價不能動到已經鎖定的 Early Bird 價格——
    # update_product_settings() 只改 ProductSettings 這張表，
    # License.locked_price 是每一組 License 各自獨立的欄位，兩者完全
    # 沒有關聯，所以這裡不需要、也不會去動任何一組 License 的
    # locked_price（已經由 test_pricing.py 的
    # test_global_price_change_does_not_affect_early_bird 驗證過）。
    update_product_settings(
        db,
        current_monthly_price=current_monthly_price,
        currency=currency,
        trial_days=trial_days,
        offline_grace_days=offline_grace_days,
        latest_version=latest_version,
        minimum_supported_version=minimum_supported_version,
    )
    new_snapshot = {
        "current_monthly_price": current_monthly_price, "trial_days": trial_days,
        "offline_grace_days": offline_grace_days, "latest_version": latest_version,
        "minimum_supported_version": minimum_supported_version,
    }
    audit_service.record(db, admin.username, action="update_product_settings", old_value=old_snapshot, new_value=new_snapshot)

    return RedirectResponse(url="/admin/settings?msg=已儲存設定", status_code=303)
