# Phase 3B — Deploy Checklist

> Phase 3A（2026-09-23）準備了完整的程式碼、設定、文件，讓真正部署
> 這件事變成「照著這份清單做」而不是「重新設計架構」。**這份清單裡
> 沒有一項在 Phase 3A 完成**——全部留給你在真正決定要上線時，一步一步
> 人工確認。

## 上線前

- [ ] 建立 Render 帳號（如果還沒有）。
- [ ] 決定正式 Domain（例如 `license.houseflow.app`）——不急著這一步
      就買，可以先用 Render 給的 `*.onrender.com` 網址上線，之後再換
      成自訂 Domain。
- [ ] 用 `python server/generate_signing_keypair.py` 產生**正式用**
      的簽章金鑰對（不要沿用任何本機開發/測試時看過的臨時金鑰）。
      私鑰要有妥善的備份方式（見
      [CLOUD_BACKUP_RECOVERY.md](CLOUD_BACKUP_RECOVERY.md) 第 6 節
      ——遺失這把私鑰不會讓資料遺失，但會讓所有 Desktop 端已經快取的
      簽章驗證失敗，逼所有使用者重新連線）。
- [ ] 用 `python -c "import secrets; print(secrets.token_urlsafe(32))"`
      產生正式用的 `HOUSEFLOW_SECRET_KEY`。
- [ ] 決定 Admin 帳號的使用者名稱與一組夠強的密碼（bootstrap 時會
      要求最少 12 字元，建議更長、用密碼產生器）。

## Render 設定（照 [RENDER_DEPLOYMENT.md](RENDER_DEPLOYMENT.md) 逐步操作）

- [ ] 建立 PostgreSQL 資料庫（`houseflow-license-db`）。
- [ ] 建立 Web Service，Root Directory 設成 `server`。
- [ ] 連結資料庫到 Web Service（自動注入 `DATABASE_URL`）。
- [ ] 設定所有必要環境變數（見
      [PRODUCTION_ENVIRONMENT.md](PRODUCTION_ENVIRONMENT.md) 的完整
      清單）：`ENVIRONMENT=production`、`HOUSEFLOW_SECRET_KEY`、
      `HOUSEFLOW_LICENSE_SIGNING_PRIVATE_KEY`、
      `HOUSEFLOW_LICENSE_REQUIRE_HTTPS=1`、`APP_BASE_URL`。
- [ ] 確認 Build Command / Pre-Deploy Command / Start Command 跟
      `render.yaml` 描述的一致。
- [ ] 觸發第一次部署，確認 build 成功。
- [ ] 確認 Pre-Deploy Command（`run_migrations.py`）成功跑完，
      PostgreSQL 裡出現完整的 7 張 table + `alembic_version`。
- [ ] 確認 `/health` 回傳 200。
- [ ] 確認 `/health/ready` 回傳 200（代表資料庫真的連得上，不只是
      process 活著）。

## Admin 帳號

- [ ] 用 Render Shell 執行 `python bootstrap_admin.py --username <你的帳號>`。
- [ ] 登入 `https://<你的網址>/admin/login`，確認能正常登入。
- [ ] 檢查瀏覽器開發工具，確認 session cookie 有 `Secure` 旗標（代表
      `HOUSEFLOW_LICENSE_REQUIRE_HTTPS=1` 真的生效）。
- [ ] 建立一組測試用 License（Plan=Professional，短天數），完整走過
      一次 Admin 操作（延長/暫停/恢復/撤銷/Early Bird），確認
      Audit Log 正確記錄。
- [ ] 完成測試後，用 Revoke 或直接在資料庫層面移除這組測試 License
      （不要留下測試資料混在正式資料裡）。

## HTTPS 驗證

- [ ] 確認 Render 提供的 HTTPS 憑證有效（Render 對所有 Web Service
      預設提供免費、自動更新的 HTTPS，通常不需要額外設定）。
- [ ] 用 `curl -I https://<你的網址>/health` 確認回應標頭正常、沒有
      憑證警告。
- [ ] 如果設定了自訂 Domain，確認 DNS 設定正確、Render 那邊的自訂
      Domain 驗證通過。

## 外部 Desktop 啟用測試（真正的第一次外部串接）

- [ ] 在一台**跟開發機器分開**的 Windows 環境（或至少是乾淨的使用者
      資料目錄），設定：
      `HOUSEFLOW_LICENSE_SERVER_URL=https://<你的正式網址>`、
      `HOUSEFLOW_LICENSE_SERVER_PUBLIC_KEY=<步驟前置需求產生的公鑰>`。
- [ ] 走一次完整的「開始試用」流程，確認 Desktop 端能連上正式
      Server、正確顯示試用中狀態。
- [ ] 走一次「輸入 License Key 啟用」流程（用 Admin 建立的測試
      License Key）。
- [ ] 關閉網路，確認離線寬限期正常運作（不會立即被鎖住）。
- [ ] 確認 Settings → 授權資訊頁面正確顯示所有欄位（方案/狀態/到期
      日/剩餘天數/裝置/最後驗證時間）。

## 備份驗證

- [ ] 確認 Render PostgreSQL 的自動備份已經啟用（見
      [CLOUD_BACKUP_RECOVERY.md](CLOUD_BACKUP_RECOVERY.md)）。
- [ ] 決定是否要額外設定 `pg_dump` 邏輯備份排程；如果要，設定好並
      確認第一次排程真的成功執行、產生了可用的備份檔案。
- [ ] 執行一次還原演練（還原到一個獨立的測試資料庫，不是正式
      環境），確認備份真的可用，不是「存在但壞掉」。

## 上線後

- [ ] 監控 Render 的 log/metrics，確認沒有非預期的 500 錯誤或效能
      異常。
- [ ] 確認 Admin Audit Log 只有你自己操作留下的記錄，沒有異常的
      登入嘗試（如果有大量失敗登入紀錄，考慮進一步調查）。
- [ ] 把正式 Desktop 安裝檔（未來 Installer）的預設
      `HOUSEFLOW_LICENSE_SERVER_URL`/`HOUSEFLOW_LICENSE_SERVER_PUBLIC_KEY`
      更新成正式值（這一輪 Desktop 預設值仍然是本機開發用的
      `http://127.0.0.1:8000`，故意不填任何 Render 網址進去，見
      [ARCHITECTURE.md](ARCHITECTURE.md)）。

## 明確不在這份清單裡（更後面的階段）

- 金流串接（規格明確排除在這幾輪之外）。
- Email 系統/密碼重設信。
- 公開的自助購買/註冊網站。
- 跨 instance 的集中式 rate limiting（目前是單一 process 記憶體內，
  見 [CLOUD_SECURITY.md](CLOUD_SECURITY.md) 第 3 節；Render 開始跑
  多個 instance 之前不會是真正的問題）。
