@echo off
setlocal
cd /d "%~dp0"
title HouseFlow

if exist ".venv\Scripts\python.exe" goto run

echo First-time setup. This may take several minutes.
where py >nul 2>&1
if %errorlevel%==0 (
  py -3 -m venv .venv
) else (
  where python >nul 2>&1
  if not %errorlevel%==0 goto nopython
  python -m venv .venv
)
if errorlevel 1 goto failed

".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed

:run
".venv\Scripts\python.exe" main.py
if errorlevel 1 goto failed
exit /b 0

:nopython
echo Python was not found.
echo Install Python 3.11, 3.12, or 3.13 from python.org.
echo During installation, enable Add Python to PATH.
pause
exit /b 1

:failed
echo.
echo HouseFlow could not start.
echo Please send a screenshot of all error text in this window.
pause
exit /b 1
