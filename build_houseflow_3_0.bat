@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "APP_NAME=HouseFlow"
set "APP_VERSION=3.0.0"
set "BUILD_LOG=%~dp0HouseFlow_build_log.txt"

REM User data lives in %LOCALAPPDATA%\HouseFlow\ (see app/services/app_paths.py),
REM completely outside this build/deploy folder. This script never reads,
REM writes, or deletes anything under %LOCALAPPDATA%\HouseFlow\ - rebuilding
REM and redeploying only ever touches the application/runtime files below.
set "USER_DATA_DIR=%LOCALAPPDATA%\HouseFlow"
set "DESKTOP=%USERPROFILE%\Desktop"
if not exist "%DESKTOP%" set "DESKTOP=%USERPROFILE%\OneDrive\Desktop"

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

echo [1/7] Checking required files...
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

if not exist "app\pages\sync_center.py" (
    echo ERROR: app\pages\sync_center.py is missing.
    goto :failed
)

if not exist "app\services\sync_runner.py" (
    echo ERROR: app\services\sync_runner.py is missing.
    goto :failed
)

if not exist "app\services\browser_runtime.py" (
    echo ERROR: app\services\browser_runtime.py is missing.
    goto :failed
)

if not exist "app\services\http_client.py" (
    echo ERROR: app\services\http_client.py is missing.
    goto :failed
)

if not exist "app\services\import_runner.py" (
    echo ERROR: app\services\import_runner.py is missing.
    goto :failed
)

if not exist "app\services\app_paths.py" (
    echo ERROR: app\services\app_paths.py is missing.
    goto :failed
)

if not exist "app\pages\schedule.py" (
    echo ERROR: app\pages\schedule.py is missing.
    goto :failed
)

if not exist "app\services\schedule_runner.py" (
    echo ERROR: app\services\schedule_runner.py is missing.
    goto :failed
)

if not exist "app\widgets\schedule_dialog.py" (
    echo ERROR: app\widgets\schedule_dialog.py is missing.
    goto :failed
)

if not exist "houseflow_version_info.txt" (
    echo ERROR: houseflow_version_info.txt is missing.
    goto :failed
)

echo [1b/7] One-time safety net: migrating any pre-app_paths.py user data...
REM Older builds stored the live database/photos/Facebook session inside
REM the app folder itself (Desktop\HouseFlow\_internal\data, or in some
REM builds the top-level Desktop\HouseFlow\data). The next step deletes
REM that whole folder to install the new build, which would destroy that
REM data before the app ever gets a chance to run its own migration. Copy
REM it into %USER_DATA_DIR% now if it's not already there. This is a
REM one-time transitional safety net, not the primary data-protection
REM mechanism going forward - once on app_paths.py, user data never lives
REM under Desktop\HouseFlow\ at all, so there is nothing here to protect
REM on future rebuilds.
if exist "%USER_DATA_DIR%\houseflow.db" (
    echo %USER_DATA_DIR% already has data - nothing to migrate.
) else if exist "%DESKTOP%\HouseFlow\_internal\data\houseflow.db" (
    echo Found data from a previous build inside _internal - copying to %USER_DATA_DIR% ...
    if not exist "%USER_DATA_DIR%" mkdir "%USER_DATA_DIR%"
    robocopy "%DESKTOP%\HouseFlow\_internal\data" "%USER_DATA_DIR%" /E /COPY:DAT /R:2 /W:2 /NFL /NDL /NJH /NJS >nul
) else if exist "%DESKTOP%\HouseFlow\data\houseflow.db" (
    echo Found data from a previous build in the top-level data folder - copying to %USER_DATA_DIR% ...
    if not exist "%USER_DATA_DIR%" mkdir "%USER_DATA_DIR%"
    robocopy "%DESKTOP%\HouseFlow\data" "%USER_DATA_DIR%" /E /COPY:DAT /R:2 /W:2 /NFL /NDL /NJH /NJS >nul
) else (
    echo No previous-version data found under Desktop\HouseFlow - nothing to migrate.
)

echo [2/7] Installing build tools...
python -m pip install --upgrade pip pyinstaller certifi >> "%BUILD_LOG%" 2>&1
if errorlevel 1 goto :failed

echo [3/7] Installing project requirements...
python -m pip install -r requirements.txt >> "%BUILD_LOG%" 2>&1
if errorlevel 1 goto :failed

echo [4/7] Installing Playwright Chromium into local bundle folder...
set "PLAYWRIGHT_BROWSERS_PATH=%CD%\pw-browsers"
python -m playwright install chromium >> "%BUILD_LOG%" 2>&1
if errorlevel 1 goto :failed

if not exist "pw-browsers" (
    echo ERROR: pw-browsers folder was not created by playwright install.
    goto :failed
)

echo [5/7] Removing old build files (application/runtime only)...
if exist "build" rmdir /s /q "build"
if exist "dist\HouseFlow" rmdir /s /q "dist\HouseFlow"
if exist "HouseFlow.spec" del /q "HouseFlow.spec"

echo [6/7] Building HouseFlow.exe...
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
  --hidden-import "app.services.sync_runner" ^
  --hidden-import "app.services.browser_runtime" ^
  --hidden-import "app.services.http_client" ^
  --hidden-import "app.services.import_runner" ^
  --hidden-import "app.services.app_paths" ^
  --hidden-import "app.services.facebook_service" ^
  --hidden-import "app.services.copywriting_engine" ^
  --hidden-import "app.services.universal_import_service" ^
  --hidden-import "app.services.schedule_runner" ^
  --hidden-import "app.pages.sync_center" ^
  --hidden-import "app.pages.schedule" ^
  --hidden-import "app.widgets.common" ^
  --hidden-import "app.widgets.property_picker" ^
  --hidden-import "app.widgets.universal_import_dialog" ^
  --hidden-import "app.widgets.schedule_dialog" ^
  --add-data "app;app" ^
  --add-data "pw-browsers;pw-browsers" ^
  "main.py" >> "%BUILD_LOG%" 2>&1

if errorlevel 1 goto :failed

if not exist "dist\HouseFlow\HouseFlow.exe" (
    echo ERROR: dist\HouseFlow\HouseFlow.exe was not created.
    goto :failed
)

echo [7/7] Copying application files to desktop...
REM This only replaces the application/runtime folder. User data lives in
REM %LOCALAPPDATA%\HouseFlow\ and is never touched by this step.
if exist "%DESKTOP%\HouseFlow" rmdir /s /q "%DESKTOP%\HouseFlow"
xcopy "dist\HouseFlow" "%DESKTOP%\HouseFlow\" /E /I /H /Y >nul
if errorlevel 1 goto :failed

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
echo User data folder (not touched by this build): %USER_DATA_DIR%
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
