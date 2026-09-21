from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow
from app.services import app_paths


def run() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("HouseFlow")
    app.setOrganizationName("HouseFlow")
    app.setFont(QFont("Microsoft JhengHei UI", 10))
    app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar, True)
    # 關閉視窗（X）預設只是最小化到系統匣，不是真的結束程式（見
    # MainWindow.closeEvent）；沒有這行的話，Qt 在某些情況下會把「隱藏
    # 最後一個可見視窗」誤判成「最後一個視窗關閉」而直接結束整個 app，
    # 連背景執行中的 Automation Engine 都會被砍掉。
    app.setQuitOnLastWindowClosed(False)

    try:
        import qdarktheme
        qdarktheme.setup_theme("light", custom_colors={"primary": "#2563EB"})
    except Exception:
        pass

    app_paths.data_root()
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
