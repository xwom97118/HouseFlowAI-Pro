from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
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
from app.widgets.common import SectionTitle


class GroupsPage(QWidget):
    def __init__(self, db: Database, go_dashboard) -> None:
        super().__init__()

        self.db = db
        self.go_dashboard = go_dashboard
        self.rows: list[dict] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 24)
        root.setSpacing(14)

        header = QHBoxLayout()

        back_button = QPushButton("← 返回 Dashboard")
        back_button.setObjectName("SecondaryButton")
        back_button.clicked.connect(self.go_dashboard)

        header.addWidget(back_button)
        header.addStretch()

        root.addLayout(header)

        root.addWidget(
            SectionTitle(
                "Facebook 社團管理",
                "新增常用社團，之後可直接在發文中心勾選。",
            )
        )

        form_row = QHBoxLayout()

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("社團名稱，例如：龍潭大小事")

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText(
            "社團網址，例如：https://www.facebook.com/groups/xxxxxxxx"
        )

        self.save_button = QPushButton("新增社團")
        self.save_button.setObjectName("PrimaryButton")
        self.save_button.clicked.connect(self.save_group)

        form_row.addWidget(QLabel("名稱"))
        form_row.addWidget(self.name_input, 1)
        form_row.addWidget(QLabel("網址"))
        form_row.addWidget(self.url_input, 2)
        form_row.addWidget(self.save_button)

        root.addLayout(form_row)

        action_row = QHBoxLayout()

        refresh_button = QPushButton("重新整理")
        refresh_button.setObjectName("SecondaryButton")
        refresh_button.clicked.connect(self.refresh)

        toggle_button = QPushButton("啟用／停用")
        toggle_button.setObjectName("SecondaryButton")
        toggle_button.clicked.connect(self.toggle_selected)

        delete_button = QPushButton("刪除社團")
        delete_button.setObjectName("SecondaryButton")
        delete_button.clicked.connect(self.delete_selected)

        action_row.addWidget(refresh_button)
        action_row.addWidget(toggle_button)
        action_row.addWidget(delete_button)
        action_row.addStretch()

        root.addLayout(action_row)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["ID", "社團名稱", "社團網址", "狀態"]
        )
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self.load_selected)

        root.addWidget(self.table, 1)

        self.status_label = QLabel("準備完成")
        self.status_label.setObjectName("MutedLabel")
        root.addWidget(self.status_label)

        self.refresh()

    def refresh(self) -> None:
        self.rows = self.db.list_facebook_groups()
        self.table.setRowCount(len(self.rows))

        for row_index, row in enumerate(self.rows):
            enabled = int(row.get("enabled", 1) or 0)

            values = [
                row.get("id", ""),
                row.get("name", ""),
                row.get("url", ""),
                "啟用" if enabled else "停用",
            ]

            for column_index, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))

                if column_index in (0, 3):
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignCenter
                    )

                self.table.setItem(
                    row_index,
                    column_index,
                    item,
                )

        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(1, 240)
        self.table.setColumnWidth(2, 620)
        self.table.setColumnWidth(3, 90)

        self.status_label.setText(
            f"目前共有 {len(self.rows)} 個 Facebook 社團"
        )

    def selected(self) -> dict | None:
        row_index = self.table.currentRow()

        if 0 <= row_index < len(self.rows):
            return self.rows[row_index]

        return None

    @staticmethod
    def normalize_url(url: str) -> str:
        url = url.strip()

        if not url:
            return ""

        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        return url

    def save_group(self) -> None:
        name = self.name_input.text().strip()
        url = self.normalize_url(self.url_input.text())

        if not name:
            QMessageBox.warning(
                self,
                "缺少社團名稱",
                "請輸入社團名稱。",
            )
            return

        if not url:
            QMessageBox.warning(
                self,
                "缺少社團網址",
                "請輸入 Facebook 社團網址。",
            )
            return

        if "facebook.com" not in url.lower():
            QMessageBox.warning(
                self,
                "網址格式不正確",
                "請輸入 Facebook 社團網址。",
            )
            return

        try:
            self.db.save_facebook_group(name, url)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "儲存失敗",
                str(exc),
            )
            return

        self.name_input.clear()
        self.url_input.clear()
        self.refresh()

        QMessageBox.information(
            self,
            "儲存完成",
            f"已儲存社團：{name}",
        )

    def load_selected(self) -> None:
        row = self.selected()

        if not row:
            return

        self.name_input.setText(
            str(row.get("name", "") or "")
        )
        self.url_input.setText(
            str(row.get("url", "") or "")
        )

        self.status_label.setText(
            "已載入社團資料；修改後按「新增社團」即可更新。"
        )

    def toggle_selected(self) -> None:
        row = self.selected()

        if not row:
            QMessageBox.information(
                self,
                "尚未選擇社團",
                "請先點選一筆社團。",
            )
            return

        group_id = int(row["id"])
        current_enabled = int(row.get("enabled", 1) or 0)
        new_enabled = not bool(current_enabled)

        self.db.set_group_enabled(
            group_id,
            new_enabled,
        )

        self.refresh()

        QMessageBox.information(
            self,
            "狀態已更新",
            "社團已啟用。"
            if new_enabled
            else "社團已停用。",
        )

    def delete_selected(self) -> None:
        row = self.selected()

        if not row:
            QMessageBox.information(
                self,
                "尚未選擇社團",
                "請先點選一筆社團。",
            )
            return

        name = str(row.get("name", "這個社團"))

        answer = QMessageBox.question(
            self,
            "確認刪除",
            f"確定要刪除「{name}」嗎？",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        self.db.delete_facebook_group(
            int(row["id"])
        )

        self.refresh()

        QMessageBox.information(
            self,
            "刪除完成",
            f"已刪除「{name}」。",
        )