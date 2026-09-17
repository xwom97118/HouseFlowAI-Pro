from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow
from app.services import app_paths


def run() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("HouseFlow AI Professional")
    app.setOrganizationName("HouseFlow AI")
    app.setFont(QFont("Microsoft JhengHei UI", 10))
    app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar, True)

    try:
        import qdarktheme
        qdarktheme.setup_theme("light", custom_colors={"primary": "#2563EB"})
    except Exception:
        pass

    app_paths.data_root()
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
