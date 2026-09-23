# License Server Cloud 安全設計

> Phase 3A（2026-09-23）。彙整目前已經實作、已經測試過的安全機制。
> 密碼學/雜湊細節見 [LICENSE_SECURITY.md](LICENSE_SECURITY.md)（Phase
> 2），這份文件補充 Phase 3A 新增的部分：CSRF、rate limit、signed
> license state、production 環境的 fail-fast 檢查、CORS、error
> handling、logging。

## 1. CSRF 保護

所有會修改資料的 Admin POST route（建立/延長/暫停/恢復/撤銷
License、Early Bird、設定到期日、解除裝置綁定、修改全域設定）都要求
一個跟目前 session 綁定的 `csrf_token`（`server/app/csrf.py`）。

Token 用 HMAC-SHA256(secret_key, session_token) 推導，不需要另外
一張表或另一個 cookie——session 換了 token 就跟著換，session 結束
token 就失效。驗證失敗一律導回登入頁，不區分「沒登入」跟「CSRF token
錯誤」兩種情況，避免洩漏 session 是否存在的資訊。

登入（`POST /admin/login`）跟登出（`GET /admin/logout`）刻意不要求
CSRF token——前者還沒有已建立的 session 可以被濫用，後者被 CSRF
強制觸發頂多是騷擾（被迫重新登入一次），不是真正的安全風險。

測試：`server/tests/test_csrf_and_lockout.py`（12 項，涵蓋沒帶
token/帶錯 token/帶對 token/重新登入後舊 token 失效）。

## 2. Admin 登入 Brute-force 防護

兩層互補的防護：

1. **單一帳號**：連續 5 次密碼錯誤後鎖定該帳號 15 分鐘，即使之後
   輸入正確密碼也拒絕（`server/app/services/admin_auth_service.py`
   的 `MAX_FAILED_LOGIN_ATTEMPTS`/`LOCKOUT_DURATION_MINUTES`）。
2. **單一來源 IP**：每個 IP 5 分鐘內最多 10 次登入嘗試（不分帳號），
   擋掉「對很多不同帳號名稱各試幾次」這種繞過單一帳號鎖定的手法
   （`server/app/middleware.py` 的 `admin_login_rate_limiter`）。

錯誤訊息一律是「帳號或密碼不正確」，不透露帳號是否存在——避免攻擊者
用錯誤訊息差異去列舉出有效帳號。

## 3. License API Rate Limiting

`/api/trial/start`、`/api/license/activate`、`/api/license/verify`：
每個來源 IP 每分鐘最多 30 次（`server/app/middleware.py` 的
`license_api_rate_limiter`）。正常 HouseFlow 使用（定期 verify、偶爾
activate）遠低於這個量。

**已知限制**（寫在 `RateLimiter` 的 docstring 裡，不是隱藏的技術
債）：這是單一 process 記憶體內計數，如果之後 Render 上跑多個
instance，各 instance 各算各的，達不到「全域每分鐘 N 次」的效果。
要做到跨 instance 限制需要換成 Redis 之類的集中式儲存——列在
[PHASE3B_DEPLOY_CHECKLIST.md](PHASE3B_DEPLOY_CHECKLIST.md)，不在
Phase 3A 範圍內（Render 免費/入門方案本來就是單一 instance，這個
限制在那之前不會真的造成問題）。

## 4. License 狀態簽章（防本機快取被竄改）

見 [ARCHITECTURE.md](ARCHITECTURE.md) 的 License Server 章節與
`server/app/services/signing_service.py` / `app/services/license/signing.py`
的說明。摘要：

- Server 用 Ed25519 私鑰對每次回應的關鍵欄位
  （license_id/status/expires_at/trial_ends_at/server_time）簽章。
- Desktop 用內建的公鑰驗證簽章，驗證失敗就不快取這份資料。
- 本機快取本身也存簽章，離線時重新驗證——使用者直接修改本機 SQLite
  裡的 `expires_at` 想繞過授權，簽章會對不上，偵測到後要求重新連線
  驗證，不會被 `evaluate_license()` 誤判成「還有效」。
- 私鑰只存在 server 的環境變數，從不出現在 Desktop 端的程式碼、
  設定檔或安裝檔裡。

**向下相容決定**：Desktop 端沒有設定 `HOUSEFLOW_LICENSE_SERVER_PUBLIC_KEY`
時（Phase 2 既有安裝的預設狀態），簽章驗證功能不啟用，行為退回
Phase 2——刻意不讓這個新功能一夜之間鎖住所有既有安裝。Phase 3B
正式上線、確定所有使用者都更新到有這個功能的版本之後，應該考慮把
這個環境變數改成必填。

## 5. Production Fail-Fast 檢查

`ENVIRONMENT=production` 時：

- 缺少 `HOUSEFLOW_SECRET_KEY` → 啟動時直接拋出例外，拒絕用自動產生
  的臨時金鑰頂著跑。
- 缺少 `HOUSEFLOW_LICENSE_SIGNING_PRIVATE_KEY` → 同樣拒絕啟動。

本機開發環境會自動產生「僅供本次啟動使用」的臨時值並印出警告——這跟
「允許 HTTP」是同一種「本機開發圖方便，正式環境必須明確設定」的
精神。

## 6. CORS

`Access-Control-Allow-Origin` 只允許 `APP_BASE_URL`（沒設定就不允許
任何跨來源請求），不用 `*`。HouseFlow Desktop 是用 `httpx` 發請求的
native client，CORS 本來就只限制瀏覽器發出的跨來源請求，對 Desktop
完全沒有影響——這個設定是為了「萬一之後有網頁前端要呼叫這個 API」
預留的最小權限起點，不是現在有這個需求。

## 7. 錯誤處理 / Log 不外洩內部細節

- 全域例外處理（`server/app/main.py` 的
  `_unhandled_exception_handler`）：任何沒被明確處理的例外，回給
  client 的只有 `error_code`/`detail`/`request_id`，不含
  traceback、SQL、檔案路徑、環境變數；完整資訊（例外類型）進 server
  log。
- `/health/ready`：DB 連不上時，回應內容不含任何連線字串或例外訊息，
  只有 `{"status": "not_ready"}`。
- 結構化 log（`server/app/logging_config.py`）：每一行 log 是一個
  JSON object，`mask_sensitive()` 在寫入前過濾掉
  password/license_key/session_token/secret/cookie/signature/
  private_key 等欄位名稱。

測試：`server/tests/test_production_hardening.py`（8 項，涵蓋
health/readiness 不洩漏資訊、rate limiter 行為、全域例外處理不洩漏
traceback）。

## 8. 傳輸安全

- Desktop 端：`HTTPLicenseProvider` 建構時就檢查 base_url，非
  `https://` 且非 `localhost/127.0.0.1` 一律拒絕建立（
  `InsecureLicenseServerURLError`），不會把 License Key 用明文 HTTP
  傳到 Internet 上（規格第 19 節）。
- Server 端：`HOUSEFLOW_LICENSE_REQUIRE_HTTPS=1` 時 Admin session
  cookie 帶 `Secure` 旗標；實際的 TLS termination 由部署環境（Render
  本身就對所有 Web Service 提供免費、自動的 HTTPS）負責，不是這個
  應用程式自己處理。

## 9. Server Time Authority

License 生命週期的權威時間來源永遠是 server（`server/app/timeutil.py`
的 `utc_now()`），不是任何一台 Desktop 的本機時鐘：

- 所有到期判斷（`compute_effective_status()`、
  `_compute_status_result_unsigned()`）都用 server 的 `utc_now()`，
  修改 Windows 系統日期完全不會影響 server 端怎麼判斷一組 License
  到期了沒。
- Desktop 端只有在**連不上 server**時才會退回本機快取 + 本機時鐘算
  離線寬限期（`evaluate_license()`），而且這個計算本身有 Phase 1
  就建立、Phase 3A 延續使用的 clock-tamper 防護（`high_water_mark`
  機制——見 `app/services/license/evaluation.py`）：本機時鐘被往回
  調，離線寬限期判斷會被拒絕，要求重新連線，而不是被系統誤信成
  「還在寬限期內」。
- Phase 3A 額外加上的 License 狀態簽章（第 4 節）讓這個防護更進一步
  ——即使使用者直接編輯本機 SQLite 檔案裡的 `expires_at`，脫離
  `evaluate_license()` 的計算路徑，簽章驗證也會偵測到內容被竄改
  （見 `test_signed_license_state.py`）。

測試涵蓋：`test_http_license_provider.py` 的
`test_clock_rollback_forces_reactivation`、
`test_offline_and_version_scenarios.py` 的 Day 1/6/8 情境測試。

## 10. 尚未完成、留給 Phase 3B 的項目

見 [PHASE3B_DEPLOY_CHECKLIST.md](PHASE3B_DEPLOY_CHECKLIST.md)——包含
「跨 instance rate limit」「真正的 PostgreSQL 環境驗證」「正式簽章
金鑰的產生與保管流程」等需要真正的 Render 環境才能完成的項目。
