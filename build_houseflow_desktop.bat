@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

echo.
echo ==========================================
echo   HouseFlow 桌面版建置工具
echo ==========================================
echo.

if not exist "main.py" (
    echo [錯誤] 找不到 main.py
    echo 請把這個檔案放在 HouseFlow 專案最外層再執行。
    pause
    exit /b 1
)

echo [1/6] 更新打包工具...
python -m pip install --upgrade pip pyinstaller
if errorlevel 1 goto :failed

echo [2/6] 安裝專案套件...
python -m pip install -r requirements.txt
if errorlevel 1 goto :failed

echo [3/6] 安裝 Playwright Chromium...
python -m playwright install chromium
if errorlevel 1 goto :failed

echo [4/6] 清除舊版建置檔案...
if exist "build" rmdir /s /q "build"
if exist "dist\HouseFlow" rmdir /s /q "dist\HouseFlow"
if exist "HouseFlow.spec" del /q "HouseFlow.spec"

echo [5/6] 建立 HouseFlow.exe...
python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --onedir ^
  --name "HouseFlow" ^
  --collect-all PySide6 ^
  --collect-all certifi ^
  --collect-all playwright ^
  --collect-all bs4 ^
  --collect-all lxml ^
  --hidden-import "app.application" ^
  --hidden-import "app.main_window" ^
  --hidden-import "app.pages.dashboard" ^
  --hidden-import "app.pages.properties" ^
  --hidden-import "app.pages.poster" ^
  --hidden-import "app.pages.settings" ^
  --hidden-import "app.pages.crm" ^
  --hidden-import "app.pages.strategy" ^
  --hidden-import "app.services.database" ^
  --hidden-import "app.services.facebook_service" ^
  --hidden-import "app.services.copywriting_engine" ^
  --hidden-import "app.widgets.common" ^
  --hidden-import "app.widgets.property_picker" ^
  --hidden-import "app.services.universal_import_service" ^
  --hidden-import "app.widgets.universal_import_dialog" ^
  --add-data "app;app" ^
  --add-data "data;data" ^
  "main.py"

if errorlevel 1 goto :failed

echo [6/6] 複製到桌面並建立捷徑...

set "DESKTOP=%USERPROFILE%\Desktop"
if not exist "%DESKTOP%" set "DESKTOP=%USERPROFILE%\OneDrive\Desktop"

if exist "%DESKTOP%\HouseFlow" rmdir /s /q "%DESKTOP%\HouseFlow"
xcopy "dist\HouseFlow" "%DESKTOP%\HouseFlow\" /E /I /H /Y >nul

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$desktop=[Environment]::GetFolderPath('Desktop');" ^
  "$target=Join-Path $desktop 'HouseFlow\HouseFlow.exe';" ^
  "$shortcut=Join-Path $desktop 'HouseFlow.lnk';" ^
  "$shell=New-Object -ComObject WScript.Shell;" ^
  "$link=$shell.CreateShortcut($shortcut);" ^
  "$link.TargetPath=$target;" ^
  "$link.WorkingDirectory=(Split-Path $target);" ^
  "$link.Description='HouseFlow AI Professional';" ^
  "$link.Save();"

echo.
echo ==========================================
echo   建置完成
echo ==========================================
echo.
echo 桌面已建立：
echo   1. HouseFlow 資料夾
echo   2. HouseFlow 捷徑
echo.
echo 之後直接雙擊桌面的 HouseFlow 即可開啟。
echo.
pause
exit /b 0

:failed
echo.
echo ==========================================
echo   建置失敗
echo ==========================================
echo.
echo 請把這個視窗最後的錯誤畫面截圖傳給我。
echo.
pause
exit /b 1
