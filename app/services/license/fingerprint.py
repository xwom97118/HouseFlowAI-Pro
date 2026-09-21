"""裝置指紋（2026-09-21 產品化 Phase 1，見規格第 13 節：「不要使用
單一容易變動的硬體值作 fingerprint」）。

設計取捨：常見的「用 MAC address／硬碟序號／主機板序號算 hash」的
做法，遇到使用者換網卡、重灌系統、更新驅動程式都可能讓 fingerprint
跳號，變成使用者被誤判成「新裝置」而必須聯絡客服解除綁定——這對一個
不打算做侵入式 DRM 的產品來說，誤傷成本比防禦到的濫用高。

這裡採用「本機持久化 ID」策略：第一次啟動時產生一個隨機 UUID，存進
HouseFlow 自己的 app_settings（%LOCALAPPDATA%\\HouseFlow\\houseflow.db，
使用者資料目錄本身也不會被解除安裝／更新動到，見
docs/PRODUCT_V1_SPEC.md 第 5 節），之後每次啟動都讀同一個值。這個 ID
本身不含任何硬體資訊，純粹是「這個使用者資料目錄」的身分——只要
使用者資料目錄還在（正常升級、正常重新安裝都不會動到它），
fingerprint 就穩定；只有真的換了一台全新電腦（全新的使用者資料
目錄）才會產生新的 fingerprint，這正是我們想要偵測的情境。

額外附上 device_name（電腦名稱）跟 os_username 純粹是給 Admin
在解除綁定時方便辨識「這是哪一台裝置」的顯示用資訊，不是比對用的
安全依據。
"""
from __future__ import annotations

import getpass
import hashlib
import os
import platform
import uuid


def _persisted_device_id(get_setting, set_setting) -> str:
    """get_setting/set_setting 是呼叫端注入的存取函式（通常是
    Database.get_setting/Database.set_setting），這裡不直接 import
    Database，避免 license 這個 domain 模組反過來依賴 app 的 DB 實作
    細節，方便未來抽換成別的持久化方式或在測試裡用假的 dict 代替。
    """
    key = "device_local_id"
    existing = get_setting(key, "").strip()
    if existing:
        return existing
    new_id = uuid.uuid4().hex
    set_setting(key, new_id)
    return new_id


def compute_device_fingerprint(get_setting, set_setting) -> str:
    """回傳穩定的裝置指紋（sha256 hex）。get_setting(key, default) /
    set_setting(key, value) 是呼叫端提供的存取函式。"""
    local_id = _persisted_device_id(get_setting, set_setting)
    raw = f"houseflow-device:{local_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def current_device_name() -> str:
    try:
        return platform.node() or "未知裝置"
    except Exception:
        return "未知裝置"


def current_os_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return os.environ.get("USERNAME", "")
