from __future__ import annotations

import webbrowser
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.database import Database
from app.services.sync_service import YungchingSyncService
from app.widgets.common import SectionTitle
from app.widgets.universal_import_dialog import UniversalImportDialog

DEFAULT_SOURCE_URL = (
    "https://shop.yungching.com.tw/"
    "034990660/list/%E4%BD%8F%E5%AE%85_p"
)


class PropertiesPage(QWidget):
    def __init__(
        self,
        db: Database,
        open_ai: Callable[[int], None],
        go_dashboard: Callable[[], None],
    ) -> None:
        super().__init__()
        self.db = db
        self.open_ai = open_ai
        self.go_dashboard = go_dashboard
        self.sync_service = YungchingSyncService()
        self.rows: list[dict] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 24)
        root.setSpacing(14)

        title_row = QHBoxLayout()
        back_btn = QPushButton("← 返回 Dashboard")
        back_btn.setObjectName("SecondaryButton")
        back_btn.clicked.connect(lambda _=False: self.go_dashboard())
        title_row.addWidget(back_btn)
        title_row.addWidget(
            SectionTitle(
                "物件中心",
                "同步、搜尋、收藏、標籤與備註都集中在這裡。",
            ),
            1,
        )
        root.addLayout(title_row)

        sync_row = QHBoxLayout()
        self.source_url = QLineEdit()
        self.source_url.setPlaceholderText("貼上永慶或台慶店頭物件列表網址（整店同步）")
        self.source_url.setText(
            self.db.get_setting("property_source_url", DEFAULT_SOURCE_URL)
        )
        self.sync_button = QPushButton("同步整店物件")
        self.sync_button.setObjectName("PrimaryButton")
        self.sync_button.clicked.connect(self.sync_properties)

        self.single_import_button = QPushButton(
            "＋ 匯入單一物件網址"
        )
        self.single_import_button.setObjectName(
            "SecondaryButton"
        )
        self.single_import_button.clicked.connect(
            self.open_universal_import
        )

        sync_row.addWidget(QLabel("整店同步網址："))
        sync_row.addWidget(self.source_url, 1)
        sync_row.addWidget(self.sync_button)
        sync_row.addWidget(self.single_import_button)
        root.addLayout(sync_row)

        tools = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜尋名稱、地址、價格、編號、標籤或備註…")
        self.search.textChanged.connect(self.refresh)
        self.favorites_only = QCheckBox("只看收藏")
        self.favorites_only.toggled.connect(self.refresh)

        refresh_btn = QPushButton("重新整理")
        refresh_btn.setObjectName("SecondaryButton")
        refresh_btn.clicked.connect(self.refresh)
        self.favorite_btn = QPushButton("⭐ 收藏／取消")
        self.favorite_btn.setObjectName("SecondaryButton")
        self.favorite_btn.clicked.connect(self.favorite_property)
        note_btn = QPushButton("📝 標籤與備註")
        note_btn.setObjectName("SecondaryButton")
        note_btn.clicked.connect(self.edit_note)
        open_btn = QPushButton("開啟原始網頁")
        open_btn.setObjectName("SecondaryButton")
        open_btn.clicked.connect(self.open_url)
        ai_btn = QPushButton("送到 AI 文案")
        ai_btn.setObjectName("PrimaryButton")
        ai_btn.clicked.connect(self.send_to_ai)

        tools.addWidget(self.search, 1)
        tools.addWidget(self.favorites_only)
        tools.addWidget(refresh_btn)
        tools.addWidget(self.favorite_btn)
        tools.addWidget(note_btn)
        tools.addWidget(open_btn)
        tools.addWidget(ai_btn)
        root.addLayout(tools)

        self.status_label = QLabel("準備完成")
        self.status_label.setObjectName("MutedLabel")
        root.addWidget(self.status_label)

        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(
            ["收藏", "ID", "物件編號", "物件名稱", "地址", "價格", "格局", "坪數", "標籤", "備註"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(self.edit_note)
        self.table.itemSelectionChanged.connect(self.update_selection_status)
        root.addWidget(self.table, 1)
        self.refresh()

    def refresh(self, *_args) -> None:
        selected_id = None
        selected = self.selected()
        if selected:
            selected_id = selected.get("id")
        self.rows = self.db.list_properties(
            self.search.text().strip(),
            self.favorites_only.isChecked(),
        )
        self.table.setRowCount(len(self.rows))
        selected_row = -1
        for row_index, row in enumerate(self.rows):
            values = [
                "★" if int(row.get("favorite", 0) or 0) else "",
                row.get("id", ""), row.get("external_id", ""), row.get("title", ""),
                row.get("address", ""), row.get("price", ""), row.get("layout", ""),
                row.get("size", ""), row.get("tag", ""), row.get("note", ""),
            ]
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                if column_index in (0, 1, 2, 5, 6, 7, 8):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row_index, column_index, item)
            if row.get("id") == selected_id:
                selected_row = row_index
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(3, 280)
        self.table.setColumnWidth(4, 220)
        self.table.setColumnWidth(9, 300)
        if selected_row >= 0:
            self.table.selectRow(selected_row)
        favorites = sum(int(row.get("favorite", 0) or 0) for row in self.rows)
        self.status_label.setText(f"目前顯示 {len(self.rows)} 筆物件，其中 {favorites} 筆收藏")

    def selected(self) -> dict | None:
        row_index = self.table.currentRow()
        return self.rows[row_index] if 0 <= row_index < len(self.rows) else None

    def update_selection_status(self) -> None:
        row = self.selected()
        if row:
            state = "已收藏" if int(row.get("favorite", 0) or 0) else "未收藏"
            self.status_label.setText(f"已選擇：{row.get('title', '')}｜{state}")

    def favorite_property(self) -> None:
        row = self.selected()
        if not row:
            QMessageBox.information(self, "尚未選擇物件", "請先點選一筆物件。")
            return
        property_id = int(row["id"])
        data = self.db.get_note(property_id)
        new_favorite = 0 if int(data.get("favorite", 0) or 0) else 1
        self.db.save_note(property_id, new_favorite, str(data.get("tag", "")), str(data.get("note", "")))
        self.refresh()
        message = "已加入收藏" if new_favorite else "已取消收藏"
        self.status_label.setText(f"{message}：{row.get('title', '')}")

    def edit_note(self, *_args) -> None:
        row = self.selected()
        if not row:
            QMessageBox.information(self, "尚未選擇物件", "請先點選一筆物件。")
            return
        property_id = int(row["id"])
        data = self.db.get_note(property_id)
        tags = ["未分類", "專任委託", "一般委託", "重點推薦", "待追蹤", "已成交", "暫停銷售"]
        old_tag = str(data.get("tag", "") or "未分類")
        if old_tag not in tags:
            tags.append(old_tag)
        selected_tag, ok = QInputDialog.getItem(self, "物件標籤", "請選擇標籤：", tags, tags.index(old_tag), False)
        if not ok:
            return
        note_text, ok = QInputDialog.getMultiLineText(
            self, "物件備註", "請輸入備註：", str(data.get("note", "") or "")
        )
        if not ok:
            return
        self.db.save_note(property_id, int(data.get("favorite", 0) or 0), selected_tag, note_text)
        self.refresh()
        self.status_label.setText(f"已儲存標籤與備註：{row.get('title', '')}")

    def sync_properties(self) -> None:
        source_url = self.source_url.text().strip()
        if not source_url:
            QMessageBox.warning(self, "缺少網址", "請先輸入永慶或台慶店頭物件列表網址；若要匯入其他公司的單一物件，請按「匯入單一物件網址」。")
            return
        self.db.set_setting("property_source_url", source_url)
        self.sync_button.setEnabled(False)
        self.sync_button.setText("同步中…")
        self.status_label.setText("正在讀取網站，請稍候…")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            result = self.sync_service.fetch(source_url)
            saved = self.db.upsert_properties(result.properties, source_url)
            self.refresh()
            QMessageBox.information(
                self, "同步完成",
                f"網站找到：{result.found} 筆\n儲存或更新：{saved} 筆\n\n收藏、標籤與備註不會被覆蓋。",
            )
        except Exception as exc:
            self.status_label.setText("同步失敗，請檢查網址或網路。")
            QMessageBox.critical(self, "同步失敗", f"無法同步物件。\n\n錯誤內容：{exc}")
        finally:
            QApplication.restoreOverrideCursor()
            self.sync_button.setEnabled(True)
            self.sync_button.setText("同步整店物件")

    def open_universal_import(self) -> None:
        dialog = UniversalImportDialog(
            db=self.db,
            on_imported=self.refresh,
            parent=self,
        )
        dialog.exec()

    def send_to_ai(self) -> None:
        row = self.selected()
        if not row:
            QMessageBox.information(self, "尚未選擇物件", "請先點選一筆物件。")
            return
        if self.db.get_setting("ai_enabled", "0") != "1":
            QMessageBox.information(
                self, "AI 目前已關閉",
                "目前先停用 OpenAI，避免再次出現額度錯誤。可在「設定」中重新開啟。",
            )
            return
        self.open_ai(int(row["id"]))

    def open_url(self) -> None:
        row = self.selected()
        if not row:
            QMessageBox.information(self, "尚未選擇物件", "請先點選一筆物件。")
            return
        url = str(row.get("url", "")).strip()
        if not url:
            QMessageBox.warning(self, "沒有網址", "這筆物件沒有原始網頁網址。")
            return
        webbrowser.open(url)