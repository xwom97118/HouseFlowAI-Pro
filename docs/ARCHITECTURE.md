# HouseFlow 架構說明

> 程式碼層的架構文件，對應 [PRODUCT_V1_SPEC.md](PRODUCT_V1_SPEC.md)
> 的產品規格。目標讀者是之後要維護/擴充這個 codebase 的人（包含未來
> 的我自己）。

## 1. 整體分層

```
┌─────────────────────────────────────────────────────────┐
│  Desktop App (PySide6)                                   │
│  app/main_window.py, app/pages/*, app/widgets/*           │
├─────────────────────────────────────────────────────────┤
│  Local Data                                                │
│  app/services/database.py (SQLite)                        │
│  %LOCALAPPDATA%\HouseFlow\ (production) / data/ (dev)      │
├─────────────────────────────────────────────────────────┤
│  Domain Services（跟 UI、跟特定後端都解耦）                  │
│  - app/services/license/        License 網域模型 + 邏輯      │
│  - app/services/property_sources/  Connector 抽象層          │
│  - app/services/db_migrations.py   Schema migration         │
│  - app/services/backup_service.py  Backup/Restore           │
│  - app/services/updater_service.py Update 狀態機骨架          │
│  - app/services/facebook_service.py 【受保護，見下】          │
├─────────────────────────────────────────────────────────┤
│  未來：License Cloud + Admin（V1 只有介面，沒有真正的伺服器）  │
└─────────────────────────────────────────────────────────┘
```

設計原則：**Desktop 端只依賴介面（ABC），不直接依賴任何特定後端
實作**。License、Property Source、Update 都是這個模式——現在只有
本機/mock 實作，之後要換成真正打 Cloud API 的版本時，UI 層完全不用
改，只要在依賴注入的地方換一個實作。

## 2. Facebook Pipeline（受保護）

`app/services/facebook_service.py`、`app/services/automation_engine.py`、
`app/services/schedule_runner.py`、`app/services/content_safety.py` 是
已經通過真實 Facebook 帳號端到端驗證（發布 → 擷取 → 5 分鐘後自動刪除
→ 雙重驗證刪除成功）的穩定 checkpoint（`b3d28a8`）。

**產品化工程不重寫這些檔案**。這裡列出的所有新架構（License、
Property Source Connector、Migration、Backup、Updater）都是**加法**
——包在外面或並排存在，沒有一個改動了 Facebook 發布/擷取/刪除的判斷
邏輯、DOM selector，或 unique-target 刪除安全機制。

如果未來要對這個範圍動刀，前提是：(1) 有具體的 regression/bug，
(2) 先用 mock/temp 資料驗證，(3) 絕不放寬 unique-target 刪除安全
機制、絕不用猜測辨識 Facebook 貼文身分。

## 3. License 網域層

```
app/services/license/
├── models.py       License / TrialState / DeviceBinding /
│                   LicenseCheckResult dataclass，LicenseStatus 等 Enum
├── evaluation.py    evaluate_license() —— 純函式，算「現在能不能用」
│                    （trial / active / expired / suspended /
│                    offline grace / clock-tamper），不做任何 I/O
├── fingerprint.py   compute_device_fingerprint() —— 本機持久化隨機 UUID
├── service.py       LicenseService(ABC) 介面 + 例外類別
└── mock_provider.py MockLicenseProvider —— 本輪唯一接進 Desktop 的實作
```

`MockLicenseProvider` 把狀態存成一個 JSON blob，寫在既有的
`app_settings` table（透過呼叫端注入的 `db.get_setting`/
`db.set_setting`，不直接 import `Database`）。UI 端（
`app/widgets/license_widgets.py` 的 `LicenseInfoPanel` /
`ActivationDialog`，掛載在 Settings 頁「授權資訊」分頁）只認
`LicenseService` 這個介面。

未來真正的 Cloud provider 只需要：
1. 實作 `LicenseService` 的四個抽象方法，內部改成打 HTTPS API。
2. `check_license()` 傳回的 `last_verified_at` 必須是**伺服器回應的
   時間戳記**，不能是本機時間——這樣才能真正防止使用者自己調時鐘
   繞過驗證（見 `evaluation.py` 的 docstring）。
3. Desktop 端（`SettingsPage`、未來的 First Run Wizard）不需要改一行。

## 4. Property Source Connector

```
app/services/property_sources/
├── base.py                PropertySourceConnector(ABC), NormalizedProperty
├── yungching_connector.py YungchingConnector —— wrap 既有 YungchingSyncService
└── registry.py             PropertySourceRegistry, default_registry()
```

`YungchingConnector` **不重寫**既有、已經在 production 驗證穩定的
`YungchingSyncService`（`app/services/sync_service.py`）——純粹
delegate `fetch_properties()`，額外做 `normalize_property()` 把結果轉
成跨品牌統一的 `NormalizedProperty`。

**這一輪刻意沒有把 `execute_source_sync()` / `SyncRunner` /
`AutomationEngine` 的實際呼叫路徑改成透過這裡的 Connector**——那條
路徑已經是 production 正在使用、已驗證穩定的程式碼。這裡先把「形狀」
建好、測試過，之後真的要讓 sync 流程改用 Connector Registry（進而支援
第二個品牌）是刻意留給下一階段的決定。

新增品牌時，只需要新增一個 `PropertySourceConnector` 子類別並在
`registry.py` 註冊，不需要動到 `database.py` 的 schema 或
`sync_runner.py` 的 pipeline。

## 5. Schema Migration

```
app/services/db_migrations.py
├── Migration(ABC)          單一版本的 schema 變更，apply() 必須冪等
├── BaselineMigration        version 1，no-op，代表現有 production schema
└── MigrationRunner          schema_migrations 表 + transactional apply
                              + 失敗自動 rollback
```

取代原本 `database.py` 裡一整排 `_ensure_*_columns()` 的隱性升級方式
——新方式有明確的版本記錄，之後要做「不只是加欄位」的真正資料轉換時
才有辦法追蹤「這個資料庫現在是哪個版本」。

**這一輪沒有接進 `Database._initialize()`**——接上去的那一刻，
`schema_migrations` table 就會被寫進下次啟動時碰到的 production
資料庫，而本輪的規則是 Production DB 唯讀，除非明確授權。是否／何時
接上去留給下一階段決定（`test_db_migrations.py` 裡有一個測試專門
驗證這件事目前確實還沒發生）。

## 6. Backup / Restore

```
app/services/backup_service.py
├── create_backup(data_dir, backup_dir) -> BackupManifest
├── verify_backup(backup_dir) -> BackupVerificationResult
└── restore_backup(backup_dir, target_data_dir, overwrite=False)
```

manifest（`manifest.json`）記錄版本、時間、內含項目、每個檔案的
sha256 checksum。備份內容：`houseflow.db`（+ wal/shm/journal）、
`property_images/`、`settings/`。**排除** `facebook_browser_profile/`
——換電腦後使用者應該重新登入 Facebook，不是把登入 session 到處帶著
走。目前沒有任何 UI 進入點會呼叫這裡的函式；只在測試中對暫存目錄
操作過。不做加密（規格明確要求先不要發明不安全的加密方案）。

## 7. Updater 狀態機骨架

```
app/services/updater_service.py
├── UpdateMetadata / UpdateProvider(ABC) / MockUpdateProvider
├── check_for_update(current_version, provider) -> UpdateCheckResult
├── UpdateStage (Enum)      狀態機的每一步
└── perform_update(...)     驅動整個流程，任何步驟失敗都會嘗試用
                              backup_service 建立的備份 rollback
```

`UpdateSteps.download_update()` / `apply_update()` 預設是
`NotImplementedError`——這一輪沒有真正的 Update Server，不會真的下載
或安裝任何東西。`apply_update()` 的 docstring 明確要求未來實作時必須
用 rename-to-timestamped-backup 的 atomic 部署模式，**禁止**沿用舊的
「刪除整個 Desktop\HouseFlow 再整包覆蓋」部署方式（那個舊方式就是
Phase B 發現「部署的 exe 沒反映最新原始碼」問題的根源）。

## 8. V1 導覽隱藏

`app/main_window.py` 的 `V1_HIDDEN_NAV_KEYS = {"ai", "crm", "strategy"}`
只影響側邊欄按鈕清單的建構（`all_navs` 過濾），**不影響**
`self.pages` 的實際頁面物件建立（AI/CRM/成交策略頁面仍然被正常
實例化，程式碼與資料表完全保留）。`navigate()` 對 `nav_buttons` 的存取
改成 `if key in self.nav_buttons` 防呆，因為隱藏後的 key 理論上仍可能
被內部呼叫路徑觸發。

## 9. 資料目錄

見 `app/services/app_paths.py`。Production（`sys.frozen`）用
`%LOCALAPPDATA%\HouseFlow\`；Dev 用專案根目錄下的 `data/`；兩者都可以
用環境變數 `HOUSEFLOW_DATA_DIR` 覆蓋（測試/診斷用，例如這一輪所有新
測試檔案都是對暫存目錄操作，不依賴、也不觸碰這個環境變數指到的真正
路徑）。
