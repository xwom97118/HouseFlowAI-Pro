# License Server 安全設計

> Phase 2（2026-09-22）。涵蓋：密碼雜湊、License Key 產生/雜湊、
> Session 管理、輸入驗證、Log 遮罩、Rate Limit（預留）、傳輸安全、
> Privacy 邊界。

## 1. 密碼雜湊（Admin 帳號）

`server/app/security.py`：`hash_password()` / `verify_password()`。

- 演算法：`hashlib.scrypt`（Python 3.6+ 標準函式庫內建，記憶體困難
  的 KDF，業界公認安全）。
- 每組密碼一組獨立的 16 bytes random salt（`secrets.token_bytes`）。
- 儲存格式：`scrypt$N$r$p$<salt_hex>$<hash_hex>`（參數本身也存起來，
  之後要調整 scrypt 參數強度時，舊帳號的雜湊仍然可以正確驗證）。
- 密碼比對用 `hmac.compare_digest()`（常數時間比較，避免 timing
  attack）。
- 密碼長度最低要求：12 個字元（`admin_auth_service.create_admin_user()`）。
- 沒有任何預設帳密，第一個 Admin 帳號必須透過
  `server/bootstrap_admin.py` 明確建立（見
  [ADMIN_CONTROL_PLANE.md](ADMIN_CONTROL_PLANE.md) 第 2 節）。

刻意不用 passlib/bcrypt 第三方套件——`hashlib.scrypt` 已經是標準
函式庫的一部分，少一個依賴，安全性等級足夠這個規模的系統使用。

## 2. License Key

`security.generate_license_key()`：

- 格式：`HF-PRO-XXXX-XXXX-XXXX-XXXX`。
- 隨機來源：`secrets.choice()`（Python 官方文件明確建議用於安全相關
  用途的隨機來源，底層用作業系統的 CSPRNG）。**不是**流水號、不是
  timestamp、不是 `random` 模組。
- 字元集排除容易混淆的 `0/O/1/I/L`，降低使用者手動輸入/抄寫時的
  出錯率。
- 每組 4 碼 × 4 組 = 16 碼有效字元，字元集大小 32 → 總空間
  32^16 ≈ 1.2 × 10^24 種組合，暴力枚舉不可行。

**資料庫只存 `license_key_hash`（sha256）+ `license_key_last4`（顯示
用的末四碼）**，從不存明文。完整 Key 只在 Admin 建立當下的那一次
HTTP 回應裡出現，之後任何查詢都拿不到完整原始 Key——如果客戶弄丟了
Key，唯一的解法是 Admin 建立一組新的 License（見
[ADMIN_CONTROL_PLANE.md](ADMIN_CONTROL_PLANE.md) 第 3 節，「不提供
查看完整原始 License Key」）。

## 3. Session Token（Admin 登入）

- `secrets.token_urlsafe(32)`——256 bits 的隨機性。
- 存進瀏覽器的是 HttpOnly cookie（JS 讀不到，降低 XSS 竊取 session
  的風險），`SameSite=Lax`。
- 資料庫只存 `session_token_hash`（sha256），不存 token 本身——即使
  資料庫外洩，攻擊者也不能直接拿 hash 冒充已登入的 session（需要先
  反推出原始 token，而 sha256 不可逆）。
- 預設 12 小時過期（`HOUSEFLOW_ADMIN_SESSION_TTL_HOURS`）。
- 登出（`/admin/logout`）會直接刪除該筆 session 記錄，立即失效。

## 4. 裝置指紋（Device Fingerprint）

Desktop 端傳來的 `device_fingerprint` 本身已經是「本機持久化隨機
UUID 的 sha256」（見 `app/services/license/fingerprint.py`，Phase 1
就已經決定不用任何真正的硬體識別資訊）。Server 端收到後**再雜湊一次**
（`hash_device_fingerprint()`）才存進 `DeviceBinding.device_fingerprint_hash`
——這是防禦性深度，不代表 Server 端有能力、或曾經嘗試逆推出任何真正
的硬體身分資訊。

## 5. 輸入驗證

所有 API request body 都是 Pydantic model（`server/app/schemas/`），
FastAPI 自動做型別/長度驗證（例如 `device_fingerprint` 最短 8 字元、
最長 256 字元），格式不符直接回 422，不會進到業務邏輯層。

## 6. Log / 敏感資料遮罩

- Audit Log（`audit_service._sanitize()`）在寫入前主動過濾掉
  `password` / `password_hash` / `license_key` / `session_token` /
  `token` / `secret` 這些欄位名稱，就算呼叫端不小心傳進去也會被擋掉
  （見 [ADMIN_CONTROL_PLANE.md](ADMIN_CONTROL_PLANE.md) 第 5 節）。
- FastAPI/uvicorn 預設的 access log 只記錄 method/path/status，不記錄
  request body，所以 License Key、密碼不會出現在一般伺服器 log 裡。

## 7. Rate Limit（架構預留，Phase 2 未啟用）

`server/app/api/license_routes.py` 目前沒有實作真正的 rate limit
——Phase 2 只在本機開發環境跑，還沒有對外流量。架構上預留的位置：
FastAPI 的 middleware 層（可以之後加一個
`SlowAPIMiddleware`/自訂 middleware，掛在 `/api/trial/start` 跟
`/api/license/activate` 這兩個最容易被暴力嘗試的端點），不需要改動
`server/app/services/` 底下任何邏輯。

## 8. 傳輸安全

- Phase 2（本機開發，localhost）：允許 HTTP。
- 正式部署前：**必須**是 HTTPS。`server/app/config.py` 的
  `require_https` 旗標（環境變數 `HOUSEFLOW_LICENSE_REQUIRE_HTTPS=1`）
  目前只用來在啟動時印出提醒，不做任何強制的 TLS 檢查——真正的 TLS
  termination 是部署環境（反向代理/Cloud 服務）的責任，不是這個
  Phase 的範圍。`require_https=True` 時，Admin session cookie 會自動
  加上 `Secure` 旗標。

## 9. Privacy 邊界（規格第 27 節）

License Server 的資料庫（`server/app/models/license.py`）只有六張表：
`licenses`、`device_bindings`、`trial_fingerprints`、
`product_settings`、`admin_users`、`admin_sessions`、
`admin_audit_logs`——裡面**沒有任何一個欄位**用來存 Property、CRM、
Facebook 貼文內容、Facebook cookies/密碼、排程內容、物件照片。這不是
「這次沒填」，是 schema 本身就沒有對應的欄位/表可以存放這些資料。
`test_trial.py` 的
`test_trial_response_never_includes_property_or_crm_fields()` 這項
測試專門驗證 API 回應裡沒有這些欄位名稱。
