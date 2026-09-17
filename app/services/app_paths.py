from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "HouseFlow"

# ---------------------------------------------------------------------------
# 設計方式（DEV / PRODUCTION 分離）
# ---------------------------------------------------------------------------
#
# 「程式檔」（安裝/打包目錄，例如 Desktop\HouseFlow\ 或 dist\HouseFlow\）
# 與「使用者資料」（資料庫、Facebook 登入、照片、CRM…）必須分開存放，
# 這樣重新打包／更新程式時才不會動到使用者資料。
#
# PRODUCTION（打包後的 HouseFlow.exe，sys.frozen 為 True）：
#     使用者資料一律放在 %LOCALAPPDATA%\HouseFlow\
#     這個目錄跟安裝目錄完全無關，重新 build / 部署 / 刪除整個
#     Desktop\HouseFlow\ 資料夾都不會影響到它。
#
# DEV（直接 python main.py 執行原始碼，sys.frozen 為 False）：
#     維持使用專案根目錄下的 data/ 資料夾（跟一直以來的開發習慣一樣，
#     不需要另外設定）。
#
#     這樣 DEV 與 PRODUCTION 天生就是兩個完全不同的實體路徑，
#     不可能互相覆蓋 —— 開發時測試不會動到正式的
#     %LOCALAPPDATA%\HouseFlow\，正式版也不會受開發資料夾影響。
#
# 進階：如果需要在開發時模擬／測試 production 資料路徑（例如測試
# migration 邏輯本身），可以設定環境變數 HOUSEFLOW_DATA_DIR 直接
# 指定資料根目錄，兩種模式都適用。


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _dev_project_root() -> Path:
    # app/services/app_paths.py -> app/services -> app -> <project root>
    return Path(__file__).resolve().parents[2]


def _default_data_root() -> Path:
    override = os.environ.get("HOUSEFLOW_DATA_DIR", "").strip()
    if override:
        return Path(override)

    if is_frozen():
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return base / APP_NAME

    return _dev_project_root() / "data"


_data_root_cache: Path | None = None


def data_root() -> Path:
    """所有永久使用者資料的根目錄。"""
    global _data_root_cache
    if _data_root_cache is None:
        root = _default_data_root()
        root.mkdir(parents=True, exist_ok=True)
        _data_root_cache = root
    return _data_root_cache


def db_path() -> Path:
    return data_root() / "houseflow.db"


def property_images_dir() -> Path:
    path = data_root() / "property_images"
    path.mkdir(parents=True, exist_ok=True)
    return path


def facebook_profile_dir() -> Path:
    path = data_root() / "facebook_browser_profile"
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_dir() -> Path:
    # 目前所有設定都存在 SQLite 的 app_settings 表（見 database.py），
    # 這裡先保留這個路徑給未來需要獨立設定檔的情境使用。
    path = data_root() / "settings"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    path = data_root() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def temp_dir() -> Path:
    path = data_root() / "temp"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# 舊版資料自動 migration
# ---------------------------------------------------------------------------
#
# 在這個 path manager 出現以前，封裝後的 HouseFlow 實際上是把資料庫等
# 資料寫在 PyInstaller 解壓目錄裡面（onedir 版即 _internal\data），
# 每次重新 build 都會被整個資料夾覆蓋掉。這裡在第一次啟動新版時，
# 掃描舊的可能位置，安全地「複製」（不是搬移、不刪除舊資料）到新的
# %LOCALAPPDATA%\HouseFlow\，且只在新位置「還沒有資料庫」時才動作，
# 避免覆蓋掉使用者在新位置已經累積的資料。重複執行也不會出錯或
# 造成資料重複。

_DATA_ITEMS = (
    "houseflow.db",
    "houseflow.db-journal",
    "houseflow.db-wal",
    "houseflow.db-shm",
    "houseflow_empty.db.db",
    "property_images",
    "facebook_browser_profile",
)


def _legacy_candidate_dirs() -> list[Path]:
    """依優先順序列出可能藏有舊資料的資料夾。"""
    candidates: list[Path] = []

    if is_frozen():
        exe_dir = Path(sys.executable).resolve().parent
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            # 修這個 bug 以前，DB_PATH 是相對 __file__ 算出來的，frozen
            # 狀態下會落在 PyInstaller 解壓目錄（onedir 版就是 _internal）。
            candidates.append(Path(meipass) / "data")
        # 舊版 build script 的備份/還原機制誤植成保護這個「上一層」的
        # data 資料夾（其實一直沒有真正保護到資料庫，但可能真的存放過
        # 其他東西，例如使用者用捷徑啟動、CWD 落在這裡時寫入的資料）。
        candidates.append(exe_dir / "data")
    else:
        candidates.append(_dev_project_root() / "data")

    return candidates


def migrate_legacy_data() -> dict:
    """啟動時呼叫一次。只在 production 且新資料夾還沒有資料庫時才會
    真的搬資料；回傳搬了什麼、從哪裡搬，方便診斷。可重複執行。
    """
    report: dict = {"migrated": False, "source": "", "items": []}

    target_root = data_root()
    target_db = target_root / "houseflow.db"

    if target_db.exists():
        # 新位置已經有資料庫，視為已經完成過 migration（或是全新安裝
        # 但使用者已經在新位置操作過），一律不動，避免覆蓋較新的資料。
        return report

    for legacy_dir in _legacy_candidate_dirs():
        legacy_db = legacy_dir / "houseflow.db"
        if not legacy_db.exists():
            continue

        report["source"] = str(legacy_dir)

        for name in _DATA_ITEMS:
            source = legacy_dir / name
            if not source.exists():
                continue

            destination = target_root / name

            try:
                if source.is_dir():
                    if destination.exists():
                        continue
                    shutil.copytree(source, destination)
                else:
                    if destination.exists():
                        continue
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
                report["items"].append(name)
            except Exception as exc:
                report.setdefault("errors", []).append(f"{name}: {exc}")

        if report["items"]:
            report["migrated"] = True
            break

    return report
