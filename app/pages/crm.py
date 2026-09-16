from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from app.services.database import Database
from app.widgets.common import SectionTitle


class ContactDialog(QDialog):
    def __init__(self, parent=None, data: dict | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("聯絡人資料")
        self.resize(520, 520)
        data = data or {}
        form = QFormLayout(self)
        self.name = QLineEdit(str(data.get("name", "")))
        self.role = QComboBox(); self.role.addItems(["買方", "屋主", "合作夥伴", "其他"])
        self.role.setCurrentText(str(data.get("role", "買方")))
        self.phone = QLineEdit(str(data.get("phone", "")))
        self.budget = QLineEdit(str(data.get("budget", "")))
        self.status = QComboBox(); self.status.addItems(["追蹤中", "待聯絡", "已帶看", "談判中", "已成交", "暫停"])
        self.status.setCurrentText(str(data.get("status", "追蹤中")))
        self.followup = QLineEdit(str(data.get("next_followup", "")))
        self.followup.setPlaceholderText("例如：2026-07-30 15:00")
        self.note = QTextEdit(str(data.get("note", "")))
        for label, widget in [
            ("姓名*", self.name), ("身分", self.role), ("電話", self.phone),
            ("預算／期望價格", self.budget), ("狀態", self.status),
            ("下次追蹤", self.followup), ("備註", self.note),
        ]:
            form.addRow(label, widget)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> dict:
        return {
            "name": self.name.text(), "role": self.role.currentText(),
            "phone": self.phone.text(), "budget": self.budget.text(),
            "status": self.status.currentText(), "next_followup": self.followup.text(),
            "note": self.note.toPlainText(),
        }


class CRMPage(QWidget):
    def __init__(self, db: Database) -> None:
        super().__init__(); self.db = db; self.rows: list[dict] = []
        root = QVBoxLayout(self); root.setContentsMargins(24, 22, 24, 24); root.setSpacing(14)
        root.addWidget(SectionTitle("CRM 客戶管理", "集中管理買方、屋主、追蹤時間與談判狀態。"))
        tools = QHBoxLayout()
        self.search = QLineEdit(); self.search.setPlaceholderText("搜尋姓名、電話、狀態或備註…")
        self.search.textChanged.connect(self.refresh)
        add_btn = QPushButton("＋ 新增聯絡人"); add_btn.setObjectName("PrimaryButton"); add_btn.clicked.connect(self.add_contact)
        edit_btn = QPushButton("編輯"); edit_btn.setObjectName("SecondaryButton"); edit_btn.clicked.connect(self.edit_contact)
        delete_btn = QPushButton("刪除"); delete_btn.setObjectName("SecondaryButton"); delete_btn.clicked.connect(self.delete_contact)
        tools.addWidget(self.search, 1); tools.addWidget(add_btn); tools.addWidget(edit_btn); tools.addWidget(delete_btn)
        root.addLayout(tools)
        self.status = QLabel(); self.status.setObjectName("MutedLabel"); root.addWidget(self.status)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["ID", "姓名", "身分", "電話", "預算／價格", "狀態", "下次追蹤", "備註"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self.edit_contact)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1); self.refresh()

    def selected(self) -> dict | None:
        i = self.table.currentRow(); return self.rows[i] if 0 <= i < len(self.rows) else None

    def refresh(self, *_args) -> None:
        self.rows = self.db.list_contacts(self.search.text().strip() if hasattr(self, "search") else "")
        self.table.setRowCount(len(self.rows))
        for i, row in enumerate(self.rows):
            vals = [row.get(k, "") for k in ["id", "name", "role", "phone", "budget", "status", "next_followup", "note"]]
            for j, value in enumerate(vals): self.table.setItem(i, j, QTableWidgetItem(str(value or "")))
        self.table.resizeColumnsToContents(); self.table.setColumnWidth(7, 300)
        self.status.setText(f"目前共有 {len(self.rows)} 位聯絡人")

    def add_contact(self) -> None:
        dialog = ContactDialog(self)
        if dialog.exec():
            try: self.db.save_contact(dialog.values()); self.refresh()
            except ValueError as exc: QMessageBox.warning(self, "無法儲存", str(exc))

    def edit_contact(self, *_args) -> None:
        row = self.selected()
        if not row: QMessageBox.information(self, "尚未選擇", "請先選擇一位聯絡人。"); return
        dialog = ContactDialog(self, row)
        if dialog.exec():
            try: self.db.save_contact(dialog.values(), int(row["id"])); self.refresh()
            except ValueError as exc: QMessageBox.warning(self, "無法儲存", str(exc))

    def delete_contact(self) -> None:
        row = self.selected()
        if not row: QMessageBox.information(self, "尚未選擇", "請先選擇一位聯絡人。"); return
        answer = QMessageBox.question(self, "確認刪除", f"確定刪除「{row.get('name', '')}」？")
        if answer == QMessageBox.StandardButton.Yes:
            self.db.delete_contact(int(row["id"])); self.refresh()
