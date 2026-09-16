from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from app.widgets.common import SectionTitle

class PlaceholderPage(QWidget):
    def __init__(self, title: str, message: str) -> None:
        super().__init__()
        root = QVBoxLayout(self); root.setContentsMargins(24,22,24,24); root.setSpacing(16)
        root.addWidget(SectionTitle(title, message))
        label = QLabel("此模組已建立介面位置，下一個 Sprint 會接上完整功能。")
        label.setObjectName("Muted")
        root.addWidget(label); root.addStretch()
