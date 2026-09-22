# Phase 2 測試計畫與涵蓋範圍

> 2026-09-22。記錄 Phase 2（License Server + Admin Control Plane）的
> 測試策略與實際涵蓋範圍，供驗收對照規格第 28、29 節的要求清單。

## 1. 測試策略

- **Server 測試**（`server/tests/`）：全部對一個全新的暫存 SQLite
  檔案操作（`server/tests/_helpers.py` 的 `make_test_server()`），
  透過 FastAPI 的 `dependency_overrides` 把 `get_db` 換成指向暫存
  DB 的 session——完全不會碰 `server/data/` 底下真正的開發用資料庫。
- **Desktop 測試**（專案根目錄 `test_http_license_provider.py`）：
  `HTTPLicenseProvider` 的邏輯測試透過「直接呼叫 FastAPI route
  handler 函式」繞過真正的網路層（`_DirectCallClient`），同時保留
  **一個**真正端到端的測試（`test_real_http_round_trip_via_live_uvicorn_server`），
  用 `server/tests/_live_server.py` 真的在背景執行緒啟動一個 uvicorn
  server（真正的 TCP port），證明 httpx → TCP → uvicorn → FastAPI →
  SQLAlchemy 整條路徑真的能通，不只是繞過網路層的邏輯測試。
- 離線寬限期／時鐘回撥測試用一個會主動拋出 `httpx.ConnectError` 的假
  `client_factory` 模擬「連不上 server」，驗證 `HTTPLicenseProvider`
  正確退回本機快取 + `evaluate_license()`（Phase 1 就有、經過測試的
  純函式）的離線判斷邏輯。
- 全程沒有任何測試會：啟動真正的 Facebook 瀏覽器、寫入 production
  Desktop DB、寫入 production Facebook session、發真正的付款請求。

## 2. Server 測試（62 項，7 個檔案，全數通過）

| 檔案 | 項目數 | 涵蓋 |
|---|---|---|
| `test_security.py` | 11 | License Key 格式/唯一性/排除易混淆字元、Key hash 一致性、密碼雜湊 roundtrip/不存明文/隨機 salt、Session token hash、Device fingerprint hash |
| `test_trial.py` | 6 | 開始試用、同裝置重複試用拒絕（409）、試用資格獨立於 License 列存在與否、不同裝置各自可試用、試用到期後 verify 回傳 invalid、回應不含 Property/CRM 欄位 |
| `test_activation.py` | 9 | 啟用成功、無效 Key（404）、同裝置重複啟用冪等、裝置數上限（409）、裝置數 2 允許兩台、Deactivate 後允許新裝置、Suspended/Revoked License 啟用被拒（403）、未綁定裝置 verify 被拒（403） |
| `test_lifecycle.py` | 10 | Active 驗證有效、到期後 invalid、Suspend 阻擋驗證、Resume 恢復、Revoke 永久阻擋、+30/+90/自訂天數延長、延長已過期 License 從今天重新起算、到期不刪除 License 列 |
| `test_pricing.py` | 5 | Early Bird 鎖定 688、全域漲價不影響已鎖定的 Early Bird、非 Early Bird 跟隨全域價格、事後設為 Early Bird 鎖定當下價格、取消 Early Bird 恢復跟隨全域價格 |
| `test_offline_and_version.py` | 5 | verify 回應含 `offline_valid_until`、寬限天數可設定並反映在回應、verify/trial 回應含版本 metadata、版本 metadata 來自 ProductSettings（非寫死） |
| `test_admin_auth.py` | 16 | 預設無帳號、建立帳號、密碼長度限制、帳號重複拒絕、登入成功/失敗（密碼錯/帳號不存在）、Session 建立/驗證/登出失效、無效 token、HTTP 登入設 cookie、未登入導去登入頁、密碼錯不設 cookie、建立 License 寫入 Audit Log、Audit Log 不含明文 Key、完整生命週期動作都留下紀錄 |

## 3. Desktop 測試（Phase 2 新增，`test_http_license_provider.py`，17 項）

| 分類 | 對應測試 |
|---|---|
| First Run Trial | `test_first_run_trial_via_http` |
| Trial 二次拒絕 | `test_trial_second_attempt_raises_trial_already_used` |
| License activation | `test_license_activation_success` |
| Bad key | `test_bad_key_raises_lookup_error` |
| Device mismatch/上限 | `test_device_limit_raises_device_limit_reached_error` |
| Active | `test_check_license_active` |
| Expired | `test_check_license_expired` |
| Suspended | `test_check_license_suspended` |
| Revoked | `test_check_license_revoked`（新增 `LicenseStatus.REVOKED`） |
| Offline within 7 days | `test_offline_within_seven_days_still_allowed` |
| Offline beyond 7 days | `test_offline_beyond_seven_days_blocked` |
| Clock rollback | `test_clock_rollback_forces_reactivation` |
| License refresh | `test_check_license_refreshes_local_cache` |
| Settings 顯示 | `test_settings_panel_displays_active_license_via_http_provider` |
| Version warning | `test_version_warning_shown_when_below_minimum` / `test_no_version_warning_when_up_to_date` |
| 真實 HTTP 端到端 | `test_real_http_round_trip_via_live_uvicorn_server` |

全部 Mock／隔離測試伺服器，沒有一項測試連到真正部署的 License
Server 或任何外部網路。

## 4. 既有回歸套件（Phase 1／1.1，全數保持通過）

`test_auto_sync.py`、`test_automation_engine.py`、
`test_backup_service.py`、`test_browser_preflight.py`、
`test_content_safety.py`、`test_db_migrations.py`、
`test_dev_delete_minutes.py`、`test_license.py`、
`test_live_facebook_isolation.py`、`test_mainwindow_v1_smoke.py`、
`test_post_capture.py`、`test_post_capture_fixture.py`、
`test_property_connector.py`、`test_schedule_ux.py`、
`test_sync_crash_recovery.py`、`test_updater_service.py`、
`test_activation_dialog.py`、`test_ai_service_generic_branding.py`
——共 18 個檔案，Phase 2 的改動（`LicenseStatus` 新增 `REVOKED`、
`LicenseCheckResult` 新增版本欄位、Settings 頁換成
`HTTPLicenseProvider`）全部驗證過不影響這些既有測試的通過狀態。

## 5. 除錯過程中發現並修正的測試方法論問題

這幾個問題都發生在測試本身的情境設計，不是 Phase 2 原始碼的邏輯錯誤：

1. **SQLAlchemy `Session.close()` 會讓已提交的 ORM 物件過期**：
   `db.refresh()` 之後即使物件已經有正確的值，`session.close()` 仍然
   會讓後續屬性存取嘗試重新從 DB 讀取，導致
   `DetachedInstanceError`。修正：測試用的 session factory 設定
   `expire_on_commit=False`（只影響測試，production 的
   request-scoped session 一律在同一個 session 生命週期內就把資料
   序列化成 Pydantic response，不受影響）。
2. **離線寬限期測試最初只模擬連線失敗，沒有讓「快取的 License」真的
   過期**：`evaluate_license()` 的 ACTIVE 分支會先檢查
   `now < expires_at`——License 還在有效期內時，離線與否根本不影響
   結果。修正：測試要先讓本機快取（不是 server 端 DB——見下一點）的
   `expires_at` 真的落在過去，才能真正測到離線寬限期／時鐘回撥那段
   邏輯。
3. **混淆了「server 端 DB」跟「Desktop 本機快取」**：離線 fallback
   （`_offline_fallback()`）用的是本機快取，不會、也不可能去問 server
   現在的真實狀態——這正是「離線」的意義。测试一度直接修改 server DB
   的 `expires_at`，但 Desktop 端仍然讀到舊的本機快取值，導致離線
   fallback 測試失敗。修正：直接竄改 `HTTPLicenseProvider` 的本機
   快取（`license_state_json`），而不是 server 端資料。
4. **`ASGITransport`（httpx 0.28）在這個版本只實作了非同步的
   `handle_async_request`**，無法配合 `httpx.Client`（同步）直接使用
   ——改用「直接呼叫 FastAPI route handler 函式」的方式測試
   `HTTPLicenseProvider` 的邏輯，另外保留一個用真正 uvicorn server（見
   `server/tests/_live_server.py`）跑的端到端測試，兩者互補。
5. **`QWidget.isVisible()` 在 widget 從未 `show()` 過的情況下永遠回傳
   `False`**（跟 Phase 1 修 `test_schedule_ux.py` 時遇到的同一個
   Qt 特性）：版本提示標籤的測試需要改用 `isHidden()`，才能正確反映
   `setVisible()` 實際設定的旗標，而不是看它有沒有真的被畫在螢幕上。
6. **LicenseInfoPanel 用 `compute_device_fingerprint()` 自己算裝置
   指紋，測試如果用另一個任意字串去啟用 License，之後 panel 呼叫
   `check_license()` 會因為指紋對不上被 server 判定成「裝置未綁定」
   （403）**——這個失敗一度被「`blocked()` 沿用本機快取裡舊的
   status」意外掩蓋掉，看起來像是通過的。修正：測試裡活化 License
   時，一律用 `compute_device_fingerprint()` 算出跟 panel 之後會用的
   同一個指紋。
