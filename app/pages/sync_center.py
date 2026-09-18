from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.database import Database, DuplicateSyncSourceError
from app.services.sync_runner import SyncRunner
from app.widgets.common import MetricCard, SectionTitle
from app.widgets.universal_import_dialog import UniversalImportDialog

SOURCE_TYPE_LABELS = {
    "yungching_store": "永慶／台慶店頭整店同步",
}

STATUS_LABELS = {
    "running": "同步中",
    "success": "成功",
    "partial": "部分成功",
    "failed": "失敗",
    "cancelled": "已取消",
}


class SyncSourceDialog(QDialog):
    """新增／編輯同步來源。"""

    def __init__(self, source: dict | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("編輯同步來源" if source else "新增同步來源")
        self.resize(520, 260)

        root = QVBoxLayout(self)
        form = QFormLayout()

        self.name_input = QLineEdit(str((source or {}).get("name", "")))
        self.name_input.setPlaceholderText("例如：龍潭永慶店頭")
        form.addRow("來源名稱", self.name_input)

        self.type_input = QComboBox()
        for key, label in SOURCE_TYPE_LABELS.items():
            self.type_input.addItem(label, key)
        current_type = (source or {}).get("source_type", "yungching_store")
        index = self.type_input.findData(current_type)
        self.type_input.setCurrentIndex(index if index >= 0 else 0)
        form.addRow("來源類型", self.type_input)

        self.url_input = QLineEdit(str((source or {}).get("url", "")))
        self.url_input.setPlaceholderText("https://shop.yungching.com.tw/.../list/...")
        form.addRow("店頭列表網址", self.url_input)

        self.auto_sync_checkbox = QCheckBox("啟用自動同步（時間排程於之後版本開放）")
        self.auto_sync_checkbox.setChecked(bool((source or {}).get("auto_sync_enabled", 0)))
        form.addRow("", self.auto_sync_checkbox)

        root.addLayout(form)

        button_row = QHBoxLayout()
        cancel_btn = QPushButton("取消")
        cancel_btn.setObjectName("SecondaryButton")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("儲存")
        save_btn.setObjectName("PrimaryButton")
        save_btn.clicked.connect(self._on_save)
        button_row.addStretch()
        button_row.addWidget(cancel_btn)
        button_row.addWidget(save_btn)
        root.addLayout(button_row)

        self.result_data: dict | None = None

    def _on_save(self) -> None:
        name = self.name_input.text().strip()
        url = self.url_input.text().strip()
        if not name:
            QMessageBox.warning(self, "缺少名稱", "請輸入來源名稱。")
            return
        if not url.startswith(("http://", "https://")):
            QMessageBox.warning(self, "網址格式不正確", "請輸入以 http:// 或 https:// 開頭的網址。")
            return
        self.result_data = {
            "name": name,
            "source_type": self.type_input.currentData(),
            "url": url,
            "auto_sync_enabled": self.auto_sync_checkbox.isChecked(),
            "enabled": True,
        }
        self.accept()


class SyncCenterPage(QWidget):
    def __init__(
        self,
        db: Database,
        go_dashboard: Callable[[], None],
        on_synced: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self.db = db
        self.go_dashboard = go_dashboard
        self.on_synced = on_synced
        self.sources: list[dict] = []
        self.runner: SyncRunner | None = None
        self.active_source_id: int | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 24)
        root.setSpacing(14)

        title_row = QHBoxLayout()
        back_btn = QPushButton("← 返回 Dashboard")
        back_btn.setObjectName("SecondaryButton")
        back_btn.clicked.connect(lambda _=False: self.go_dashboard())
        title_row.addWidget(back_btn)
        title_row.addWidget(
            SectionTitle("同步中心", "管理整店同步來源、單一物件匯入與同步歷史。"),
            1,
        )
        root.addLayout(title_row)

        cards_row = QHBoxLayout()
        self.card_last_sync = MetricCard("最後同步", "尚未同步")
        self.card_new = MetricCard("今日新增", "0")
        self.card_price = MetricCard("今日價格異動", "0")
        self.card_offline = MetricCard("今日下架", "0")
        self.card_failed = MetricCard("今日失敗次數", "0")
        for card in (
            self.card_last_sync,
            self.card_new,
            self.card_price,
            self.card_offline,
            self.card_failed,
        ):
            cards_row.addWidget(card, 1)
        root.addLayout(cards_row)

        toolbar = QHBoxLayout()
        add_btn = QPushButton("＋新增來源")
        add_btn.setObjectName("PrimaryButton")
        add_btn.clicked.connect(self.add_source)

        self.sync_now_btn = QPushButton("立即同步")
        self.sync_now_btn.setObjectName("PrimaryButton")
        self.sync_now_btn.clicked.connect(self.sync_selected_source)

        self.cancel_btn = QPushButton("取消同步")
        self.cancel_btn.setObjectName("SecondaryButton")
        self.cancel_btn.clicked.connect(self.cancel_sync)
        self.cancel_btn.setEnabled(False)

        edit_btn = QPushButton("編輯")
        edit_btn.setObjectName("SecondaryButton")
        edit_btn.clicked.connect(self.edit_source)

        self.toggle_btn = QPushButton("停用／啟用")
        self.toggle_btn.setObjectName("SecondaryButton")
        self.toggle_btn.clicked.connect(self.toggle_source)

        delete_btn = QPushButton("刪除")
        delete_btn.setObjectName("SecondaryButton")
        delete_btn.clicked.connect(self.delete_source)

        import_btn = QPushButton("＋ 匯入單一物件網址")
        import_btn.setObjectName("SecondaryButton")
        import_btn.clicked.connect(self.open_universal_import)

        toolbar.addWidget(add_btn)
        toolbar.addWidget(self.sync_now_btn)
        toolbar.addWidget(self.cancel_btn)
        toolbar.addWidget(edit_btn)
        toolbar.addWidget(self.toggle_btn)
        toolbar.addWidget(delete_btn)
        toolbar.addStretch()
        toolbar.addWidget(import_btn)
        root.addLayout(toolbar)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setVisible(False)
        root.addWidget(self.progress_bar)

        self.status_label = QLabel("準備完成")
        self.status_label.setObjectName("MutedLabel")
        root.addWidget(self.status_label)

        splitter = QSplitter(Qt.Orientation.Vertical)

        self.source_table = QTableWidget(0, 7)
        self.source_table.setHorizontalHeaderLabels(
            ["名稱", "網址", "類型", "啟用", "自動同步", "最後同步", "狀態"]
        )
        self.source_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.source_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.source_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.source_table.horizontalHeader().setStretchLastSection(True)
        self.source_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.source_table.verticalHeader().setVisible(False)
        splitter.addWidget(self.source_table)

        history_box = QWidget()
        history_layout = QVBoxLayout(history_box)
        history_layout.setContentsMargins(0, 8, 0, 0)
        history_layout.setSpacing(6)
        history_layout.addWidget(SectionTitle("同步歷史", "最近 50 筆同步紀錄"))

        self.history_table = QTableWidget(0, 9)
        self.history_table.setHorizontalHeaderLabels(
            ["開始時間", "來源", "狀態", "找到", "新增", "更新", "下架", "失敗頁數", "訊息"]
        )
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.horizontalHeader().setStretchLastSection(True)
        self.history_table.verticalHeader().setVisible(False)
        history_layout.addWidget(self.history_table)

        splitter.addWidget(history_box)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        self.refresh()

    # ------------------------------------------------------------------
    # 資料刷新
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        self._refresh_summary()
        self._refresh_sources()
        self._refresh_history()

    def _refresh_summary(self) -> None:
        summary = self.db.sync_dashboard_summary()
        last_sync = summary.get("last_sync_at") or "尚未同步"
        self.card_last_sync.set_value(last_sync)
        self.card_new.set_value(summary.get("today_new", 0))
        self.card_price.set_value(summary.get("today_price_changed", 0))
        self.card_offline.set_value(summary.get("today_offline", 0))
        self.card_failed.set_value(summary.get("today_failed", 0))

    def _refresh_sources(self) -> None:
        selected_id = self.selected_source_id()
        self.sources = self.db.list_sync_sources()
        self.source_table.setRowCount(len(self.sources))
        selected_row = -1
        for row_index, source in enumerate(self.sources):
            values = [
                source.get("name", ""),
                source.get("url", ""),
                SOURCE_TYPE_LABELS.get(source.get("source_type", ""), source.get("source_type", "")),
                "是" if int(source.get("enabled", 0) or 0) else "否",
                "是" if int(source.get("auto_sync_enabled", 0) or 0) else "否",
                source.get("last_sync_at") or "尚未同步",
                "執行中" if source.get("id") == self.active_source_id else "待命",
            ]
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column_index in (2, 3, 4, 6):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.source_table.setItem(row_index, column_index, item)
            if source.get("id") == selected_id:
                selected_row = row_index
        self.source_table.resizeColumnsToContents()
        self.source_table.setColumnWidth(0, 180)
        if selected_row >= 0:
            self.source_table.selectRow(selected_row)
        elif self.sources:
            self.source_table.selectRow(0)

    def _refresh_history(self) -> None:
        runs = self.db.list_sync_runs(limit=50)
        self.history_table.setRowCount(len(runs))
        for row_index, run in enumerate(runs):
            values = [
                run.get("started_at", ""),
                run.get("source_name", ""),
                STATUS_LABELS.get(run.get("status", ""), run.get("status", "")),
                run.get("found_count", 0),
                run.get("new_count", 0),
                run.get("updated_count", 0),
                run.get("offline_count", 0),
                run.get("failed_count", 0),
                run.get("error_message", ""),
            ]
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column_index in (2, 3, 4, 5, 6, 7):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.history_table.setItem(row_index, column_index, item)
        self.history_table.resizeColumnsToContents()

    def selected_source(self) -> dict | None:
        row_index = self.source_table.currentRow()
        return self.sources[row_index] if 0 <= row_index < len(self.sources) else None

    def selected_source_id(self) -> int | None:
        source = self.selected_source()
        return int(source["id"]) if source else None

    # ------------------------------------------------------------------
    # 來源管理
    # ------------------------------------------------------------------

    def add_source(self) -> None:
        dialog = SyncSourceDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.result_data:
            return

        try:
            self.db.save_sync_source(dialog.result_data)
        except DuplicateSyncSourceError as exc:
            confirm = QMessageBox.question(
                self,
                "此同步來源已存在",
                f"這個網址已經有一個來源「{exc.existing_name}」了。\n\n"
                "要用剛剛輸入的名稱／設定更新它嗎？",
            )
            if confirm == QMessageBox.StandardButton.Yes:
                self.db.save_sync_source(dialog.result_data, source_id=exc.existing_id)
            else:
                return

        self.refresh()

    def edit_source(self) -> None:
        source = self.selected_source()
        if not source:
            QMessageBox.information(self, "尚未選擇來源", "請先在列表中選擇一個同步來源。")
            return
        dialog = SyncSourceDialog(source=source, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_data:
            self.db.save_sync_source(dialog.result_data, source_id=int(source["id"]))
            self.refresh()

    def toggle_source(self) -> None:
        source = self.selected_source()
        if not source:
            QMessageBox.information(self, "尚未選擇來源", "請先在列表中選擇一個同步來源。")
            return
        new_enabled = not bool(int(source.get("enabled", 0) or 0))
        self.db.set_sync_source_enabled(int(source["id"]), new_enabled)
        self.refresh()

    def delete_source(self) -> None:
        source = self.selected_source()
        if not source:
            QMessageBox.information(self, "尚未選擇來源", "請先在列表中選擇一個同步來源。")
            return
        confirm = QMessageBox.question(
            self,
            "確認刪除來源",
            f"確定要刪除同步來源「{source.get('name', '')}」嗎？\n\n"
            "這只會刪除同步來源設定，不會刪除已同步的物件資料。",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.db.delete_sync_source(int(source["id"]))
        self.refresh()

    def open_universal_import(self) -> None:
        dialog = UniversalImportDialog(db=self.db, on_imported=self._on_external_change, parent=self)
        dialog.exec()

    # ------------------------------------------------------------------
    # 同步執行
    # ------------------------------------------------------------------

    def sync_selected_source(self) -> None:
        if self.runner is not None:
            QMessageBox.information(self, "同步進行中", "目前已有同步正在執行，請稍候。")
            return
        source = self.selected_source()
        if not source:
            QMessageBox.information(self, "尚未選擇來源", "請先新增或選擇一個同步來源。")
            return
        if not int(source.get("enabled", 0) or 0):
            QMessageBox.warning(self, "來源已停用", "請先啟用這個同步來源再執行同步。")
            return

        self.active_source_id = int(source["id"])
        self.sync_now_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.status_label.setText(f"正在同步「{source.get('name', '')}」…")
        self._refresh_sources()

        self.runner = SyncRunner(self.db, source)
        self.runner.progress.connect(self._on_progress)
        self.runner.finished.connect(self._on_finished)
        self.runner.failed.connect(self._on_failed)
        self.runner.start()

    def cancel_sync(self) -> None:
        if self.runner is not None:
            self.runner.cancel()
            self.status_label.setText("正在取消同步，請稍候目前批次完成…")
            self.cancel_btn.setEnabled(False)

    def _on_progress(self, payload: dict) -> None:
        total = int(payload.get("total", 0) or 0)
        current = int(payload.get("current", 0) or 0)
        message = str(payload.get("message", ""))
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(current)
        else:
            self.progress_bar.setRange(0, 0)
        self.status_label.setText(message or "同步中…")

    def _on_finished(self, payload: dict) -> None:
        counts = payload.get("counts", {})
        status = payload.get("status", "success")
        summary = (
            f"同步完成（{STATUS_LABELS.get(status, status)}）："
            f"找到 {payload.get('found', 0)} 筆，"
            f"新增 {counts.get('new', 0)}，更新 {counts.get('updated', 0)}，"
            f"價格異動 {counts.get('price_changed', 0)}，"
            f"下架 {counts.get('offline', 0)}"
        )
        self.status_label.setText(summary)
        self._finish_sync_ui()
        QMessageBox.information(self, "同步完成", summary)

    def _on_failed(self, message: str) -> None:
        self.status_label.setText(f"同步失敗：{message}")
        self._finish_sync_ui()
        QMessageBox.critical(self, "同步失敗", f"這次同步發生錯誤，其他來源與現有資料不受影響。\n\n錯誤內容：{message}")

    def _finish_sync_ui(self) -> None:
        if self.runner is not None:
            self.runner.wait_and_cleanup()
        self.runner = None
        self.active_source_id = None
        self.sync_now_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.refresh()
        self._on_external_change()

    def _on_external_change(self) -> None:
        self.refresh()
        if callable(self.on_synced):
            self.on_synced()
