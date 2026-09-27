# HouseFlow License Server

> Phase 2（2026-09-22）＋ Phase 3A（2026-09-23 Cloud Readiness
> 補強）：本機開發環境的 License Server + Admin Control Plane。
> 目前**沒有**部署到公開網路，也沒有購買任何 Cloud 服務——這份文件
> 描述的是本機可以跑起來、可以驗收的架構，不是已經上線的服務。
> 真正部署的步驟見 [RENDER_DEPLOYMENT.md](RENDER_DEPLOYMENT.md)。

## 1. 這是什麼

HouseFlow License Server 負責且只負責：License、Trial、Subscription、
Device Binding、Pricing（含 Early Bird）、App Version metadata。

**完全不接收、不儲存**：物件資料、CRM 資料、排程內容、Facebook 貼文
內容、Facebook cookies/session、物件照片、客戶個資。這些資料永遠留在
Desktop 本機（見 [PRODUCT_V1_SPEC.md](PRODUCT_V1_SPEC.md) 第 10 節）。

## 2. 技術選擇

| 項目 | 選擇 | 理由 |
|---|---|---|
| API 框架 | FastAPI | HouseFlow Desktop 本身就是 Python；團隊維護成本最低，不需要學一套新語言/生態系。FastAPI 內建 Pydantic 驗證、自動產生 OpenAPI 文件、效能足夠這個規模使用。 |
| ORM | SQLAlchemy 2.0 | 業務邏輯（`server/app/services/`）只透過 ORM 操作，不寫任何 SQLite 專屬的 SQL。之後要換 PostgreSQL，只需要改 `DATABASE_URL` 連線字串（`sqlite:///...` → `postgresql+psycopg2://...`），不需要重寫任何一行 `server/app/services/` 底下的程式碼。 |
| 開發用資料庫 | SQLite（`server/data/license_server.db`，已加入 `.gitignore`） | Phase 2 只在本機開發環境使用，SQLite 零安裝、零設定。 |
| 正式資料庫 | PostgreSQL（Phase 3 決定何時導入） | 支援真正的併發寫入、正式部署的持久性與備份需求。 |
| 密碼／Session/License Key 雜湊 | Python 標準函式庫（`hashlib.scrypt` + `secrets`） | 見 [LICENSE_SECURITY.md](LICENSE_SECURITY.md)——刻意不引入 passlib/PyJWT，用官方推薦的 `secrets` 模組做 cryptographically secure random，用 `hashlib.scrypt`（Python 3.6+ 內建）做記憶體困難的密碼雜湊，減少依賴。 |
| Admin UI | FastAPI + Jinja2（server-rendered HTML + 一般 form） | Phase 2 的目標是「必須實際可用」，不是「漂亮到 production marketing site」。避免多引入一整套前端框架/建置流程；之後如果要做更豐富的 UI，可以在不動 API/Service 層的前提下換掉這一層。 |
| Migration | **Phase 3A：Alembic**（`server/migrations/`，`server/app/database.py` 的 `run_migrations()`） | 正式環境（`ENVIRONMENT=production`）啟動時跑 `alembic upgrade head`——有版本記錄，`existing database → upgrade → latest schema` 是安全、可測試的路徑（見 `server/tests/test_lifecycle.py` 的 migration 相關測試）。本機開發預設仍然用 `Base.metadata.create_all()`（`init_db()`）圖方便；測試環境用暫存 SQLite 檔案，兩者都不會跑到 Alembic 那條路徑，不會互相干擾。 |
| PostgreSQL 驅動 | `psycopg`（v3，`psycopg[binary]`） | 官方推薦的新一代驅動，binary extra 內建預編譯好的 libpq，Render 的 build 環境不需要另外裝系統層級的 PostgreSQL 開發套件。 |

## 3. Repository 結構

```
server/
├── app/
│   ├── main.py              FastAPI 進入點（License API + Admin UI 掛在同一個 process）
│   ├── config.py            環境變數設定
│   ├── database.py          SQLAlchemy engine/session + run_migrations()
│   ├── security.py          密碼/License Key/Session Token 雜湊
│   ├── csrf.py               Phase 3A：CSRF token 產生/驗證
│   ├── middleware.py         Phase 3A：request id、rate limiting
│   ├── logging_config.py     Phase 3A：結構化 logging
│   ├── timeutil.py          統一的 UTC 時間工具
│   ├── version.py            License Server 自己的版本號
│   ├── models/               SQLAlchemy ORM models
│   ├── schemas/               Pydantic request/response schema
│   ├── services/               核心商業邏輯（License/Admin/Audit/Auth/Signing）
│   ├── api/                   License API routes（給 Desktop 呼叫）
│   └── admin_ui/               Admin 網頁（Jinja2 templates + routes）
├── migrations/                Phase 3A：Alembic migration scripts
├── alembic.ini
├── bootstrap_admin.py        建立第一個 Admin 帳號的明確指令
├── run_migrations.py          Phase 3A：CLI 包裝，給部署流程用
├── generate_signing_keypair.py Phase 3A：產生 License 簽章金鑰對
├── .env.example                Phase 3A：環境變數清單（無真實值）
├── requirements.txt            Phase 3A：改為精確版本鎖定
└── tests/                     Server 端回歸測試（見 PHASE2_TEST_PLAN.md／PHASE3A 測試新增項目）
```

Desktop（`app/`）完全不變動既有結構；`server/` 是一個新的、獨立的
Python 套件，只透過 HTTP 跟 Desktop 溝通（見
[ARCHITECTURE.md](ARCHITECTURE.md)）。

## 4. License API（給 Desktop 呼叫）

Base path：`/api`（本機開發：`http://127.0.0.1:8000/api`）

| Method | Path | 用途 |
|---|---|---|
| POST | `/api/trial/start` | 開始 7 天試用 |
| POST | `/api/license/activate` | 用 License Key 啟用 |
| POST | `/api/license/verify` | 定期驗證目前授權狀態 |

三個 API 都回傳同一種形狀（`LicenseStateResponse`）：`valid` /
`status` / `message` / `license_id` / `plan` / `is_early_bird` /
`price` / `currency` / `trial_ends_at` / `expires_at` /
`offline_valid_until` / `server_time` / `minimum_supported_version` /
`latest_version` / `signature`（Phase 3A 新增，見第 6.1 節）。刻意不
回傳任何 internal id、hash 或其他不必要的內部資料。

錯誤回應對應的 HTTP 狀態碼：

| 情境 | Status |
|---|---|
| 同一裝置重複試用 | 409 |
| License Key 不存在 | 404 |
| License 已停權／已撤銷 | 403 |
| 裝置數已達上限 | 409 |
| 裝置未跟這組授權綁定（verify 時） | 403 |

Server 是 authority；Desktop 本機的快取只是離線時的 fallback 依據
（見第 6 節）。

## 5. Admin Control Plane

Base path：`/admin`（本機開發：`http://127.0.0.1:8000/admin`）。詳見
[ADMIN_CONTROL_PLANE.md](ADMIN_CONTROL_PLANE.md)。

## 6. 離線 7 天寬限期

`POST /api/license/verify` 的回應帶 `offline_valid_until`
（= 這次驗證成功的裝置 `last_verified_at` + `ProductSettings.offline_grace_days`）。
Desktop 端的 `HTTPLicenseProvider`（`app/services/license/http_provider.py`）：

1. 每次都先嘗試真的打一次 `/api/license/verify`。
2. 連得上：用 server 回傳的權威狀態更新本機快取，回傳給 UI。
3. 連不上（`httpx` 連線/逾時例外）：退回讀本機快取，跑
   `app.services.license.evaluation.evaluate_license()`（Phase 1
   就有、經過測試的純函式）計算「現在還在不在離線寬限期內」。

這代表離線寬限期的計算邏輯只有一份（`evaluate_license()`），
Desktop 端本機評估跟 Server 端計算 `offline_valid_until` 的邏輯
彼此一致，不會出現「Server 說還沒過期，Desktop 本機卻認為過期了」
的分歧。

### 6.1 Phase 3A：本機快取防篡改（License 狀態簽章）

離線 fallback 的前提是「本機快取的資料是可信的」——Phase 3A 補上
這個假設本身的防護：Server 用 Ed25519 私鑰對每次回應簽章，Desktop
驗證後才快取，離線時重新驗證快取內容的簽章。完整設計見
[CLOUD_SECURITY.md](CLOUD_SECURITY.md) 第 4 節。

## 7. 啟動方式

### 本機開發

```bash
# 1. 安裝依賴
python -m pip install -r server/requirements.txt

# 2. 建立第一個 Admin 帳號（沒有任何預設帳密）
python server/bootstrap_admin.py --username admin

# 3. 啟動 server（License API + Admin UI 都在這個 process）
uvicorn server.app.main:app --reload --port 8000
```

啟動後：
- License API：`http://127.0.0.1:8000/api/...`
- Admin UI：`http://127.0.0.1:8000/admin/`
- Health check：`http://127.0.0.1:8000/health`
- Readiness check：`http://127.0.0.1:8000/health/ready`

Desktop 端透過環境變數 `HOUSEFLOW_LICENSE_SERVER_URL` 指定要打哪個
License Server（預設 `http://127.0.0.1:8000`，見
`app/services/license/http_provider.py` 的 `DEFAULT_BASE_URL`）；正式
環境必須是 `https://`，只有 `http://127.0.0.1`/`http://localhost`
允許明文 HTTP（見 [CLOUD_SECURITY.md](CLOUD_SECURITY.md) 第 8 節）。

### 正式環境（Render，Phase 3B 才真正執行）

```bash
# Pre-Deploy：跑 migration
python server/run_migrations.py

# Start：不加 --reload，讀 Render 注入的 $PORT
# 從 repo 根目錄執行（不是從 server/ 底下）——server/app/ 底下的模組
# 互相用絕對路徑 `from server.app.xxx import` import，只有在 repo
# 根目錄是 process 工作目錄時才能正確解析（見 RENDER_DEPLOYMENT.md
# 的說明，這是用乾淨 checkout 測試實際驗證過的結果）。
uvicorn server.app.main:app --host 0.0.0.0 --port $PORT
```

完整步驟見 [RENDER_DEPLOYMENT.md](RENDER_DEPLOYMENT.md)。
