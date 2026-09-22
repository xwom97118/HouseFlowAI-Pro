# HouseFlow Admin — Control Plane

> Phase 2（2026-09-22）：只有產品管理員使用的 License 管理介面。

## 1. 定位

HouseFlow Admin 是 **License Control Plane**，不是使用者業務資料的
監看後台。Admin 只管理：License、Trial、Subscription、Device
Binding、Pricing（含 Early Bird）、App Version metadata、Audit Log。

**Admin 絕對看不到**：客戶姓名/電話、房屋內容、貼文內容、Facebook
cookies/密碼/session、物件照片、排程內容。這不是「介面上沒做」，是
**架構上 Admin 從來沒有管道拿到這些資料**——License Server 的資料庫
裡根本沒有這些表（見 [LICENSE_SERVER.md](LICENSE_SERVER.md) 第 1
節、[PRODUCT_V1_SPEC.md](PRODUCT_V1_SPEC.md) 第 10 節）。

## 2. 認證

沒有任何預設帳號（沒有 admin/admin）。第一個 Admin 帳號必須透過
`server/bootstrap_admin.py` 明確建立：

```bash
python server/bootstrap_admin.py --username admin
```

密碼只能來自互動輸入或環境變數 `HOUSEFLOW_ADMIN_BOOTSTRAP_PASSWORD`
（配合 `--from-env`），兩者都不會被 commit 進原始碼。密碼儲存用
`hashlib.scrypt`（見 [LICENSE_SECURITY.md](LICENSE_SECURITY.md)），
最短 12 個字元。

登入後拿到一個 HttpOnly session cookie（`houseflow_admin_session`），
server 只保存它的 sha256 hash，不是 token 本身。Session 預設 12 小時
過期（`HOUSEFLOW_ADMIN_SESSION_TTL_HOURS` 可調整）。

## 3. 畫面

### Dashboard（`/admin/`）

總 License / Active / Trial / Expiring Soon（7 天內）/ Expired /
Suspended 的計數卡片。

### License 清單（`/admin/licenses`）

搜尋（License ID / License Key 末四碼 / Device 名稱）+ 狀態篩選。
每一列顯示：License ID（縮寫）、Plan、Status、Early Bird、有效價格、
到期日、裝置數、最後驗證時間。

### License 詳細（`/admin/licenses/{license_id}`）

完整欄位 + 操作區：

- **+30 天 / +90 天 / 自訂天數**（延長到期日；如果已經過期，從「現在」
  重新起算，不是從舊的到期日疊加）
- **Suspend / Resume**（暫停不是永久性的，之後可以恢復）
- **Revoke**（永久撤銷，畫面上會要求二次確認，UI 不提供復原）
- **設為 Early Bird / 取消 Early Bird**（設定時鎖定當下的全域月費）
- **直接設定到期日**（YYYY-MM-DD）
- **裝置清單** + 個別「解除綁定」（解除後該裝置的名額釋放，可以給
  新裝置使用）
- **這組 License 的 Audit Log**（只顯示跟這組 License 相關的紀錄）

### 建立 License（`/admin/licenses/new`）

輸入 Plan（目前只有 Professional）、Duration（天）、Device Limit、
Early Bird 勾選。建立成功後，**完整 License Key 只顯示這一次**，
提供「Copy」按鈕；離開這個頁面後就無法再查看完整原始 Key——如果
客戶弄丟了，只能建立一組新的 License（或未來版本支援 Key Rotation），
不提供「查看完整原始 Key」的功能（規格第 5 節）。

### Audit Log（`/admin/audit`）

全站最近的 Admin 操作紀錄（不限單一 License）。

### Settings（`/admin/settings`）

編輯 `ProductSettings`：目前月費、幣別、試用天數、離線寬限天數、
最新版本、最低支援版本。**已經是 Early Bird 的 License 不受這裡的
「目前月費」變動影響**，永久維持建立/設定當下鎖定的價格。

## 4. 人工收款流程（規格第 18 節）

Phase 2 沒有整合任何金流。實際流程：

```
客戶付款（轉帳/其他管道，Phase 2 範圍外）
        ↓
Admin 登入 HouseFlow Admin
        ↓
建立 License（首次購買）或搜尋既有 License（續訂）
        ↓
首購：填 Duration/Device Limit/Early Bird，建立後複製 Key 給客戶
續訂：進入 License 詳細頁，點 +30 天 / +90 天 / 自訂天數
        ↓
立即生效（Admin 操作直接寫入資料庫，沒有審核流程）
```

訂閱架構刻意不跟任何特定金流服務商綁死——`create_license()` /
`extend_license()` 只接受「要建立/延長多少天」，不知道也不需要知道
背後的付款方式。

## 5. Audit Log

每一個會改變狀態的 Admin 操作都會留下紀錄（`AdminAuditLog`）：
`create_license` / `extend_license` / `suspend_license` /
`resume_license` / `revoke_license` / `set_early_bird` /
`set_expiration` / `deactivate_device` / `update_product_settings`。

每筆紀錄包含：操作者（username）、動作、影響的 License ID、
變更前後的欄位快照（JSON，只記錄跟這次操作相關的欄位）、時間。

**絕對不記錄**：密碼、完整 License Key、session token、任何 secret
——`server/app/services/audit_service.py` 的 `_sanitize()` 在寫入
之前會過濾掉這些欄位名稱，就算呼叫端不小心傳進來也會被擋掉。

## 6. 未來（Phase 3 以後，這一輪不做）

- 更多角色（目前只有單一種 Admin 帳號，沒有分權限）。
- 兩步驟驗證（2FA）。
- 匯出報表。
- 與正式金流 webhook 整合（付款成功自動延長，不需要人工操作）。
