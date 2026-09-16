@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "APP_NAME=HouseFlow"
set "APP_VERSION=3.0.0"
set "BUILD_LOG=%~dp0HouseFlow_build_log.txt"
set "TEMP_DATA=%TEMP%\HouseFlow_data_backup"

echo.
echo ==================================================
echo   HouseFlow Professional %APP_VERSION% Builder
echo ==================================================
echo Project folder: %CD%
echo.

if not exist "main.py" (
    echo ERROR: main.py was not found.
    echo Put this BAT file in the project root folder.
    goto :failed
)

if not exist "requirements.txt" (
    echo ERROR: requirements.txt was not found.
    goto :failed
)

if not exist "app" (
    echo ERROR: app folder was not found.
    goto :failed
)

where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python was not found in PATH.
    goto :failed
)

echo Build started: %date% %time% > "%BUILD_LOG%"
echo Project folder: %CD% >> "%BUILD_LOG%"
echo. >> "%BUILD_LOG%"

echo [1/8] Checking required files...
if not exist "app\services\universal_import_service.py" (
    echo ERROR: app\services\universal_import_service.py is missing.
    goto :failed
)

if not exist "app\widgets\universal_import_dialog.py" (
    echo ERROR: app\widgets\universal_import_dialog.py is missing.
    goto :failed
)

if not exist "app\widgets\property_picker.py" (
    echo ERROR: app\widgets\property_picker.py is missing.
    goto :failed
)

if not exist "houseflow_version_info.txt" (
    echo ERROR: houseflow_version_info.txt is missing.
    goto :failed
)

echo [2/8] Installing build tools...
python -m pip install --upgrade pip pyinstaller certifi >> "%BUILD_LOG%" 2>&1
if errorlevel 1 goto :failed

echo [3/8] Installing project requirements...
python -m pip install -r requirements.txt >> "%BUILD_LOG%" 2>&1
if errorlevel 1 goto :failed

echo [4/8] Installing Playwright Chromium...
python -m playwright install chromium >> "%BUILD_LOG%" 2>&1
if errorlevel 1 goto :failed

echo [5/8] Backing up desktop data...
set "DESKTOP=%USERPROFILE%\Desktop"
if not exist "%DESKTOP%" set "DESKTOP=%USERPROFILE%\OneDrive\Desktop"

if exist "%TEMP_DATA%" rmdir /s /q "%TEMP_DATA%"

if exist "%DESKTOP%\HouseFlow\data" (
    mkdir "%TEMP_DATA%" >nul 2>nul
    robocopy "%DESKTOP%\HouseFlow\data" "%TEMP_DATA%" /E /NFL /NDL /NJH /NJS /NC /NS >nul
)

echo [6/8] Removing old build files...
if exist "build" rmdir /s /q "build"
if exist "dist\HouseFlow" rmdir /s /q "dist\HouseFlow"
if exist "HouseFlow.spec" del /q "HouseFlow.spec"

echo [7/8] Building HouseFlow.exe...
python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --onedir ^
  --name "HouseFlow" ^
  --collect-all PySide6 ^
  --collect-all certifi ^
  --collect-all requests ^
  --collect-all urllib3 ^
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
  --hidden-import "app.services.sync_service" ^
  --hidden-import "app.services.facebook_service" ^
  --hidden-import "app.services.copywriting_engine" ^
  --hidden-import "app.services.universal_import_service" ^
  --hidden-import "app.widgets.common" ^
  --hidden-import "app.widgets.property_picker" ^
  --hidden-import "app.widgets.universal_import_dialog" ^
  --add-data "app;app" ^
  --add-data "data;data" ^
  "main.py" >> "%BUILD_LOG%" 2>&1

if errorlevel 1 goto :failed

if not exist "dist\HouseFlow\HouseFlow.exe" (
    echo ERROR: dist\HouseFlow\HouseFlow.exe was not created.
    goto :failed
)

echo [8/8] Copying to desktop...
if exist "%DESKTOP%\HouseFlow" rmdir /s /q "%DESKTOP%\HouseFlow"
xcopy "dist\HouseFlow" "%DESKTOP%\HouseFlow\" /E /I /H /Y >nul
if errorlevel 1 goto :failed

if exist "%TEMP_DATA%" (
    robocopy "%TEMP_DATA%" "%DESKTOP%\HouseFlow\data" /E /NFL /NDL /NJH /NJS /NC /NS >nul
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$desktop=[Environment]::GetFolderPath('Desktop');" ^
  "$target=Join-Path $desktop 'HouseFlow\HouseFlow.exe';" ^
  "$shortcut=Join-Path $desktop 'HouseFlow.lnk';" ^
  "$shell=New-Object -ComObject WScript.Shell;" ^
  "$link=$shell.CreateShortcut($shortcut);" ^
  "$link.TargetPath=$target;" ^
  "$link.WorkingDirectory=(Split-Path $target);" ^
  "$link.Description='HouseFlow Professional %APP_VERSION%';" ^
  "$link.Save();"

if errorlevel 1 goto :failed

echo.
echo ==================================================
echo   BUILD COMPLETE
echo ==================================================
echo Desktop folder: %DESKTOP%\HouseFlow
echo Desktop shortcut: HouseFlow
echo Build log: %BUILD_LOG%
echo.
start "" "%DESKTOP%\HouseFlow"
pause
exit /b 0

:failed
echo.
echo ==================================================
echo   BUILD FAILED
echo ==================================================
echo Check this log file:
echo %BUILD_LOG%
echo.
pause
exit /b 1
