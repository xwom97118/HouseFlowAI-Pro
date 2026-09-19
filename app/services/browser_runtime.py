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


class BundledBrowserMissingError(RuntimeError):
    """封裝版 HouseFlow 找不到隨附的 Chromium 執行檔。"""


def verify_bundled_browser_or_raise() -> None:
    """在真的呼叫 Playwright 啟動瀏覽器之前先確認執行檔存在。

    2026-09-19 發生過一次事故：部署流程在 HouseFlow 還在執行中的時候把
    _internal/pw-browsers 刪除，背景排程到期要發文時，Playwright 嘗試
    啟動一個已經不存在的 chrome.exe，只拋出很難懂的
    [WinError 2] 系統找不到指定的檔案，DB 跟 log 裡完全看不出真正原因。
    這裡提前擋下來，給一個可以直接採取行動的錯誤訊息。

    只在封裝後（frozen）執行時檢查；開發模式沒有隨附的 pw-browsers 資料
    夾，沿用 Playwright 自己在 %LOCALAPPDATA%\\ms-playwright 的預設行為。
    """
    if not getattr(sys, "frozen", False):
        return

    status = browser_runtime_status()
    if not status["bundled_found"] or not status["chrome_path"]:
        raise BundledBrowserMissingError(
            "Facebook 自動化找不到隨附的瀏覽器元件（Chromium）。\n"
            f"預期路徑：{status['browsers_dir']}\n"
            "請重新安裝／重新部署 HouseFlow"
            "（部署時請先關閉正在執行中的 HouseFlow，避免執行中被刪除執行檔）。"
        )


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
