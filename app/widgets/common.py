from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QVBoxLayout,
    QWidget,
)


def emoji_icon(emoji: str, size: int = 22) -> QIcon:
    """把一個 emoji 畫成固定大小的 QIcon，讓 Sidebar 選單圖示不論字符
    本身寬窄都有一致的視覺大小與左側對齊。之後要換成 SVG icon 時，
    只需要換掉這個函式內部的畫法，呼叫端（button.setIcon(...)）不用改。
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    font = painter.font()
    font.setPointSize(int(size * 0.6))
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, emoji)
    painter.end()

    return QIcon(pixmap)


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


class BrandHeader(QFrame):
    """Sidebar 頂部品牌卡。之後要換上正式 Logo 時，只需要改這裡（例如
    在 title 前面加一個 QLabel(QPixmap(...))），呼叫端完全不用動。
    """

    def __init__(self, name: str = "HouseFlow", subtitle: str = "PROFESSIONAL") -> None:
        super().__init__()
        self.setObjectName("BrandCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(2)

        self.title_label = QLabel(name)
        self.title_label.setObjectName("BrandTitle")

        self.subtitle_label = QLabel(" ".join(subtitle))
        self.subtitle_label.setObjectName("BrandSubtitle")

        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)


class AccountStatusCard(QFrame):
    """Sidebar 底部帳號／版本／狀態卡。set_name() 讓 MainWindow 可以在
    品牌名稱變更（例如使用者在設定頁改了顯示名稱）後更新顯示。
    """

    def __init__(self, meta: str = "", version: str = "") -> None:
        super().__init__()
        self.setObjectName("AccountCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(4)

        self.name_label = QLabel("")
        self.name_label.setObjectName("AccountName")
        layout.addWidget(self.name_label)

        self.meta_label = QLabel(meta)
        self.meta_label.setObjectName("AccountMeta")
        layout.addWidget(self.meta_label)

        status_row = QHBoxLayout()
        status_row.setSpacing(6)

        self.status_label = QLabel("● Ready")
        self.status_label.setObjectName("StatusReady")

        self.version_label = QLabel(version)
        self.version_label.setObjectName("AccountVersion")

        status_row.addWidget(self.status_label)
        status_row.addStretch()
        status_row.addWidget(self.version_label)
        layout.addLayout(status_row)

    def set_name(self, name: str) -> None:
        self.name_label.setText(name or "尚未設定品牌名稱")
