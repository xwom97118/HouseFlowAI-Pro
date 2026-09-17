from app.services import app_paths
from app.services.browser_runtime import ensure_playwright_browsers_path

# 必須在任何模組實際讀寫使用者資料（資料庫、照片、Facebook 登入）以前
# 執行：把舊版留在安裝目錄裡的資料（如果有）搬到 %LOCALAPPDATA%\HouseFlow\，
# 而且只有在新位置還沒有資料庫時才會動作，不會覆蓋任何既有資料。
app_paths.migrate_legacy_data()

ensure_playwright_browsers_path()

from app.application import run

if __name__ == "__main__":
    run()
