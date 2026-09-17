from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.database import Database
from app.services.schedule_runner import SchedulePublishRunner
from app.widgets.common import MetricCard, SectionTitle
from app.widgets.schedule_dialog import NewScheduleDialog

STATUS_LABELS = {
    "draft": "草稿",
    "pending_review": "待檢核",
    "scheduled": "已排程",
    "publishing": "發布中",
    "published": "發布成功",
    "failed": "發布失敗",
    "cancelled": "已取消",
    "deleted": "已刪除",
}

FILTERS: list[tuple[str, list[str] | None, bool]] = [
    ("草稿", ["draft"], False),
    ("今日待檢核", ["pending_review"], True),
    ("今日已排程", ["scheduled"], True),
    ("發布中", ["publishing"], False),
    ("今日發布成功", ["published"], True),
    ("今日發布失敗", ["failed"], True),
    ("全部歷史", None, False),
]


class ScheduleCenterPage(QWidget):
    def __init__(
        self,
        db: Database,
        go_dashboard: Callable[[], None],
        on_published: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self.db = db
        self.go_dashboard = go_dashboard
        self.on_published = on_published
        self.rows: list[dict] = []
        self.runner: SchedulePublishRunner | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 24)
        root.setSpacing(14)

        title_row = QHBoxLayout()
        back_btn = QPushButton("← 返回 Dashboard")
        back_btn.setObjectName("SecondaryButton")
        back_btn.clicked.connect(lambda _=False: self.go_dashboard())
        title_row.addWidget(back_btn)
        title_row.addWidget(
            SectionTitle("排程發布中心", "建立、核准與追蹤 Facebook 排程發布。"),
            1,
        )
        root.addLayout(title_row)

        cards_row = QHBoxLayout()
        self.card_pending = MetricCard("今日待檢核", "0")
        self.card_scheduled = MetricCard("今日已排程", "0")
        self.card_publishing = MetricCard("發布中", "0")
        self.card_published = MetricCard("今日發布成功", "0")
        self.card_failed = MetricCard("今日發布失敗", "0")
        for card in (
            self.card_pending,
            self.card_scheduled,
            self.card_publishing,
            self.card_published,
            self.card_failed,
        ):
            cards_row.addWidget(card, 1)
        root.addLayout(cards_row)

        toolbar = QHBoxLayout()

        add_btn = QPushButton("＋新增排程")
        add_btn.setObjectName("PrimaryButton")
        add_btn.clicked.connect(self.add_schedule)

        self.filter_combo = QComboBox()
        for label, _statuses, _today in FILTERS:
            self.filter_combo.addItem(label)
        self.filter_combo.currentIndexChanged.connect(self.refresh)

        view_btn = QPushButton("查看內容")
        view_btn.setObjectName("SecondaryButton")
        view_btn.clicked.connect(self.view_selected)

        submit_draft_btn = QPushButton("送出待檢核")
        submit_draft_btn.setObjectName("SecondaryButton")
        submit_draft_btn.clicked.connect(self.submit_draft_selected)

        approve_btn = QPushButton("核准排程")
        approve_btn.setObjectName("SecondaryButton")
        approve_btn.clicked.connect(self.approve_selected)

        approve_all_btn = QPushButton("核准今日全部")
        approve_all_btn.setObjectName("SecondaryButton")
        approve_all_btn.clicked.connect(self.approve_all_today)

        reject_btn = QPushButton("退回修改")
        reject_btn.setObjectName("SecondaryButton")
        reject_btn.clicked.connect(self.reject_selected)

        self.publish_btn = QPushButton("立即發布")
        self.publish_btn.setObjectName("PrimaryButton")
        self.publish_btn.clicked.connect(self.publish_selected)

        cancel_btn = QPushButton("取消排程")
        cancel_btn.setObjectName("SecondaryButton")
        cancel_btn.clicked.connect(self.cancel_selected)

        delete_btn = QPushButton("刪除")
        delete_btn.setObjectName("SecondaryButton")
        delete_btn.clicked.connect(self.delete_selected)

        toolbar.addWidget(add_btn)
        toolbar.addWidget(QLabel("篩選："))
        toolbar.addWidget(self.filter_combo)
        toolbar.addWidget(view_btn)
        toolbar.addWidget(submit_draft_btn)
        toolbar.addWidget(approve_btn)
        toolbar.addWidget(approve_all_btn)
        toolbar.addWidget(reject_btn)
        toolbar.addWidget(self.publish_btn)
        toolbar.addWidget(cancel_btn)
        toolbar.addWidget(delete_btn)
        toolbar.addStretch()
        root.addLayout(toolbar)

        self.status_label = QLabel("準備完成")
        self.status_label.setObjectName("MutedLabel")
        root.addWidget(self.status_label)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["物件", "發布位置", "預定時間", "狀態", "核准時間", "發布時間", "失敗原因／備註", "重試次數"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(self.view_selected)
        root.addWidget(self.table, 1)

        self.refresh()

    # ------------------------------------------------------------------

    def refresh(self) -> None:
        self._refresh_summary()
        self._refresh_table()

    def _refresh_summary(self) -> None:
        counts = self.db.schedule_dashboard_counts()
        self.card_pending.set_value(counts.get("pending_review_today", 0))
        self.card_scheduled.set_value(counts.get("scheduled_today", 0))
        self.card_publishing.set_value(counts.get("publishing", 0))
        self.card_published.set_value(counts.get("published_today", 0))
        self.card_failed.set_value(counts.get("failed_today", 0))

    def _current_filter(self) -> tuple[list[str] | None, bool]:
        index = self.filter_combo.currentIndex()
        if index < 0 or index >= len(FILTERS):
            index = 0
        _label, statuses, only_today = FILTERS[index]
        return statuses, only_today

    def _refresh_table(self) -> None:
        selected_id = self.selected_id()
        statuses, only_today = self._current_filter()
        self.rows = self.db.list_schedules(statuses=statuses, only_today=only_today)

        self.table.setRowCount(len(self.rows))
        selected_row = -1
        for row_index, row in enumerate(self.rows):
            title = str(row.get("property_title") or "（物件已刪除）")
            values = [
                title,
                row.get("target_label", ""),
                row.get("scheduled_at", ""),
                STATUS_LABELS.get(row.get("status", ""), row.get("status", "")),
                row.get("approved_at", ""),
                row.get("published_at", ""),
                row.get("error_message", ""),
                row.get("retry_count", 0),
            ]
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                if column_index in (2, 3, 4, 5, 7):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row_index, column_index, item)
            if row.get("id") == selected_id:
                selected_row = row_index

        self.table.resizeColumnsToContents()
        if selected_row >= 0:
            self.table.selectRow(selected_row)
        self.status_label.setText(f"目前顯示 {len(self.rows)} 筆排程")

    def selected(self) -> dict | None:
        row_index = self.table.currentRow()
        return self.rows[row_index] if 0 <= row_index < len(self.rows) else None

    def selected_id(self) -> int | None:
        row = self.selected()
        return int(row["id"]) if row else None

    # ------------------------------------------------------------------

    def add_schedule(self) -> None:
        dialog = NewScheduleDialog(self.db, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def view_selected(self, *_args) -> None:
        row = self.selected()
        if not row:
            QMessageBox.information(self, "尚未選擇排程", "請先在列表中選擇一筆排程。")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("排程內容")
        dialog.resize(600, 500)
        layout = QVBoxLayout(dialog)

        info = (
            f"物件：{row.get('property_title', '')}\n"
            f"發布位置：{row.get('target_label', '')}\n"
            f"預定時間：{row.get('scheduled_at', '')}\n"
            f"狀態：{STATUS_LABELS.get(row.get('status', ''), row.get('status', ''))}\n"
            f"圖片：{len([p for p in str(row.get('images', '')).split(chr(10)) if p.strip()])} 張\n"
        )
        if row.get("error_message"):
            info += f"失敗原因：{row.get('error_message')}\n"

        info_label = QLabel(info)
        layout.addWidget(info_label)

        content_view = QPlainTextEdit(str(row.get("copy_text", "")))
        content_view.setReadOnly(True)
        layout.addWidget(content_view, 1)

        close_btn = QPushButton("關閉")
        close_btn.setObjectName("SecondaryButton")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)

        dialog.exec()

    def submit_draft_selected(self) -> None:
        row = self.selected()
        if not row:
            QMessageBox.information(self, "尚未選擇排程", "請先在列表中選擇一筆排程。")
            return
        if row.get("status") != "draft":
            QMessageBox.warning(self, "無法送出", "只有「草稿」狀態的排程可以送出待檢核。")
            return

        scheduled_at = str(row.get("scheduled_at") or "").strip()
        if not scheduled_at:
            from PySide6.QtCore import QDateTime

            scheduled_at = QDateTime.currentDateTime().addSecs(3 * 3600).toString(
                "yyyy-MM-dd HH:mm:00"
            )
            QMessageBox.information(
                self,
                "已自動設定發布時間",
                f"這筆草稿還沒有設定時間，已先設為 {scheduled_at}，"
                "核准前仍可以再調整。",
            )

        self.db.submit_draft(int(row["id"]), scheduled_at)
        self.refresh()
        self.status_label.setText(f"已送出待檢核：{row.get('property_title', '')} - {row.get('target_label', '')}")

    def approve_selected(self) -> None:
        row = self.selected()
        if not row:
            QMessageBox.information(self, "尚未選擇排程", "請先在列表中選擇一筆排程。")
            return
        if row.get("status") != "pending_review":
            QMessageBox.warning(self, "無法核准", "只有「待檢核」狀態的排程可以核准。")
            return
        self.db.approve_schedule(int(row["id"]))
        self.refresh()
        self.status_label.setText(f"已核准：{row.get('property_title', '')} - {row.get('target_label', '')}")

    def approve_all_today(self) -> None:
        confirm = QMessageBox.question(
            self, "核准今日全部待檢核", "確定要核准所有「今天」預定發布的待檢核排程嗎？"
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        count = self.db.approve_all_pending_today()
        self.refresh()
        self.status_label.setText(f"已核准今日 {count} 筆排程。")

    def reject_selected(self) -> None:
        row = self.selected()
        if not row:
            QMessageBox.information(self, "尚未選擇排程", "請先在列表中選擇一筆排程。")
            return
        if row.get("status") != "pending_review":
            QMessageBox.warning(self, "無法退回", "只有「待檢核」狀態的排程可以退回修改。")
            return
        self.db.reject_schedule(int(row["id"]))
        self.refresh()
        self.status_label.setText(f"已退回草稿：{row.get('property_title', '')}")

    def cancel_selected(self) -> None:
        row = self.selected()
        if not row:
            QMessageBox.information(self, "尚未選擇排程", "請先在列表中選擇一筆排程。")
            return
        if row.get("status") in ("published", "publishing"):
            QMessageBox.warning(self, "無法取消", "發布中或已發布成功的排程無法取消。")
            return
        confirm = QMessageBox.question(self, "取消排程", "確定要取消這筆排程嗎？")
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.db.cancel_schedule(int(row["id"]))
        self.refresh()

    def delete_selected(self) -> None:
        row = self.selected()
        if not row:
            QMessageBox.information(self, "尚未選擇排程", "請先在列表中選擇一筆排程。")
            return
        if row.get("status") == "publishing":
            QMessageBox.warning(self, "無法刪除", "發布中的排程無法刪除。")
            return
        confirm = QMessageBox.question(
            self, "刪除排程紀錄", "確定要刪除這筆排程紀錄嗎？此動作無法復原。"
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.db.delete_schedule(int(row["id"]))
        self.refresh()

    # ------------------------------------------------------------------

    def publish_selected(self) -> None:
        if self.runner is not None:
            QMessageBox.information(self, "發布進行中", "目前已有排程正在發布，請稍候。")
            return

        row = self.selected()
        if not row:
            QMessageBox.information(self, "尚未選擇排程", "請先在列表中選擇一筆排程。")
            return
        if row.get("status") not in ("scheduled", "failed"):
            QMessageBox.warning(self, "無法發布", "只有「已排程」或「發布失敗」的排程可以立即發布。")
            return

        target_label = row.get("target_label", "")
        confirm = QMessageBox.question(
            self,
            "確認立即發布",
            f"確定要立即發布到「{target_label}」嗎？\nHouseFlow 會自動按下 Facebook 的「發布」。",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        schedule_id = int(row["id"])
        self.db.mark_schedule_publishing(schedule_id)
        self.refresh()

        self.publish_btn.setEnabled(False)
        self.status_label.setText(f"正在發布：{row.get('property_title', '')} - {target_label} ……")

        self.runner = SchedulePublishRunner(self.db, row)
        self.runner.finished.connect(self._on_publish_finished)
        self.runner.failed.connect(self._on_publish_failed)
        self.runner.start()

    def _on_publish_finished(self, payload: dict) -> None:
        success = bool(payload.get("success"))
        message = str(payload.get("message", ""))
        self.status_label.setText(("發布成功：" if success else "發布失敗：") + message)
        self._finish_publish_ui()
        if success and callable(self.on_published):
            self.on_published()

    def _on_publish_failed(self, message: str) -> None:
        self.status_label.setText(f"發布發生錯誤：{message}")
        self._finish_publish_ui()

    def _finish_publish_ui(self) -> None:
        if self.runner is not None:
            self.runner.wait_and_cleanup()
        self.runner = None
        self.publish_btn.setEnabled(True)
        self.refresh()
