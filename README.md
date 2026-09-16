# HouseFlow AI Professional 2.0.1

房仲日常工作桌面工具，包含：

- Dashboard
- 永慶／台慶物件同步
- 收藏、標籤、備註
- CRM 買方與屋主管理
- 龍潭成交策略產生與保存
- AI 文案中心（預設關閉）
- 設定、排程、發布與分析入口

## Windows 第一次啟動

1. 將 ZIP 完整解壓縮。
2. 雙擊 `run.bat`。
3. 第一次會建立 `.venv` 並安裝套件，完成後自動啟動。
4. 之後可雙擊 `start_only.bat` 快速啟動。

需要先安裝 Python 3.11、3.12 或 3.13，安裝時勾選 **Add Python to PATH**。

## 資料位置

所有物件、收藏、備註、CRM 與成交策略都儲存在：

`data/houseflow.db`

更新版本前請先備份此檔案。
