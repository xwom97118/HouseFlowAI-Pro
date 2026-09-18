from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QDateTime, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QDialog,
    QFrame,
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
from app.services.schedule_runner import ScheduleDeleteRunner, SchedulePublishRunner
from app.widgets.common import ClickableMetricCard, SectionTitle, show_toast
from app.widgets.schedule_dialog import DeleteRuleSelector, NewScheduleDialog, ScheduleTimePicker

STATUS_LABELS = {
    "draft": "草稿",
    "pending_review": "待檢核",
    "scheduled": "待發布",
    "publishing": "發布中",
    "published": "已發布",
    "failed": "發布失敗",
    "needs_review": "需要人工確認",
    "cancelled": "已取消",
    "deleted": "已刪除",
}

STATUS_DOTS = {
    "draft": "⚪",
    "pending_review": "🟠",
    "scheduled": "🔵",
    "publishing": "🔵",
    "published": "🟢",
    "failed": "🔴",
    "needs_review": "🔴",
    "cancelled": "⚪",
    "deleted": "⚪",
}

# 柔和背景色（不要高飽和），對應 styles.py 的 StatusBadge 配色語彙。
STATUS_COLORS = {
    "draft": ("#E5E9F0", "#526176"),
    "pending_review": ("#FEF3C7", "#B45309"),
    "scheduled": ("#DBEAFE", "#1D4ED8"),
    "publishing": ("#DBEAFE", "#1D4ED8"),
    "published": ("#DCFCE7", "#15803D"),
    "failed": ("#FEE2E2", "#B91C1C"),
    "needs_review": ("#FEE2E2", "#B91C1C"),
    "cancelled": ("#E5E9F0", "#526176"),
    "deleted": ("#E5E9F0", "#526176"),
}

DELETE_STATUS_LABELS = {
    "not_scheduled": "不自動刪除",
    "pending": "待刪除",
    "deleting": "刪除中",
    "deleted": "已刪除",
    "delete_failed": "刪除失敗",
    "manual_required": "需人工刪除",
    "cancelled": "已取消刪除",
}

DELETE_STATUS_DOTS = {
    "not_scheduled": "⚪",
    "pending": "🟣",
    "deleting": "🟣",
    "deleted": "⚪",
    "delete_failed": "🔴",
    "manual_required": "🟠",
    "cancelled": "⚪",
}

# (tab 標籤, status 篩選, delete_status 篩選) —— 兩者都是 None 代表不篩選。
TABS: list[tuple[str, list[str] | None, list[str] | None]] = [
    ("全部", None, None),
    ("待檢核", ["pending_review"], None),
    ("待發布", ["scheduled"], None),
    ("已發布", ["published"], None),
    ("失敗", ["failed", "needs_review"], None),
    ("待刪除", None, ["pending"]),
    ("已刪除", None, ["deleted"]),
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
        self.tab_index = 1  # 預設停在「待檢核」——這是每天打開 HouseFlow 第一件事要處理的畫面
        self.runner: SchedulePublishRunner | None = None
        self.delete_runner: ScheduleDeleteRunner | None = None
        self._pending_highlight_batch: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 24)
        root.setSpacing(12)

        title_row = QHBoxLayout()
        back_btn = QPushButton("← 返回 Dashboard")
        back_btn.setObjectName("SecondaryButton")
        back_btn.clicked.connect(lambda _=False: self.go_dashboard())
        title_row.addWidget(back_btn)
        title_row.addWidget(
            SectionTitle("排程發布中心", "建立、核准與追蹤 Facebook 排程發布。"),
            1,
        )
        add_btn = QPushButton("＋新增排程")
        add_btn.setObjectName("PrimaryButton")
        add_btn.clicked.connect(self.add_schedule)
        title_row.addWidget(add_btn)
        root.addLayout(title_row)

        # 今日 Summary Cards：可以直接點擊切換下面的 Tab -----------------
        cards_row = QHBoxLayout()
        self.card_pending = ClickableMetricCard("今日待檢核", "0")
        self.card_scheduled = ClickableMetricCard("今日待發布", "0")
        self.card_published = ClickableMetricCard("今日已發布", "0")
        self.card_failed = ClickableMetricCard("今日失敗", "0")
        self.card_delete_pending = ClickableMetricCard("今日待刪除", "0")
        self.card_deleted = ClickableMetricCard("今日已刪除", "0")
        card_to_tab = {
            self.card_pending: 1,
            self.card_scheduled: 2,
            self.card_published: 3,
            self.card_failed: 4,
            self.card_delete_pending: 5,
            self.card_deleted: 6,
        }
        for card, tab_index in card_to_tab.items():
            card.clicked.connect(lambda _=False, idx=tab_index: self.set_tab(idx))
            cards_row.addWidget(card, 1)
        root.addLayout(cards_row)

        # 狀態 Tabs（segmented control）取代原本的篩選下拉 ------------------
        tabs_row = QHBoxLayout()
        tabs_row.setSpacing(6)
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        self.tab_buttons: list[QPushButton] = []
        for index, (label, _statuses, _delete_statuses) in enumerate(TABS):
            button = QPushButton(label)
            button.setObjectName("TabButton")
            button.setCheckable(True)
            button.clicked.connect(lambda _=False, idx=index: self.set_tab(idx))
            self.tab_group.addButton(button)
            self.tab_buttons.append(button)
            tabs_row.addWidget(button)

        self.approve_all_btn = QPushButton("核准今日全部")
        self.approve_all_btn.setObjectName("SecondaryButton")
        self.approve_all_btn.clicked.connect(self.approve_all_today)
        tabs_row.addWidget(self.approve_all_btn)

        self.review_mode_btn = QPushButton("開始檢核")
        self.review_mode_btn.setObjectName("SuccessButton")
        self.review_mode_btn.clicked.connect(self.open_review_mode)
        tabs_row.addWidget(self.review_mode_btn)

        tabs_row.addStretch()
        root.addLayout(tabs_row)

        # Bulk actions：只有多選時才出現 ----------------------------------
        self.bulk_bar = QFrame()
        self.bulk_bar.setObjectName("Card")
        bulk_layout = QHBoxLayout(self.bulk_bar)
        bulk_layout.setContentsMargins(12, 8, 12, 8)
        self.bulk_label = QLabel("")
        bulk_layout.addWidget(self.bulk_label)
        bulk_layout.addStretch()
        bulk_approve_btn = QPushButton("全部核准")
        bulk_approve_btn.setObjectName("PrimaryButton")
        bulk_approve_btn.clicked.connect(self.bulk_approve_selected)
        bulk_clear_btn = QPushButton("取消選取")
        bulk_clear_btn.setObjectName("SecondaryButton")
        bulk_clear_btn.clicked.connect(lambda: self.table.clearSelection())
        bulk_layout.addWidget(bulk_approve_btn)
        bulk_layout.addWidget(bulk_clear_btn)
        self.bulk_bar.setVisible(False)
        root.addWidget(self.bulk_bar)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["物件", "發布位置", "排程時間", "狀態", "自動刪除"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(self.view_selected)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        root.addWidget(self.table, 1)

        # 情境式操作列：依照目前選取的排程狀態，只顯示真正需要的操作 -------
        actions_row = QHBoxLayout()
        actions_row.setSpacing(8)

        self.view_btn = self._action_button("查看詳情", self.view_selected, actions_row)
        self.submit_draft_btn = self._action_button("送出待檢核", self.submit_draft_selected, actions_row)
        self.approve_btn = self._action_button("核准", self.approve_selected, actions_row)
        self.reject_btn = self._action_button("退回修改", self.reject_selected, actions_row)
        self.modify_time_btn = self._action_button("修改時間", self.modify_time_selected, actions_row)
        self.publish_btn = self._action_button("立即發布", self.publish_selected, actions_row)
        self.resolve_btn = self._action_button("處理需要確認", self.resolve_needs_review_selected, actions_row)
        self.delete_post_btn = self._action_button("刪除貼文", self.delete_post_selected, actions_row)
        self.modify_delete_btn = self._action_button("修改刪除時間", self.modify_delete_rule_selected, actions_row)
        self.cancel_delete_btn = self._action_button("取消自動刪除", self.cancel_auto_delete_selected, actions_row)
        self.cancel_btn = self._action_button("取消排程", self.cancel_selected, actions_row)
        self.delete_btn = self._action_button("刪除紀錄", self.delete_selected, actions_row)

        actions_row.addStretch()
        root.addLayout(actions_row)

        self.status_label = QLabel("準備完成")
        self.status_label.setObjectName("MutedLabel")
        root.addWidget(self.status_label)

        self.tab_buttons[self.tab_index].setChecked(True)
        self.refresh()

    @staticmethod
    def _action_button(label: str, handler, layout: QHBoxLayout) -> QPushButton:
        button = QPushButton(label)
        button.setObjectName("SecondaryButton")
        button.clicked.connect(handler)
        layout.addWidget(button)
        return button

    # ------------------------------------------------------------------

    def refresh(self) -> None:
        self._refresh_summary()
        self._refresh_table()

    def _refresh_summary(self) -> None:
        counts = self.db.today_automation_summary()
        self.card_pending.set_value(counts.get("pending_review_today", 0))
        self.card_scheduled.set_value(counts.get("scheduled_today", 0))
        self.card_published.set_value(counts.get("published_today", 0))
        self.card_failed.set_value(counts.get("failed_today", 0))
        self.card_delete_pending.set_value(counts.get("delete_pending_today", 0))
        self.card_deleted.set_value(counts.get("deleted_today", 0))

    def set_tab(self, index: int) -> None:
        if not (0 <= index < len(TABS)):
            return
        self.tab_index = index
        self.tab_buttons[index].setChecked(True)
        self._refresh_table()

    def _current_filter(self) -> tuple[list[str] | None, list[str] | None]:
        _label, statuses, delete_statuses = TABS[self.tab_index]
        return statuses, delete_statuses

    def _refresh_table(self) -> None:
        selected_ids = set(self._selected_ids())
        statuses, delete_statuses = self._current_filter()
        self.rows = self.db.list_schedules(statuses=statuses, delete_statuses=delete_statuses)

        is_review_tab = TABS[self.tab_index][0] == "待檢核"
        self.approve_all_btn.setVisible(is_review_tab)
        self.review_mode_btn.setVisible(is_review_tab and bool(self.rows))

        self.table.setRowCount(len(self.rows))
        rows_to_select: list[int] = []
        for row_index, row in enumerate(self.rows):
            title = str(row.get("property_title") or "（物件已刪除）")
            status = row.get("status", "")
            delete_status = row.get("delete_status", "")

            status_text = f"{STATUS_DOTS.get(status, '⚪')} {STATUS_LABELS.get(status, status)}"
            delete_text = f"{DELETE_STATUS_DOTS.get(delete_status, '⚪')} {DELETE_STATUS_LABELS.get(delete_status, delete_status)}"

            values = [title, row.get("target_label", ""), row.get("scheduled_at", ""), status_text, delete_text]
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                if column_index in (2, 3, 4):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if column_index == 3:
                    bg, fg = STATUS_COLORS.get(status, ("#E5E9F0", "#526176"))
                    item.setBackground(QColor(bg))
                    item.setForeground(QColor(fg))
                self.table.setItem(row_index, column_index, item)

            if row.get("id") in selected_ids:
                rows_to_select.append(row_index)
            if self._pending_highlight_batch and row.get("batch_id") == self._pending_highlight_batch:
                rows_to_select.append(row_index)

        self.table.resizeColumnsToContents()
        for row_index in rows_to_select:
            self.table.selectRow(row_index)
        if rows_to_select:
            self.table.scrollToItem(self.table.item(rows_to_select[0], 0))
        self._pending_highlight_batch = None

        self.status_label.setText(f"目前顯示 {len(self.rows)} 筆排程")
        self._on_selection_changed()

    def selected(self) -> dict | None:
        row_index = self.table.currentRow()
        return self.rows[row_index] if 0 <= row_index < len(self.rows) else None

    def selected_id(self) -> int | None:
        row = self.selected()
        return int(row["id"]) if row else None

    def _selected_ids(self) -> list[int]:
        indexes = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        ids: list[int] = []
        for index in indexes:
            row_index = index.row()
            if 0 <= row_index < len(self.rows):
                ids.append(int(self.rows[row_index]["id"]))
        return ids

    def _selected_rows_data(self) -> list[dict]:
        ids = set(self._selected_ids())
        return [row for row in self.rows if row.get("id") in ids]

    # ------------------------------------------------------------------
    # 情境式操作列：依選取的排程狀態顯示/隱藏對應按鈕
    # ------------------------------------------------------------------

    def _on_selection_changed(self) -> None:
        selected_ids = self._selected_ids()
        row = self.selected()

        # Bulk bar：待檢核 tab 下多選才出現
        is_review_tab = TABS[self.tab_index][0] == "待檢核"
        if is_review_tab and len(selected_ids) > 1:
            self.bulk_bar.setVisible(True)
            self.bulk_label.setText(f"☑ {len(selected_ids)} 筆已選取")
        else:
            self.bulk_bar.setVisible(False)

        buttons = (
            self.view_btn, self.submit_draft_btn, self.approve_btn, self.reject_btn,
            self.modify_time_btn, self.publish_btn, self.resolve_btn, self.delete_post_btn,
            self.modify_delete_btn, self.cancel_delete_btn, self.cancel_btn, self.delete_btn,
        )

        if not row or len(selected_ids) > 1:
            for button in buttons:
                button.setVisible(False)
            return

        status = row.get("status", "")
        delete_status = row.get("delete_status", "")
        has_post_url = bool(str(row.get("post_url") or "").strip())

        self.view_btn.setVisible(True)
        self.submit_draft_btn.setVisible(status == "draft")
        self.approve_btn.setVisible(status == "pending_review")
        self.reject_btn.setVisible(status == "pending_review")
        self.modify_time_btn.setVisible(status == "scheduled")
        self.publish_btn.setVisible(status in ("scheduled", "failed"))
        self.publish_btn.setText("重新嘗試" if status == "failed" else "立即發布")
        self.resolve_btn.setVisible(status == "needs_review")
        self.delete_post_btn.setVisible(status == "published" and has_post_url)
        self.modify_delete_btn.setVisible(
            status == "published" and delete_status in ("pending", "manual_required")
        )
        self.cancel_delete_btn.setVisible(delete_status == "pending")
        self.cancel_btn.setVisible(status in ("draft", "pending_review", "scheduled", "failed", "needs_review"))
        self.delete_btn.setVisible(status != "publishing")

    # ------------------------------------------------------------------

    def add_schedule(self) -> None:
        dialog = NewScheduleDialog(self.db, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def focus_batch(self, batch_id: str) -> None:
        """從發文中心「加入排程」導過來時，直接切到全部並反白剛建立的那幾筆。"""
        self._pending_highlight_batch = batch_id
        self.set_tab(0)
        self.status_label.setText("已建立排程，已為您反白顯示。")

    def view_selected(self, *_args) -> None:
        row = self.selected()
        if not row:
            QMessageBox.information(self, "尚未選擇排程", "請先在列表中選擇一筆排程。")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("排程詳情")
        dialog.resize(600, 560)
        layout = QVBoxLayout(dialog)

        info = (
            f"物件：{row.get('property_title', '')}\n"
            f"發布位置：{row.get('target_label', '')}\n"
            f"排程時間：{row.get('scheduled_at', '')}\n"
            f"狀態：{STATUS_LABELS.get(row.get('status', ''), row.get('status', ''))}\n"
            f"核准時間：{row.get('approved_at', '') or '—'}\n"
            f"實際發布時間：{row.get('published_at', '') or '—'}\n"
            f"重試次數：{row.get('retry_count', 0)}\n"
            f"圖片：{len([p for p in str(row.get('images', '')).split(chr(10)) if p.strip()])} 張\n"
            f"自動刪除：{DELETE_STATUS_LABELS.get(row.get('delete_status', ''), row.get('delete_status', ''))}"
            f"（{row.get('delete_at', '') or '未設定'}）\n"
        )
        if row.get("error_message"):
            info += f"失敗原因：{row.get('error_message')}\n"

        batch_id = str(row.get("batch_id") or "")
        if batch_id:
            batch_rows = self.db.list_batch_schedules(batch_id)
            if len(batch_rows) > 1:
                success = sum(1 for r in batch_rows if r.get("status") == "published")
                info += f"\n同批發布位置：{success}/{len(batch_rows)} 成功\n"
                for r in batch_rows:
                    icon = {"published": "✅", "failed": "❌", "needs_review": "⚠"}.get(
                        r.get("status", ""), "⏳"
                    )
                    info += f"  {icon} {r.get('target_label', '')}：{STATUS_LABELS.get(r.get('status', ''), r.get('status', ''))}\n"

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

    # ------------------------------------------------------------------
    # 單筆狀態操作：每一個都先給立即回饋，再做 targeted refresh（不整頁重建）
    # ------------------------------------------------------------------

    def _require_selection(self) -> dict | None:
        row = self.selected()
        if not row:
            QMessageBox.information(self, "尚未選擇排程", "請先在列表中選擇一筆排程。")
        return row

    def submit_draft_selected(self) -> None:
        row = self._require_selection()
        if not row:
            return
        scheduled_at = str(row.get("scheduled_at") or "").strip()
        if not scheduled_at:
            scheduled_at = QDateTime.currentDateTime().addSecs(3 * 3600).toString("yyyy-MM-dd HH:mm:00")

        self.submit_draft_btn.setEnabled(False)
        self.db.submit_draft(int(row["id"]), scheduled_at)
        self.submit_draft_btn.setEnabled(True)
        show_toast(self, "✓ 已送出待檢核", kind="success")
        self.refresh()

    def approve_selected(self) -> None:
        row = self._require_selection()
        if not row:
            return
        self.approve_btn.setEnabled(False)
        self.approve_btn.setText("核准中…")
        self.db.approve_schedule(int(row["id"]))
        self.approve_btn.setEnabled(True)
        show_toast(self, "✓ 已核准", kind="success")
        self.refresh()

    def bulk_approve_selected(self) -> None:
        rows = self._selected_rows_data()
        pending = [row for row in rows if row.get("status") == "pending_review"]
        if not pending:
            return
        confirm = QMessageBox.question(self, "全部核准", f"確定要核准選取的 {len(pending)} 筆排程嗎？")
        if confirm != QMessageBox.StandardButton.Yes:
            return
        for row in pending:
            self.db.approve_schedule(int(row["id"]))
        show_toast(self, f"✓ 已核准 {len(pending)} 筆", kind="success")
        self.refresh()

    def approve_all_today(self) -> None:
        confirm = QMessageBox.question(
            self, "核准今日全部待檢核", "確定要核准所有「今天」預定發布的待檢核排程嗎？"
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        count = self.db.approve_all_pending_today()
        show_toast(self, f"✓ 已核准今日 {count} 筆", kind="success")
        self.refresh()

    def reject_selected(self) -> None:
        row = self._require_selection()
        if not row:
            return
        self.db.reject_schedule(int(row["id"]))
        show_toast(self, "已退回草稿", kind="info")
        self.refresh()

    def modify_time_selected(self) -> None:
        row = self._require_selection()
        if not row:
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("修改發布時間")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"「{row.get('property_title', '')} - {row.get('target_label', '')}」的發布時間："))
        picker = ScheduleTimePicker()
        current = str(row.get("scheduled_at") or "").strip()
        if current:
            dt = QDateTime.fromString(current, "yyyy-MM-dd HH:mm:ss")
            if dt.isValid():
                picker.date_edit.setDate(dt.date())
                picker.time_edit.setTime(dt.time())
        layout.addWidget(picker)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("儲存")
        ok_btn.setObjectName("PrimaryButton")
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.setObjectName("SecondaryButton")
        cancel_btn.clicked.connect(dialog.reject)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if not picker.is_valid():
            QMessageBox.warning(self, "發布時間不正確", "發布時間不能早於目前時間。")
            return

        self.db.update_schedule_time(int(row["id"]), picker.value_str())
        show_toast(self, "✓ 已修改發布時間", kind="success")
        self.refresh()

    def cancel_selected(self) -> None:
        row = self._require_selection()
        if not row:
            return
        confirm = QMessageBox.question(self, "取消排程", "確定要取消這筆排程嗎？")
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.db.cancel_schedule(int(row["id"]))
        show_toast(self, "已取消排程", kind="info")
        self.refresh()

    def delete_selected(self) -> None:
        row = self._require_selection()
        if not row:
            return
        confirm = QMessageBox.question(
            self, "刪除排程紀錄", "確定要刪除這筆排程紀錄嗎？此動作無法復原。"
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.db.delete_schedule(int(row["id"]))
        show_toast(self, "已刪除紀錄", kind="info")
        self.refresh()

    # ------------------------------------------------------------------
    # 需要人工確認（發布結果不確定）

    def resolve_needs_review_selected(self) -> None:
        row = self._require_selection()
        if not row:
            return

        target_label = row.get("target_label", "")
        reason = row.get("error_message", "")
        box = QMessageBox(self)
        box.setWindowTitle("需要人工確認")
        box.setText(
            f"「{row.get('property_title', '')} - {target_label}」的發布結果無法自動確認"
            f"（原因：{reason or '未知'}）。\n\n"
            "請先到 Facebook 上實際確認這篇貼文是否已經發布，再選擇下面的處理方式："
        )
        already_btn = box.addButton("已經發布成功", QMessageBox.ButtonRole.YesRole)
        retry_btn = box.addButton("尚未發布，重新嘗試", QMessageBox.ButtonRole.ActionRole)
        cancel_btn = box.addButton("取消這筆排程", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("先不處理", QMessageBox.ButtonRole.RejectRole)
        box.exec()

        clicked = box.clickedButton()
        if clicked is already_btn:
            self.db.resolve_needs_review(int(row["id"]), "already_published")
            show_toast(self, "已標記為發布成功", kind="success")
        elif clicked is retry_btn:
            self.db.resolve_needs_review(int(row["id"]), "retry")
            show_toast(self, "已排回等待自動重新發布", kind="info")
        elif clicked is cancel_btn:
            self.db.resolve_needs_review(int(row["id"]), "cancel")
            show_toast(self, "已取消這筆排程", kind="info")
        else:
            return
        self.refresh()

    # ------------------------------------------------------------------
    # 自動刪文相關手動操作

    def delete_post_selected(self) -> None:
        if self.delete_runner is not None:
            QMessageBox.information(self, "刪除進行中", "目前已有貼文正在刪除，請稍候。")
            return

        row = self._require_selection()
        if not row:
            return
        post_url = str(row.get("post_url") or "").strip()
        if not post_url:
            QMessageBox.warning(
                self,
                "無法自動刪除",
                "這筆貼文沒有可靠的貼文網址，HouseFlow 無法安全確認要刪哪一篇，"
                "請自行到 Facebook 上手動刪除。",
            )
            return
        if row.get("delete_status") == "deleting":
            QMessageBox.information(self, "刪除進行中", "這筆貼文正在刪除中，請稍候。")
            return

        confirm = QMessageBox(self)
        confirm.setIcon(QMessageBox.Icon.Warning)
        confirm.setWindowTitle("確認刪除貼文")
        confirm.setText("確定要刪除Facebook上這篇貼文嗎？此操作可能無法復原。")
        confirm.setInformativeText(
            f"物件：{row.get('property_title', '')}\n"
            f"Facebook 位置：{row.get('target_label', '')}\n"
            f"發布時間：{row.get('published_at', '')}"
        )
        yes_btn = confirm.addButton("確定刪除", QMessageBox.ButtonRole.YesRole)
        confirm.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        confirm.exec()
        if confirm.clickedButton() is not yes_btn:
            return

        schedule_id = int(row["id"])
        self.delete_post_btn.setEnabled(False)
        self.delete_post_btn.setText("刪除中…")
        self.status_label.setText(f"正在刪除貼文：{row.get('property_title', '')} - {row.get('target_label', '')} ……")

        self.delete_runner = ScheduleDeleteRunner(self.db, row)
        self.delete_runner.finished.connect(self._on_delete_finished)
        self.delete_runner.failed.connect(self._on_delete_failed)
        self.delete_runner.start()

    def _on_delete_finished(self, payload: dict) -> None:
        success = bool(payload.get("success"))
        message = str(payload.get("message", ""))
        if success:
            show_toast(self, "✓ 貼文已刪除", kind="success")
        else:
            self.status_label.setText(f"刪除失敗：{message}")
        self._finish_delete_ui()

    def _on_delete_failed(self, message: str) -> None:
        self.status_label.setText(f"刪除發生錯誤：{message}")
        self._finish_delete_ui()

    def _finish_delete_ui(self) -> None:
        if self.delete_runner is not None:
            self.delete_runner.wait_and_cleanup()
        self.delete_runner = None
        self.delete_post_btn.setEnabled(True)
        self.delete_post_btn.setText("刪除貼文")
        self.refresh()

    def modify_delete_rule_selected(self) -> None:
        row = self._require_selection()
        if not row:
            return

        current_days = row.get("delete_after_days")
        current_days = int(current_days) if current_days not in (None, "") else None

        dialog = QDialog(self)
        dialog.setWindowTitle("修改刪除時間")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"「{row.get('property_title', '')} - {row.get('target_label', '')}」的自動刪除時間："))
        selector = DeleteRuleSelector(self.db, preset_days=current_days)
        layout.addWidget(selector)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("儲存")
        ok_btn.setObjectName("PrimaryButton")
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.setObjectName("SecondaryButton")
        cancel_btn.clicked.connect(dialog.reject)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self.db.update_delete_rule(int(row["id"]), selector.value())
        show_toast(self, "✓ 已更新自動刪除時間", kind="success")
        self.refresh()

    def cancel_auto_delete_selected(self) -> None:
        row = self._require_selection()
        if not row:
            return
        confirm = QMessageBox.question(self, "取消自動刪除", "確定要取消這篇貼文的自動刪除排程嗎？")
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.db.cancel_auto_delete(int(row["id"]))
        show_toast(self, "已取消自動刪除", kind="info")
        self.refresh()

    # ------------------------------------------------------------------

    def publish_selected(self) -> None:
        if self.runner is not None:
            QMessageBox.information(self, "發布進行中", "目前已有排程正在發布，請稍候。")
            return

        row = self._require_selection()
        if not row:
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
        self.publish_btn.setText("發布中…")
        self.status_label.setText(f"正在發布：{row.get('property_title', '')} - {target_label} ……")

        self.runner = SchedulePublishRunner(self.db, row)
        self.runner.finished.connect(self._on_publish_finished)
        self.runner.failed.connect(self._on_publish_failed)
        self.runner.start()

    def _on_publish_finished(self, payload: dict) -> None:
        success = bool(payload.get("success"))
        message = str(payload.get("message", ""))
        if success:
            show_toast(self, "✓ 發布成功", kind="success")
        else:
            self.status_label.setText(f"發布失敗：{message}")
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
        self.publish_btn.setText("立即發布")
        self.refresh()

    # ------------------------------------------------------------------
    # Review Mode：每天最重要的日常工作——連續核准今天要檢核的排程
    # ------------------------------------------------------------------

    def open_review_mode(self) -> None:
        pending = self.db.list_schedules(statuses=["pending_review"])
        if not pending:
            QMessageBox.information(self, "沒有待檢核排程", "目前沒有待檢核的排程。")
            return
        dialog = ReviewModeDialog(self.db, pending, parent=self)
        dialog.exec()
        self.refresh()


class ReviewModeDialog(QDialog):
    """快速檢核模式：一次只看一篇，核准後自動進下一篇，不用每核准一筆
    就跳回表格重新選取——這是 HouseFlow 每天最重要的操作路徑。
    """

    def __init__(self, db: Database, rows: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.db = db
        self.rows = rows
        self.index = 0

        self.setWindowTitle("快速檢核")
        self.resize(640, 640)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        self.progress_label = QLabel("")
        self.progress_label.setObjectName("Muted")
        layout.addWidget(self.progress_label)

        self.title_label = QLabel("")
        self.title_label.setObjectName("PageTitle")
        layout.addWidget(self.title_label)

        self.meta_label = QLabel("")
        self.meta_label.setWordWrap(True)
        layout.addWidget(self.meta_label)

        self.content_view = QPlainTextEdit()
        self.content_view.setReadOnly(True)
        layout.addWidget(self.content_view, 1)

        nav_row = QHBoxLayout()
        self.prev_btn = QPushButton("← 上一篇")
        self.prev_btn.setObjectName("SecondaryButton")
        self.prev_btn.clicked.connect(self.go_prev)

        self.reject_btn = QPushButton("退回修改")
        self.reject_btn.setObjectName("SecondaryButton")
        self.reject_btn.clicked.connect(self.reject_current)

        self.approve_btn = QPushButton("✓ 核准")
        self.approve_btn.setObjectName("PrimaryButton")
        self.approve_btn.clicked.connect(self.approve_current)

        self.next_btn = QPushButton("下一篇 →")
        self.next_btn.setObjectName("SecondaryButton")
        self.next_btn.clicked.connect(self.go_next)

        nav_row.addWidget(self.prev_btn)
        nav_row.addStretch()
        nav_row.addWidget(self.reject_btn)
        nav_row.addWidget(self.approve_btn)
        nav_row.addStretch()
        nav_row.addWidget(self.next_btn)
        layout.addLayout(nav_row)

        close_btn = QPushButton("關閉")
        close_btn.setObjectName("SecondaryButton")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        self._render()

    def _render(self) -> None:
        if not self.rows:
            self.title_label.setText("今天沒有待檢核的排程了 🎉")
            self.meta_label.setText("")
            self.content_view.setPlainText("")
            self.progress_label.setText("")
            for button in (self.prev_btn, self.reject_btn, self.approve_btn, self.next_btn):
                button.setEnabled(False)
            return

        self.index = max(0, min(self.index, len(self.rows) - 1))
        row = self.rows[self.index]

        self.progress_label.setText(f"{self.index + 1} / {len(self.rows)}")
        self.title_label.setText(str(row.get("property_title") or "（物件已刪除）"))

        delete_days = row.get("delete_after_days")
        delete_text = f"發布後 {delete_days} 天自動刪除" if delete_days else "不自動刪除"
        images = len([p for p in str(row.get("images", "")).split("\n") if p.strip()])

        self.meta_label.setText(
            f"發布位置：{row.get('target_label', '')}　｜　"
            f"發布時間：{row.get('scheduled_at', '')}　｜　"
            f"圖片：{images} 張　｜　"
            f"自動刪除：{delete_text}"
        )
        self.content_view.setPlainText(str(row.get("copy_text", "")))

        self.prev_btn.setEnabled(self.index > 0)
        self.next_btn.setEnabled(self.index < len(self.rows) - 1)
        self.reject_btn.setEnabled(True)
        self.approve_btn.setEnabled(True)

    def go_prev(self) -> None:
        self.index -= 1
        self._render()

    def go_next(self) -> None:
        self.index += 1
        self._render()

    def approve_current(self) -> None:
        if not self.rows:
            return
        row = self.rows[self.index]
        self.db.approve_schedule(int(row["id"]))
        show_toast(self, "✓ 已核准", kind="success")
        self._advance_after_decision()

    def reject_current(self) -> None:
        if not self.rows:
            return
        row = self.rows[self.index]
        self.db.reject_schedule(int(row["id"]))
        show_toast(self, "已退回草稿", kind="info")
        self._advance_after_decision()

    def _advance_after_decision(self) -> None:
        del self.rows[self.index]
        if self.index >= len(self.rows):
            self.index = len(self.rows) - 1
        self._render()
