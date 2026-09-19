from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.database import Database, DuplicateSyncSourceError
from app.services.sync_runner import SyncRunner
from app.widgets.common import MetricCard, SectionTitle, show_toast
from app.widgets.universal_import_dialog import UniversalImportDialog

SOURCE_TYPE_LABELS = {
    "yungching_store": "永慶／台慶店頭整店同步",
}

RUN_STATUS_LABELS = {
    "running": "同步中",
    "success": "成功",
    "partial": "部分成功",
    "suspicious": "結果可疑",
    "failed": "失敗",
    "cancelled": "已取消",
}

LAST_STATUS_LABELS = {
    "": "尚未同步",
    "success": "✓ 成功",
    "partial": "~ 部分成功",
    "suspicious": "⚠ 結果可疑",
    "failed": "✕ 失敗",
    "needs_review": "⚠ 需要確認",
    "cancelled": "已取消",
}

CHANGE_TYPE_LABELS = {
    "created": "新增物件",
    "price_changed": "價格異動",
    "content_changed": "內容異動",
    "offline": "已下架",
    "online_again": "重新上架",
}


class SyncIntervalSelector(QWidget):
    """自動同步頻率：30分/1/3/6/12/24小時或自訂分鐘數。預設每 6 小時，
    但不是寫死──實際預設值存在 DB 的 sync_interval_minutes 欄位。
    """

    PRESETS = (
        (30, "每 30 分鐘"),
        (60, "每 1 小時"),
        (180, "每 3 小時"),
        (360, "每 6 小時"),
        (720, "每 12 小時"),
        (1440, "每 24 小時"),
    )

    def __init__(self, current_minutes: int | None = None) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.group = QButtonGroup(self)
        self.radios: list[tuple[QRadioButton, int]] = []

        preset_row = QHBoxLayout()
        for minutes, label in self.PRESETS:
            radio = QRadioButton(label)
            self.group.addButton(radio)
            self.radios.append((radio, minutes))
            preset_row.addWidget(radio)
        layout.addLayout(preset_row)

        custom_row = QHBoxLayout()
        self.custom_radio = QRadioButton("自訂")
        self.group.addButton(self.custom_radio)
        self.custom_minutes = QSpinBox()
        self.custom_minutes.setRange(5, 10080)
        self.custom_minutes.setSuffix(" 分鐘")
        custom_row.addWidget(self.custom_radio)
        custom_row.addWidget(self.custom_minutes)
        custom_row.addStretch()
        layout.addLayout(custom_row)

        default_minutes = current_minutes if current_minutes is not None else 360
        matched = next((r for r, m in self.radios if m == default_minutes), None)
        if matched is not None:
            matched.setChecked(True)
            self.custom_minutes.setValue(default_minutes)
        else:
            self.custom_radio.setChecked(True)
            self.custom_minutes.setValue(default_minutes)

    def value(self) -> int:
        for radio, minutes in self.radios:
            if radio.isChecked():
                return minutes
        return self.custom_minutes.value()


def format_interval(minutes: int) -> str:
    for preset_minutes, label in SyncIntervalSelector.PRESETS:
        if preset_minutes == minutes:
            return label
    if minutes % 60 == 0:
        return f"每 {minutes // 60} 小時"
    return f"每 {minutes} 分鐘"


class SyncSourceDialog(QDialog):
    """新增／編輯同步來源。"""

    def __init__(self, db: Database, source: dict | None = None, parent=None) -> None:
        super().__init__(parent)
        self.db = db
        self.is_new = source is None
        self.setWindowTitle("編輯同步來源" if source else "新增同步來源")
        self.resize(560, 420)

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

        root.addLayout(form)

        self.auto_sync_checkbox = QCheckBox("☑ 開啟自動同步")
        self.auto_sync_checkbox.setChecked(
            bool(int((source or {}).get("auto_sync_enabled", 0) or 0))
        )
        root.addWidget(self.auto_sync_checkbox)

        root.addWidget(QLabel("同步頻率"))
        current_interval = (source or {}).get("sync_interval_minutes")
        self.interval_selector = SyncIntervalSelector(
            int(current_interval) if current_interval else None
        )
        root.addWidget(self.interval_selector)

        if self.is_new:
            self.sync_now_checkbox = QCheckBox("☑ 建立後立即同步")
            self.sync_now_checkbox.setChecked(True)
            root.addWidget(self.sync_now_checkbox)
        else:
            self.sync_now_checkbox = None

        root.addStretch()

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
        self.sync_now = False

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
            "sync_interval_minutes": self.interval_selector.value(),
            "enabled": True,
        }
        self.sync_now = bool(self.sync_now_checkbox and self.sync_now_checkbox.isChecked())
        self.accept()


class SourceCard(QFrame):
    """一個同步來源的卡片：名稱/網址/物件數/上次同步/下次同步/頻率/
    上次結果，加上 [立即同步][設定][停用] 三個動作，不需要使用者理解
    database table。
    """

    def __init__(
        self,
        source: dict,
        property_count: int,
        on_sync_now: Callable[[dict], None],
        on_settings: Callable[[dict], None],
        on_toggle: Callable[[dict], None],
        on_delete: Callable[[dict], None],
        is_syncing: bool,
    ) -> None:
        super().__init__()
        self.setObjectName("Card")
        self.source = source

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(6)

        header_row = QHBoxLayout()
        name_label = QLabel(str(source.get("name", "")))
        name_label.setObjectName("StepTitle")
        header_row.addWidget(name_label)

        enabled = bool(int(source.get("enabled", 0) or 0))
        auto_sync = bool(int(source.get("auto_sync_enabled", 0) or 0))
        if not enabled:
            status_text, status_kind = "● 已停用", "neutral"
        elif is_syncing:
            status_text, status_kind = "⏳ 同步中", "info"
        elif auto_sync:
            status_text, status_kind = "● 自動同步開啟", "success"
        else:
            status_text, status_kind = "○ 自動同步關閉", "neutral"
        status_label = QLabel(status_text)
        status_label.setObjectName("StatusBadge")
        status_label.setProperty("kind", status_kind)
        header_row.addWidget(status_label)
        header_row.addStretch()
        layout.addLayout(header_row)

        url_label = QLabel(str(source.get("url", "")))
        url_label.setObjectName("Muted")
        url_label.setWordWrap(True)
        layout.addWidget(url_label)

        info_row = QHBoxLayout()
        info_row.setSpacing(24)

        def _info(title: str, value: str) -> QVBoxLayout:
            box = QVBoxLayout()
            box.setSpacing(1)
            t = QLabel(title)
            t.setObjectName("Muted")
            v = QLabel(value)
            box.addWidget(t)
            box.addWidget(v)
            return box

        info_row.addLayout(_info("物件", str(property_count)))
        info_row.addLayout(_info("上次同步", str(source.get("last_sync_at") or "尚未同步")))
        next_sync_text = (
            str(source.get("next_sync_at")) if auto_sync and source.get("next_sync_at") else
            ("待排程" if auto_sync else "—")
        )
        info_row.addLayout(_info("下次同步", next_sync_text))
        info_row.addLayout(_info("頻率", format_interval(int(source.get("sync_interval_minutes") or 360))))
        last_status = str(source.get("last_status") or "")
        result_text = LAST_STATUS_LABELS.get(last_status, last_status)
        info_row.addLayout(_info("上次結果", result_text))
        info_row.addStretch()
        layout.addLayout(info_row)

        if last_status in ("failed", "needs_review") and source.get("last_error"):
            error_label = QLabel(f"⚠ {source.get('last_error')}")
            error_label.setObjectName("WarningText")
            error_label.setWordWrap(True)
            layout.addWidget(error_label)

        action_row = QHBoxLayout()
        sync_btn = QPushButton("同步中…" if is_syncing else "立即同步")
        sync_btn.setObjectName("PrimaryButton")
        sync_btn.setEnabled(enabled and not is_syncing)
        sync_btn.clicked.connect(lambda: on_sync_now(source))

        settings_btn = QPushButton("設定")
        settings_btn.setObjectName("SecondaryButton")
        settings_btn.clicked.connect(lambda: on_settings(source))

        toggle_btn = QPushButton("停用" if enabled else "啟用")
        toggle_btn.setObjectName("SecondaryButton")
        toggle_btn.clicked.connect(lambda: on_toggle(source))

        delete_btn = QPushButton("刪除")
        delete_btn.setObjectName("SecondaryButton")
        delete_btn.clicked.connect(lambda: on_delete(source))

        action_row.addWidget(sync_btn)
        action_row.addWidget(settings_btn)
        action_row.addWidget(toggle_btn)
        action_row.addWidget(delete_btn)
        action_row.addStretch()
        layout.addLayout(action_row)


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

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)

        root = QVBoxLayout(content)
        root.setContentsMargins(24, 22, 24, 24)
        root.setSpacing(14)

        title_row = QHBoxLayout()
        back_btn = QPushButton("← 返回 Dashboard")
        back_btn.setObjectName("SecondaryButton")
        back_btn.clicked.connect(lambda _=False: self.go_dashboard())
        title_row.addWidget(back_btn)
        title_row.addWidget(
            SectionTitle("同步中心", "Auto Sync Control Center — 管理自動同步來源、單一物件匯入與同步歷史。"),
            1,
        )
        root.addLayout(title_row)

        cards_row = QHBoxLayout()
        self.card_auto_sources = MetricCard("自動同步來源", "0")
        self.card_today_runs = MetricCard("今日同步次數", "0")
        self.card_new = MetricCard("今日新增物件", "0")
        self.card_changed = MetricCard("今日異動", "0")
        self.card_failed = MetricCard("今日失敗", "0")
        for card in (
            self.card_auto_sources,
            self.card_today_runs,
            self.card_new,
            self.card_changed,
            self.card_failed,
        ):
            cards_row.addWidget(card, 1)
        root.addLayout(cards_row)

        toolbar = QHBoxLayout()
        add_btn = QPushButton("＋新增來源")
        add_btn.setObjectName("PrimaryButton")
        add_btn.clicked.connect(self.add_source)

        self.cancel_btn = QPushButton("取消同步")
        self.cancel_btn.setObjectName("SecondaryButton")
        self.cancel_btn.clicked.connect(self.cancel_sync)
        self.cancel_btn.setEnabled(False)

        import_btn = QPushButton("＋ 匯入單一物件網址")
        import_btn.setObjectName("SecondaryButton")
        import_btn.clicked.connect(self.open_universal_import)

        toolbar.addWidget(add_btn)
        toolbar.addWidget(self.cancel_btn)
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

        root.addWidget(QLabel("同步來源"))
        self.sources_container = QVBoxLayout()
        self.sources_container.setSpacing(10)
        root.addLayout(self.sources_container)

        root.addWidget(SectionTitle("最近異動", "新增物件、價格異動、下架與重新上架，最近 20 筆。"))
        self.changes_table = QTableWidget(0, 3)
        self.changes_table.setHorizontalHeaderLabels(["時間", "物件", "異動內容"])
        self.changes_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.changes_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.changes_table.horizontalHeader().setStretchLastSection(True)
        self.changes_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.changes_table.verticalHeader().setVisible(False)
        self.changes_table.setMaximumHeight(220)
        root.addWidget(self.changes_table)

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
        self.history_table.setMaximumHeight(260)
        history_layout.addWidget(self.history_table)
        root.addWidget(history_box)

        self.refresh()

    # ------------------------------------------------------------------
    # 資料刷新
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        self._refresh_summary()
        self._refresh_sources()
        self._refresh_changes()
        self._refresh_history()

    def _refresh_summary(self) -> None:
        summary = self.db.sync_dashboard_summary()
        self.card_auto_sources.set_value(summary.get("auto_sync_sources", 0))
        self.card_today_runs.set_value(summary.get("today_sync_runs", 0))
        self.card_new.set_value(summary.get("today_new", 0))
        self.card_changed.set_value(summary.get("today_changed", 0))
        self.card_failed.set_value(summary.get("today_failed", 0))

    def _clear_source_cards(self) -> None:
        while self.sources_container.count():
            item = self.sources_container.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _refresh_sources(self) -> None:
        self.sources = self.db.list_sync_sources()
        self._clear_source_cards()

        if not self.sources:
            empty_label = QLabel("尚未建立同步來源。按「＋新增來源」開始第一個整店自動同步。")
            empty_label.setObjectName("MutedLabel")
            self.sources_container.addWidget(empty_label)
            return

        for source in self.sources:
            source_id = int(source["id"])
            property_count = self.db.count_active_properties_for_source(source_id)
            is_syncing = (
                source.get("sync_status") == "syncing" or source_id == self.active_source_id
            )
            card = SourceCard(
                source, property_count,
                on_sync_now=self.sync_source,
                on_settings=self.edit_source,
                on_toggle=self.toggle_source,
                on_delete=self.delete_source,
                is_syncing=is_syncing,
            )
            self.sources_container.addWidget(card)

    def _refresh_changes(self) -> None:
        changes = self.db.list_property_changes(limit=20)
        self.changes_table.setRowCount(len(changes))
        for row_index, change in enumerate(changes):
            change_type = str(change.get("change_type", ""))
            label = CHANGE_TYPE_LABELS.get(change_type, change_type)
            if change_type == "price_changed":
                detail = f"{label}：{change.get('old_value', '')} → {change.get('new_value', '')}"
            else:
                detail = label
            title = str(change.get("property_title") or "（物件已刪除）")
            values = [change.get("detected_at", ""), title, detail]
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                self.changes_table.setItem(row_index, column_index, item)
        self.changes_table.resizeColumnsToContents()

    def _refresh_history(self) -> None:
        runs = self.db.list_sync_runs(limit=50)
        self.history_table.setRowCount(len(runs))
        for row_index, run in enumerate(runs):
            values = [
                run.get("started_at", ""),
                run.get("source_name", ""),
                RUN_STATUS_LABELS.get(run.get("status", ""), run.get("status", "")),
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

    # ------------------------------------------------------------------
    # 來源管理
    # ------------------------------------------------------------------

    def add_source(self) -> None:
        dialog = SyncSourceDialog(self.db, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.result_data:
            return

        try:
            new_id = self.db.save_sync_source(dialog.result_data)
        except DuplicateSyncSourceError as exc:
            confirm = QMessageBox.question(
                self,
                "此同步來源已存在",
                f"這個網址已經有一個來源「{exc.existing_name}」了。\n\n"
                "要用剛剛輸入的名稱／設定更新它嗎？",
            )
            if confirm == QMessageBox.StandardButton.Yes:
                new_id = exc.existing_id
                self.db.save_sync_source(dialog.result_data, source_id=exc.existing_id)
            else:
                return

        self.refresh()
        show_toast(self, "✓ 已新增同步來源", kind="success")
        if dialog.sync_now:
            source = self.db.get_sync_source(new_id)
            if source:
                self.sync_source(source)

    def edit_source(self, source: dict) -> None:
        dialog = SyncSourceDialog(self.db, source=source, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_data:
            self.db.save_sync_source(dialog.result_data, source_id=int(source["id"]))
            self.refresh()
            show_toast(self, "✓ 已更新來源設定", kind="success")

    def toggle_source(self, source: dict) -> None:
        new_enabled = not bool(int(source.get("enabled", 0) or 0))
        self.db.set_sync_source_enabled(int(source["id"]), new_enabled)
        self.refresh()
        show_toast(self, "已啟用來源" if new_enabled else "已停用來源", kind="info")

    def delete_source(self, source: dict) -> None:
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
        show_toast(self, "已刪除來源", kind="info")

    def open_universal_import(self) -> None:
        dialog = UniversalImportDialog(db=self.db, on_imported=self._on_external_change, parent=self)
        dialog.exec()

    # ------------------------------------------------------------------
    # 同步執行
    # ------------------------------------------------------------------

    def sync_source(self, source: dict) -> None:
        if self.runner is not None:
            QMessageBox.information(self, "同步進行中", "目前已有同步正在執行，請稍候。")
            return
        if not int(source.get("enabled", 0) or 0):
            QMessageBox.warning(self, "來源已停用", "請先啟用這個同步來源再執行同步。")
            return

        self.active_source_id = int(source["id"])
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
            f"同步完成（{RUN_STATUS_LABELS.get(status, status)}）："
            f"找到 {payload.get('found', 0)} 筆，"
            f"新增 {counts.get('new', 0)}，更新 {counts.get('updated', 0)}，"
            f"價格異動 {counts.get('price_changed', 0)}，"
            f"下架 {counts.get('offline', 0)}"
        )
        self.status_label.setText(summary)
        self._finish_sync_ui()
        show_toast(self, f"✓ {summary}", kind="success", duration_ms=4000)

    def _on_failed(self, message: str) -> None:
        self.status_label.setText(f"同步失敗：{message}")
        self._finish_sync_ui()
        QMessageBox.critical(self, "同步失敗", f"這次同步發生錯誤，其他來源與現有資料不受影響。\n\n錯誤內容：{message}")

    def _finish_sync_ui(self) -> None:
        if self.runner is not None:
            self.runner.wait_and_cleanup()
        self.runner = None
        self.active_source_id = None
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.refresh()
        self._on_external_change()

    def _on_external_change(self) -> None:
        self.refresh()
        if callable(self.on_synced):
            self.on_synced()
