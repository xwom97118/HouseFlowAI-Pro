# Render Deployment — Step-by-Step (Phase 3B, not executed yet)

> Phase 3A（2026-09-23）：這份文件是寫給**未來**（Phase 3B）真正部署
> 到 Render 時照著做的步驟。本輪**完全沒有**建立 Render 帳號、
> Service、資料庫，也沒有花任何錢。[render.yaml](../render.yaml) 已經
> 準備好架構描述，但同樣還沒被套用到任何真正的 Render 帳號。

## 前置需求

- 一個 Render 帳號（Phase 3B 才建立）。
- 這個 repository 可以被 Render 存取（GitHub/GitLab 連結，或手動
  上傳）。
- 已經用 `python server/generate_signing_keypair.py` 產生好一組
  正式用的簽章金鑰對（不要沿用任何本機開發時看過的臨時金鑰）。
- 已經用 `python -c "import secrets; print(secrets.token_urlsafe(32))"`
  產生好一個正式用的 `HOUSEFLOW_SECRET_KEY`。

## 步驟

### 1. 建立 PostgreSQL 資料庫

Render Dashboard → New → PostgreSQL。

- Name：`houseflow-license-db`
- Region：選一個離主要使用者最近的（例如 Singapore）
- Plan：先用最小的（Starter 等級），流量成長再升級

建立完成後，記下 Render 自動產生的 Internal Database URL（等一下
連結 Web Service 時會自動注入，不需要手動複製貼上）。

### 2. 建立 Web Service

Render Dashboard → New → Web Service → 選這個 repository。

- Name：`houseflow-license-server`
- Root Directory：`server`
- Runtime：Python 3
- Build Command：`pip install -r requirements.txt`
- Pre-Deploy Command：`python run_migrations.py`
- Start Command：`uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Health Check Path：`/health`

（也可以用 `render.yaml` 這個 blueprint 檔案，讓 Render 直接照著建立
上面這些設定：Render Dashboard → New → Blueprint → 選這個
repository。這一輪只是把 blueprint 準備好，還沒有真的套用過。）

### 3. 連結資料庫到 Web Service

Web Service → Environment → Add from database → 選
`houseflow-license-db`。Render 會自動注入 `DATABASE_URL` 環境變數，
不需要手動輸入連線字串。

### 4. 設定環境變數

在 Web Service 的 Environment 分頁，逐一設定（完整清單見
[PRODUCTION_ENVIRONMENT.md](PRODUCTION_ENVIRONMENT.md)）：

```
ENVIRONMENT=production
HOUSEFLOW_SECRET_KEY=<步驟前置需求產生的值>
HOUSEFLOW_LICENSE_SIGNING_PRIVATE_KEY=<步驟前置需求產生的私鑰>
HOUSEFLOW_LICENSE_REQUIRE_HTTPS=1
APP_BASE_URL=<這個 Web Service 的正式網址，例如 https://houseflow-license-server.onrender.com，之後換成自訂 Domain 要記得更新>
LOG_LEVEL=INFO
```

**不要**把 `HOUSEFLOW_LICENSE_SIGNING_PRIVATE_KEY` 貼在任何 issue、
聊天記錄、commit message 裡——只貼進 Render 的 Environment 設定介面。

### 5. 部署

儲存環境變數之後 Render 會自動觸發一次部署：

1. `pip install -r requirements.txt`
2. `python run_migrations.py`（在全新資料庫上會套用所有 migration，
   建出完整 schema；如果之後又新增了 migration，只會套用還沒套用過
   的部分）
3. `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Render 打 `/health`，收到 200 才會把流量切過去

### 6. 建立第一個 Admin 帳號

Render 的 Shell 分頁（Web Service → Shell）：

```bash
python bootstrap_admin.py --username <你的帳號名稱>
```

會要求互動輸入密碼（Render Shell 支援互動輸入）。**這一步只做一次**
——`bootstrap_admin.py` 對已存在的帳號名稱會直接拒絕，不會覆蓋或
重設密碼（見 `server/app/services/admin_auth_service.create_admin_user`
與對應測試）。

### 7. 驗證

- `curl https://<你的網址>/health` → `{"status": "ok", ...}`
- `curl https://<你的網址>/health/ready` → `{"status": "ready"}`
- 瀏覽器開 `https://<你的網址>/admin/login`，用步驟 6 建立的帳號登入
- 確認 cookie 是 HTTPS-only（瀏覽器開發工具 → Application →
  Cookies → `Secure` 打勾）

### 8. 讓 Desktop 連上正式 Server

設定 Desktop 端環境變數（未來 Installer/設定介面決定怎麼分發，這一輪
先確認機制存在）：

```
HOUSEFLOW_LICENSE_SERVER_URL=https://<你的網址>
HOUSEFLOW_LICENSE_SERVER_PUBLIC_KEY=<步驟前置需求產生的公鑰>
```

### 9. 之後的部署（新版本上線）

Push 到連結的 git branch，Render 自動：build → 跑
`run_migrations.py`（冪等，只套用新的 migration）→ 起新的 process →
`/health` 通過才切流量 → 舊 process 才下線。任何一個 migration
失敗，部署會直接失敗、不會把有問題的版本切上線。

## 完整清單見

- [PRODUCTION_ENVIRONMENT.md](PRODUCTION_ENVIRONMENT.md) — 每個環境
  變數的細節
- [CLOUD_SECURITY.md](CLOUD_SECURITY.md) — 部署前的安全檢查
- [PHASE3B_DEPLOY_CHECKLIST.md](PHASE3B_DEPLOY_CHECKLIST.md) — 真正
  上線前需要人工完成的完整清單
