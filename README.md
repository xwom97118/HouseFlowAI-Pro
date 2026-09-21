# HouseFlow

HouseFlow 房仲工作台 —— Windows 桌面應用程式，V1 聚焦於「物件同步 → 安排發文 → Facebook 自動發布／自動刪文 → 分析」這條核心流程：

- Dashboard
- 同步中心（物件來源同步）
- 物件中心
- 發文中心
- 社團管理
- 排程管理
- 分析
- 設定

CRM、成交策略、AI 文案中心目前從 V1 導覽隱藏（程式與既有資料都還在，之後版本會重新開放）。

## Windows 第一次啟動（開發模式）

1. 將 ZIP 完整解壓縮。
2. 雙擊 `run.bat`。
3. 第一次會建立 `.venv` 並安裝套件，完成後自動啟動。
4. 之後可雙擊 `start_only.bat` 快速啟動。

需要先安裝 Python 3.11、3.12 或 3.13，安裝時勾選 **Add Python to PATH**。

## 資料位置

正式安裝（打包後）版本的使用者資料一律存在：

`%LOCALAPPDATA%\HouseFlow\`

（`houseflow.db`、`facebook_browser_profile`、`property_images`、`logs`、`backups`）——跟程式安裝目錄完全分開，更新或重新安裝 HouseFlow 不會動到這裡。

開發模式（直接執行原始碼）則使用專案根目錄下的 `data/`，行為與正式安裝互不影響（見 `app/services/app_paths.py`）。

更新版本前請先備份使用者資料目錄。

## 文件

- [docs/PRODUCT_V1_SPEC.md](docs/PRODUCT_V1_SPEC.md) — 產品規格（授權、試用、訂閱、Admin、Backup、Updater）
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 系統架構（Desktop / Local Data / License Cloud / Admin / Updater / Connector 之間的關係）
