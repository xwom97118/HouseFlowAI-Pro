from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QVBoxLayout,
    QWidget,
)


class ImagePreviewList(QListWidget):
    """可拖曳排序的圖片縮圖清單。發文中心與排程對話框共用。"""

    def __init__(self, order_changed) -> None:
        super().__init__()

        self.order_changed = order_changed
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Snap)
        self.setWrapping(True)
        self.setSpacing(10)
        self.setIconSize(QSize(150, 110))
        self.setGridSize(QSize(180, 160))
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def dropEvent(self, event) -> None:
        super().dropEvent(event)
        if callable(self.order_changed):
            self.order_changed()


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
        label.setObjectName("SectionTitleLabel")
        box.addWidget(label)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("Muted")
            box.addWidget(sub)
        layout.addLayout(box)
        layout.addStretch()


class StatusBadge(QLabel):
    """狀態小標籤，例如排程狀態、同步狀態。kind 對應 styles.py 裡的配色。"""

    def __init__(self, text: str = "", kind: str = "neutral") -> None:
        super().__init__(text)
        self.setObjectName("StatusBadge")
        self.setProperty("kind", kind)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_status(self, text: str, kind: str = "neutral") -> None:
        self.setText(text)
        self.setProperty("kind", kind)
        style = self.style()
        if style is not None:
            style.unpolish(self)
            style.polish(self)


class PropertySummaryCard(QFrame):
    """發文中心／排程用的物件摘要卡：縮圖 + 標題 + 售價/格局/坪數 + 地址。"""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Card")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(14)

        self.thumb_label = QLabel("無縮圖")
        self.thumb_label.setObjectName("PropertyThumb")
        self.thumb_label.setFixedSize(104, 78)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.thumb_label)

        text_box = QVBoxLayout()
        text_box.setSpacing(3)

        self.title_label = QLabel("尚未選擇物件")
        self.title_label.setObjectName("PropertyCardTitle")
        self.title_label.setWordWrap(True)

        self.meta_label = QLabel("")
        self.meta_label.setObjectName("Muted")

        self.address_label = QLabel("")
        self.address_label.setObjectName("Muted")
        self.address_label.setWordWrap(True)

        text_box.addWidget(self.title_label)
        text_box.addWidget(self.meta_label)
        text_box.addWidget(self.address_label)
        text_box.addStretch()

        layout.addLayout(text_box, 1)

    def set_property(self, property_data: dict[str, Any] | None) -> None:
        if not property_data:
            self.thumb_label.setPixmap(QPixmap())
            self.thumb_label.setText("無縮圖")
            self.title_label.setText("尚未選擇物件")
            self.meta_label.setText("")
            self.address_label.setText("")
            return

        title = str(property_data.get("title") or "未命名物件")
        price = str(property_data.get("price") or "價格未提供")
        layout_text = str(property_data.get("layout") or "")
        size = str(property_data.get("size") or "")
        address = str(property_data.get("address") or "")

        self.title_label.setText(title)
        self.meta_label.setText("｜".join(part for part in (price, layout_text, size) if part))
        self.address_label.setText(address)

        image_paths = str(property_data.get("image_paths", "")).strip()
        first_image = next((p for p in image_paths.split("\n") if p.strip()), "")

        if first_image and Path(first_image).is_file():
            pixmap = QPixmap(first_image)
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    104, 78,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.thumb_label.setPixmap(scaled)
                return

        self.thumb_label.setPixmap(QPixmap())
        self.thumb_label.setText("無縮圖")
