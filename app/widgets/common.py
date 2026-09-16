from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


class MetricCard(QFrame):
    def __init__(self, title: str, value: str = "0", subtitle: str = "") -> None:
        super().__init__()
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        title_label = QLabel(title)
        title_label.setObjectName("Muted")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("MetricValue")
        layout.addWidget(title_label)
        layout.addWidget(self.value_label)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("Muted")
            layout.addWidget(sub)

    def set_value(self, value: int | str) -> None:
        self.value_label.setText(str(value))


class SectionTitle(QWidget):
    def __init__(self, title: str, subtitle: str = "") -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        box = QVBoxLayout()
        label = QLabel(title)
        label.setStyleSheet("font-size:18px;font-weight:700;")
        box.addWidget(label)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("Muted")
            box.addWidget(sub)
        layout.addLayout(box)
        layout.addStretch()
