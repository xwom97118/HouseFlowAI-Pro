# Production Environment Configuration

> Phase 3A（2026-09-23）。完整的環境變數清單，對照
> [server/.env.example](../server/.env.example)。本輪不會真的設定
> 任何一個正式值——這份文件是給 Phase 3B 真正部署時對照用的。

## 1. 環境變數總表

| 變數 | 必填（production） | 說明 |
|---|---|---|
| `ENVIRONMENT` | 是（設成 `production`） | 切換 fail-fast 檢查與啟動流程（見下）。 |
| `DATABASE_URL` | 是（Render 自動注入） | PostgreSQL 連線字串。 |
| `HOUSEFLOW_LICENSE_DB_URL` | 否 | 優先於 `DATABASE_URL`，本機開發用。 |
| `HOUSEFLOW_SECRET_KEY` | **是** | CSRF token 推導用。沒設定且 `ENVIRONMENT=production` 時應用程式直接拒絕啟動。 |
| `HOUSEFLOW_LICENSE_SIGNING_PRIVATE_KEY` | **是** | License 狀態簽章私鑰（base64 PEM）。同樣是 production fail-fast。 |
| `HOUSEFLOW_LICENSE_REQUIRE_HTTPS` | 是（設成 `1`） | 控制 Admin session cookie 的 Secure 旗標。 |
| `APP_BASE_URL` | 建議設定 | CORS allow-list 用。 |
| `HOUSEFLOW_ADMIN_SESSION_TTL_HOURS` | 否（預設 12） | Admin session 有效期間（小時）。 |
| `LOG_LEVEL` | 否（預設 `INFO`） | 結構化 log 的輸出等級。 |
| `HOUSEFLOW_ADMIN_BOOTSTRAP_PASSWORD` | 否，只在建立第一個帳號那一次短暫設定 | 見 `server/bootstrap_admin.py --from-env`。 |

Desktop 端（`app/services/license/http_provider.py`）另外讀：

| 變數 | 說明 |
|---|---|
| `HOUSEFLOW_LICENSE_SERVER_URL` | License Server 網址。正式環境必須是 `https://`（見 [CLOUD_SECURITY.md](CLOUD_SECURITY.md) 第 4 節），只有 `http://127.0.0.1`/`http://localhost` 允許明文 HTTP。 |
| `HOUSEFLOW_LICENSE_SERVER_PUBLIC_KEY` | License 狀態簽章的公鑰（base64）。沒設定時簽章驗證功能不啟用（向下相容 Phase 2 既有安裝），Phase 3B 正式上線前應該設成必填。 |

## 2. `ENVIRONMENT=production` 時的行為差異

- `HOUSEFLOW_SECRET_KEY` 未設定 → 應用程式啟動時直接拋出
  `RuntimeError`，不會用自動產生的臨時金鑰頂著跑（本機開發才會這樣
  做，見 `server/app/config.py` 的 `_resolve_secret_key()`）。
- `HOUSEFLOW_LICENSE_SIGNING_PRIVATE_KEY` 未設定 → 同樣直接拒絕啟動
  （見 `server/app/services/signing_service.py`）。
- 啟動時執行 `run_migrations()`（`alembic upgrade head`），不是
  `Base.metadata.create_all()`——見
  [LICENSE_SERVER.md](LICENSE_SERVER.md)「資料庫選擇」一節。

## 3. 如何產生每一個 secret

```bash
# HOUSEFLOW_SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(32))"

# HOUSEFLOW_LICENSE_SIGNING_PRIVATE_KEY / HOUSEFLOW_LICENSE_SERVER_PUBLIC_KEY
python server/generate_signing_keypair.py
```

`generate_signing_keypair.py` 一次印出一組配對好的私鑰／公鑰，私鑰
設給 Render 上的 License Server，公鑰設給 Desktop 安裝時的設定
（未來 Phase 3B/Installer 決定實際的分發方式，這一輪只確保「有這個
機制」）。

## 4. 這份文件不包含的東西

- 不包含任何一個變數的真實值——上面全部都是名稱與說明。
- 不包含 Render 帳號/Service 本身怎麼建立（見
  [RENDER_DEPLOYMENT.md](RENDER_DEPLOYMENT.md)）。
- 不包含 Desktop 端要怎麼把這些環境變數帶進使用者的電腦（那是未來
  Installer/First Run 流程要解決的問題，這一輪只確保 Desktop 端讀取
  這些環境變數的程式碼路徑已經存在且測試過）。
