from __future__ import annotations

import os
import sys
from pathlib import Path

# PyInstaller onedir/onefile 都會在啟動時設定 sys._MEIPASS 指向解壓後的
# 資料目錄（onedir 版對應 _internal 資料夾）。開發模式下沒有這個屬性，
# 改用專案根目錄。
_BROWSERS_FOLDER_NAME = "pw-browsers"


def _app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def bundled_browsers_dir() -> Path:
    return _app_base_dir() / _BROWSERS_FOLDER_NAME


def ensure_playwright_browsers_path() -> None:
    """讓封裝後的 HouseFlow 使用隨程式一起發行的 Chromium，
    而不是依賴開發電腦上 %LOCALAPPDATA%\\ms-playwright 的快取。

    必須在任何 `from playwright.sync_api import sync_playwright` 的
    程式碼實際啟動瀏覽器之前呼叫（在 main.py 最前面呼叫一次即可）。
    如果找不到隨附的瀏覽器資料夾（例如一般開發環境），就保持
    Playwright 預設行為，不覆蓋環境變數。
    """
    browsers_dir = bundled_browsers_dir()
    if browsers_dir.is_dir() and any(browsers_dir.iterdir()):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_dir)


def browser_runtime_status() -> dict:
    """回傳目前 Chromium 執行環境狀態，供設定頁 / 診斷使用。"""
    browsers_dir = bundled_browsers_dir()
    frozen = bool(getattr(sys, "frozen", False))
    bundled_found = browsers_dir.is_dir() and any(browsers_dir.iterdir())

    chrome_path = ""
    if bundled_found:
        for candidate in browsers_dir.glob("chromium-*/chrome-win*/chrome.exe"):
            chrome_path = str(candidate)
            break

    return {
        "frozen": frozen,
        "browsers_dir": str(browsers_dir),
        "bundled_found": bundled_found,
        "chrome_path": chrome_path,
        "env_override": os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""),
    }
