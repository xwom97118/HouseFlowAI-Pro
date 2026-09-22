"""Source-mode smoke test（2026-09-21 產品化 Phase 1，規格第 32 節
Step 13）：完整實例化 MainWindow，確認 V1 導覽隱藏（AI／CRM／成交
策略）不會讓任何既有邏輯崩潰，且完全不會碰觸真正的 production
%LOCALAPPDATA%\\HouseFlow\\ 資料夾。

透過 HOUSEFLOW_DATA_DIR 環境變數把 Database() 導向一個全新的暫存
目錄——MainWindow.__init__() 內部自己 new 一個 Database()，這是目前
唯一能在不修改 MainWindow 建構子的情況下完全隔離測試用資料的方式。
"""
from __future__ import annotations

import os
import shutil
import tempfile

_TEMP_DATA_DIR = tempfile.mkdtemp(prefix="hf_mainwindow_smoke_")
os.environ["HOUSEFLOW_DATA_DIR"] = _TEMP_DATA_DIR

from PySide6.QtWidgets import QApplication, QTabWidget  # noqa: E402

_app = QApplication.instance() or QApplication([])

from app.main_window import MainWindow  # noqa: E402


def test_mainwindow_constructs_without_crashing() -> None:
    window = MainWindow()
    assert window is not None
    window.close()


def test_v1_hidden_keys_are_not_in_nav_buttons() -> None:
    window = MainWindow()
    try:
        for hidden_key in ("ai", "crm", "strategy"):
            assert hidden_key not in window.nav_buttons
    finally:
        window.close()


def test_v1_visible_keys_are_in_nav_buttons() -> None:
    window = MainWindow()
    try:
        for visible_key in (
            "dashboard", "sync_center", "properties", "poster",
            "groups", "schedule", "analytics", "settings",
        ):
            assert visible_key in window.nav_buttons
    finally:
        window.close()


def test_hidden_pages_are_still_instantiated_not_deleted() -> None:
    """程式碼/頁面物件必須保留（只是不顯示導覽按鈕），確保之後要重新
    開放功能時不需要重寫任何東西（規格第 2 節）。"""
    window = MainWindow()
    try:
        for hidden_key in ("ai", "crm", "strategy"):
            assert hidden_key in window.pages, f"{hidden_key} page object should still exist"
    finally:
        window.close()


def test_navigate_to_visible_page_works() -> None:
    window = MainWindow()
    try:
        window.navigate("properties")
        assert window.current_key == "properties"
        assert window.nav_buttons["properties"].isChecked()
    finally:
        window.close()


def test_navigate_to_hidden_page_does_not_crash() -> None:
    """navigate() 對 nav_buttons 的存取已經改成 `if key in self.nav_buttons`
    防呆——即使有內部呼叫路徑意外導到隱藏頁面，也不應該 KeyError。

    "ai" 這個 key 剛好還疊了一層既有（非本輪新增）的 ai_enabled 開關
    檢查，預設關閉時 navigate() 會彈出提示並直接 return、不會真的切換
    頁面——這是既有行為，不是本輪改動的目標，這裡只驗證「不會崩潰」，
    用 mock 避開真的彈出 QMessageBox（headless 測試環境不應該依賴
    使用者手動點掉對話框）。
    """
    from unittest import mock

    window = MainWindow()
    try:
        with mock.patch("app.main_window.QMessageBox.information") as mock_info:
            window.navigate("crm")  # 沒有 ai_enabled 那層檢查，應該正常切換
            assert window.current_key == "crm"
            assert mock_info.called is False
    finally:
        window.close()


def test_dashboard_hides_crm_metric_card() -> None:
    """規格：CRM 已從 V1 導覽隱藏，Dashboard 不應該再顯示一張使用者
    點不到入口的「CRM 客戶」卡片（2026-09-22 Phase 1.1）。"""
    window = MainWindow()
    try:
        dashboard_page = window.pages["dashboard"]
        assert "contacts" not in dashboard_page.cards
        assert "properties" in dashboard_page.cards
        assert "favorites" in dashboard_page.cards
        assert "drafts" in dashboard_page.cards
    finally:
        window.close()


def test_dashboard_refresh_does_not_crash_without_crm_card() -> None:
    window = MainWindow()
    try:
        dashboard_page = window.pages["dashboard"]
        dashboard_page.refresh()  # 不應該因為少了 "contacts" key 而崩潰
    finally:
        window.close()


def test_settings_page_has_license_tab() -> None:
    window = MainWindow()
    try:
        window.navigate("settings")
        settings_page = window.pages["settings"]
        tabs = settings_page.findChild(QTabWidget)
        tab_names = [tabs.tabText(i) for i in range(tabs.count())]
        assert "授權資訊" in tab_names
        assert hasattr(settings_page, "license_panel")
    finally:
        window.close()


def test_smoke_test_did_not_touch_real_localappdata() -> None:
    """回歸性防呆：確認這個測試檔案本身真的把資料目錄導向暫存資料夾，
    不是不小心漏設環境變數而打到真正的 production 路徑。"""
    from app.services import app_paths

    resolved_root = str(app_paths.data_root())
    assert resolved_root.startswith(_TEMP_DATA_DIR)
    assert "AppData\\Local\\HouseFlow" not in resolved_root
    assert "AppData/Local/HouseFlow" not in resolved_root


if __name__ == "__main__":
    import sys

    failures = 0
    tests = [(name, obj) for name, obj in list(globals().items()) if name.startswith("test_")]
    try:
        for name, test in tests:
            try:
                test()
                print(f"PASS: {name}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"FAIL: {name}: {exc}")
        print(f"\n{len(tests) - failures}/{len(tests)} passed")
    finally:
        shutil.rmtree(_TEMP_DATA_DIR, ignore_errors=True)
    sys.exit(1 if failures else 0)
