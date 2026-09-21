# HouseFlow 產品化 V1 規格

> 本文件記錄 HouseFlow 從「個人本機工具」轉型為「可公開下載、安裝、
> 試用、付費訂閱的 Windows Desktop 商業軟體」（產品化 Phase 1，
> 2026-09-21）時制定的產品層規格。程式碼層的架構說明見
> [ARCHITECTURE.md](ARCHITECTURE.md)。

## 1. 產品定位

- 產品全名：**HouseFlow**（中文：HouseFlow 房仲工作台）。
- 不使用「HouseFlow AI Professional」或「AI Professional」等舊名稱
  （UI、視窗標題、關於畫面、版本資訊、新文件一律禁止）。
- 型態：Windows Desktop 應用程式（PySide6 + 本機 SQLite + 本機瀏覽器
  自動化），**不是**網頁應用程式。V1 維持這個型態不變。
- 核心定位：**Local First** —— 使用者的房仲業務資料（物件、排程、
  貼文內容、客戶資料、Facebook session）留在使用者自己的電腦上，不上傳
  任何 Cloud（見第 6 節）。

## 2. V1 功能範圍

### 2.1 V1 顯示的核心流程

Dashboard → 同步中心 → 物件中心 → 發文中心 → 社團管理 → 排程管理 →
分析 → 設定

完整業務流程：**網站物件來源 → 同步 → 物件中心 → 安排發文 → Quick
Schedule → 排程管理 → Facebook 發布 → 貼文識別 → 自動刪除 →
分析/Log**。

### 2.2 V1 暫時隱藏的功能

以下功能從 V1 導覽列隱藏，但**程式碼、資料庫 table、既有資料完全保留
不刪除**，之後可以直接重新開放：

- AI 文案
- 成交策略
- 客戶管理 / CRM

## 3. 商業模式

| 項目 | 值 |
|---|---|
| 產品 | HouseFlow |
| 方案 | Professional |
| 定價 | NT$688 / 月 |
| 試用 | 7 天，完整功能，不需信用卡 |
| 試用限制 | 原則上每台裝置只能有一次免費試用 |
| License 綁定 | 1 組 Professional License = 1 台裝置 |

### 3.1 早鳥定價

早鳥使用者即使未來公開定價調整（788 / 888 / 988…），永久維持
NT$688/月。資料模型需保留：`is_early_bird`、`locked_price`、
`currency`（見 `app/services/license/models.py` 的 `License`
dataclass）。

## 4. License Key 模型

格式類似 `HF-PRO-XXXX-XXXX-XXXX`，但**不是**單純的序號當作安全基礎
——真正的有效性必須由伺服器端權威資料驗證（V1 的 `MockLicenseProvider`
只做格式檢查，供本機開發/測試用，明確不是真正的驗證邏輯）。

保留欄位：`license_id`、`license_key_hash`、`plan`、`status`、
`trial_started_at`、`trial_ends_at`、`activated_at`、`expires_at`、
`is_early_bird`、`locked_price`、`currency`、`device_limit`、
`created_at`、`updated_at`。**不保存明文 license key**，只保存
`license_key_hash`。

## 5. 裝置綁定

- 1 組 Professional License 綁定 1 台裝置。
- 保留欄位：`device_id`、`license_id`、`device_fingerprint`、
  `device_name`、`first_activated_at`、`last_seen_at`、
  `last_license_check_at`、`status`。
- Admin 未來可以解除某台裝置的綁定，讓新裝置可以啟用。
- Device fingerprint **不**使用單一容易變動的硬體資訊（MAC / 硬碟序號
  / 主機板序號），改用本機持久化的隨機 UUID（見
  `app/services/license/fingerprint.py`），只有在使用者資料目錄真的
  被清空（等同全新安裝）時才會改變——刻意設計為非侵入式，不是硬體
  DRM。

## 6. 試用防濫用

7 天試用、完整功能、原則上一台裝置一次。不能單靠「刪除 SQLite 再重裝
HouseFlow」重置——最終仍需要伺服器端記錄裝置是否已使用過試用資格，
V1 先用本機持久化的 device fingerprint 作為最小可行版本（見
`MockLicenseProvider._used_trial_fingerprints`）。

## 7. 離線授權（Offline License）

- 訂閱有效期間允許離線使用。
- 最長連續離線天數：**7 天**（以「上一次成功驗證的時間」為準）。
- 超過 7 天需要重新連網完成一次驗證。
- **不能只信任本機系統時鐘**：系統會持久化一個「本機看過的最新時間戳記
  （high-water mark）」，如果目前時間早於這個記錄，視為時鐘被往回調過
  （tamper 訊號），此時不採信離線寬限期還沒用完的判斷，要求重新連網
  驗證（見 `app/services/license/evaluation.py`）。這不是侵入式 DRM，
  只是防止單純調本機時鐘就能無限期繞過。

## 8. 訂閱到期

到期**絕對不會刪除**：資料庫、物件資料、排程資料、CRM 舊資料、
Facebook Profile、圖片、設定、備份。到期只限制需要有效 License 的操作
（例如：發布新貼文）。UI 顯示「HouseFlow 訂閱已到期」，提供「續訂 /
重新驗證」選項，資料完全保留完整。

## 9. Facebook 帳號政策

V1 一次只管理 **1 組** Facebook 瀏覽器 Profile / Session，不支援多
帳號。當 session 失效、登出、被檢查點（checkpoint）、需要重新登入、
需要安全驗證，或狀態無法確認時：

- 停止新的 Facebook 發布。
- 絕對不能把失敗的排程標記為成功。
- UI 顯示「Facebook 需要重新登入」，提供「重新連接 Facebook」選項。
- 既有排程資料不會消失。

> **這條規則保護目前已驗證穩定的 Facebook closed-loop pipeline
> （commit `b3d28a8`）——見 [ARCHITECTURE.md](ARCHITECTURE.md#facebook-pipeline-受保護)
> 的保護說明，本規格書不重新定義任何 Facebook 發布/擷取/刪除邏輯。**

## 10. Cloud V1 範圍（非常重要）

Cloud（未來的 HouseFlow License Cloud + Admin）**只**負責：

- License
- Trial
- Subscription
- Device Binding
- App Version / Update Metadata
- 必要的 Admin 控制

**絕對不**上傳：物件資料、CRM 資料、排程內容、Facebook 貼文內容、
Facebook cookies / session、物件照片、客戶個資。這些資料永遠留在
使用者本機（Local First）。

## 11. Admin 控制平面（未來）

「HouseFlow Admin」（僅供產品管理者使用）V1 範圍至少需要管理：
License、Trial、Subscription、Device、Pricing、Early Bird、
App Version。

未來能力：建立 License、停權、恢復、延長 30/90 天、自訂贈送天數、
修改 `expires_at`、解除裝置綁定、設定 Early Bird、查看最後一次驗證
時間、查看 App Version。

Global Settings：`current_price`（預設 688 TWD）、`trial_days`
（預設 7）、`offline_grace_days`（預設 7）、`latest_version`、
`minimum_supported_version`。**價格不得寫死在 Desktop UI**——必須來自
這組全域設定。

## 12. 付款（V1）

本輪不整合任何第三方金流。付款由 Admin 人工確認後手動延長 License。
訂閱架構刻意不跟任何特定金流服務商綁死，方便未來接自動付款/續訂/
發票/金流閘道。

## 13. 隱私

- HouseFlow Admin **不應該**看到：客戶姓名/電話、房屋內容、貼文內容、
  Facebook cookies / 密碼 / session。Admin 只管理授權與必要的產品
  metadata。
- Log 記錄同樣避免不必要地記錄：密碼、cookies、access token、
  session 密鑰、完整敏感個資。

## 14. 備份 / 更新 / 資料庫遷移

- **Backup**：見 `app/services/backup_service.py`——建立備份、驗證
  備份、還原備份（manifest + checksum，不含加密，不含 Facebook
  Session）。
- **Updater**：見 `app/services/updater_service.py`——check → release
  notes → download → verify → backup → apply → migrate → launch →
  verify → success/rollback 的狀態機骨架。**禁止**「刪除整個
  Desktop\HouseFlow 再整包覆蓋」的舊部署方式，必須採用
  rename-to-timestamped-backup 的 atomic 部署模式。
- **DB Migration**：見 `app/services/db_migrations.py`——
  `schema_migrations` 版本記錄表 + transactional 套用 + 失敗自動
  rollback。V1 只有 baseline migration（version 1，no-op），刻意
  **沒有**接進 `Database._initialize()` 的正式啟動流程，等待後續
  授權後才會真的對 production DB 寫入版本記錄表。

## 15. 資料/程式分離

- **程式檔**（例如 `C:\Program Files\HouseFlow\`）：exe、runtime、
  Chromium、resources。
- **使用者資料**（`%LOCALAPPDATA%\HouseFlow\`）：資料庫、設定、
  瀏覽器 profile、logs、備份、使用者產生的資料。
- 更新 HouseFlow **絕對不能**刪除使用者資料。
- 解除安裝**預設不**刪除使用者資料。任何未來的刪除都必須是明確、
  獨立的使用者選擇。

## 16. 物件來源架構

「同步中心」不再等於「永慶網站同步」——重新定義為品牌中立的
「物件來源 / Property Sources」。見 `app/services/property_sources/`
的 `PropertySourceConnector` 抽象層與 ARCHITECTURE.md 的說明。

未來預計支援的品牌（**本輪不實作**）：永慶房屋、永慶不動產、永義房屋、
有巢氏房屋、台慶不動產、信義房屋、住商不動產、台灣房屋、中信房屋、
東森房屋、21世紀不動產、太平洋房屋、群義房屋、地方型房仲、公司自有
網站、其他合法來源。

## 17. 不得新增的單一使用者假設

從本輪開始，任何新功能都不可以假設：只有阿嘉本人、只有目前公司、
只有目前門市、只有目前這組 Facebook 帳號、只有目前 Windows 使用者、
只有目前的桌面路徑、只有目前這個網站、只有台慶/永慶、只有目前的
業務員/經紀業證號。所有個人資訊都必須是可設定的（見
`Database._seed_default_brand_profile()` 的修正——新資料庫不再預先
寫死任何真實個人資料）。
