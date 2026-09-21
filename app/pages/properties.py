from __future__ import annotations

import webbrowser
from collections.abc import Callable

from PySide6.QtCore import QDateTime, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
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
from app.services.schedule_runner import SchedulePublishRunner
from app.services.sync_runner import SyncRunner
from app.widgets.common import SectionTitle, show_toast
from app.widgets.quick_schedule_dialog import QuickScheduleDialog
from app.widgets.universal_import_dialog import UniversalImportDialog

DEFAULT_SOURCE_URL = (
    "https://shop.yungching.com.tw/"
    "034990660/list/%E4%BD%8F%E5%AE%85_p"
)

STATUS_FILTERS = ["全部", "新物件", "價格異動", "下架"]


def _parse_wan(value: str) -> float | None:
    import re

    match = re.search(r"(\d+(?:\.\d+)?)", (value or "").replace(",", ""))
    return float(match.group(1)) if match else None


def _format_price_delta(old_value: str, new_value: str) -> str:
    old_num = _parse_wan(old_value)
    new_num = _parse_wan(new_value)
    if old_num is None or new_num is None or old_num == new_num:
        return "已異動"
    arrow = "↓" if new_num < old_num else "↑"
    return f"{arrow} {abs(old_num - new_num):g}萬"


def _short_dt(value: str) -> str:
    if not value:
        return ""
    dt = QDateTime.fromString(value, "yyyy-MM-dd HH:mm:ss")
    return dt.toString("M/d HH:mm") if dt.isValid() else value


# 2026-09-21 UX 重構：物件中心新增的排程狀態欄——把 schedules table 的
# 原始狀態值（scheduled/publishing/published/failed/...）換成使用者
# 看得懂的一句話，不用進排程中心才知道「這個物件現在是什麼狀態」。
def _schedule_status_cell(latest: dict | None) -> tuple[str, tuple[str, str]]:
    if not latest:
        return "未排程", ("#E5E9F0", "#526176")

    status = latest.get("status", "")
    delete_status = latest.get("delete_status", "")
    delete_at = latest.get("delete_at", "")

    if status in ("draft", "pending_review", "scheduled"):
        text = f"🟡 已排程 {_short_dt(latest.get('scheduled_at', ''))}"
        return text, ("#FEF3C7", "#B45309")
    if status == "publishing":
        return "🔵 發布中", ("#DBEAFE", "#1D4ED8")
    if status == "published":
        text = f"🟢 已發布 {_short_dt(latest.get('published_at', ''))}"
        if delete_status == "pending" and delete_at:
            text += f"　🗑 {_short_dt(delete_at)}"
        return text, ("#DCFCE7", "#15803D")
    if status in ("failed", "needs_review"):
        return "🔴 發布失敗", ("#FEE2E2", "#B91C1C")
    if status == "cancelled":
        return "⚪ 已取消", ("#E5E9F0", "#526176")
    return status or "未排程", ("#E5E9F0", "#526176")


class PropertiesPage(QWidget):
    def __init__(
        self,
        db: Database,
        open_ai: Callable[[int], None],
        go_dashboard: Callable[[], None],
        go_schedule: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self.db = db
        self.open_ai = open_ai
        self.go_dashboard = go_dashboard
        self.go_schedule = go_schedule
        self.runner: SyncRunner | None = None
        self.publish_runner: SchedulePublishRunner | None = None
        self.rows: list[dict] = []
        self.schedule_status_map: dict[int, dict] = {}

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

        self.status_filter = QComboBox()
        self.status_filter.addItems(STATUS_FILTERS)
        self.status_filter.currentIndexChanged.connect(self.refresh)

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
        ai_btn.setObjectName("SecondaryButton")
        ai_btn.clicked.connect(self.send_to_ai)

        # 2026-09-21 UX 重構：物件中心的主要操作——一個按鈕直接開啟
        # Quick Schedule Dialog，不用先跳到排程中心再選物件。
        self.schedule_btn = QPushButton("📅 安排發文")
        self.schedule_btn.setObjectName("PrimaryButton")
        self.schedule_btn.clicked.connect(self.open_quick_schedule)

        tools.addWidget(self.search, 1)
        tools.addWidget(self.favorites_only)
        tools.addWidget(QLabel("篩選："))
        tools.addWidget(self.status_filter)
        tools.addWidget(refresh_btn)
        tools.addWidget(self.favorite_btn)
        tools.addWidget(note_btn)
        tools.addWidget(open_btn)
        tools.addWidget(ai_btn)
        tools.addWidget(self.schedule_btn)
        root.addLayout(tools)

        self.status_label = QLabel("準備完成")
        self.status_label.setObjectName("MutedLabel")
        root.addWidget(self.status_label)

        self.table = QTableWidget(0, 12)
        self.table.setHorizontalHeaderLabels(
            ["收藏", "狀態", "ID", "物件編號", "物件名稱", "地址", "價格", "格局", "坪數", "標籤", "備註", "排程狀態"]
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
        all_rows = self.db.list_properties(
            self.search.text().strip(),
            self.favorites_only.isChecked(),
        )
        changes_map = self.db.recent_property_changes_map()
        self.schedule_status_map = self.db.latest_schedule_by_property()

        status_filter = self.status_filter.currentText()
        self.rows = []
        for row in all_rows:
            badge, kind = self._status_badge(row, changes_map)
            if status_filter == "新物件" and badge != "🆕 新物件":
                continue
            if status_filter == "價格異動" and not (badge.startswith("↓") or badge.startswith("↑")):
                continue
            if status_filter == "下架" and row.get("status") != "offline":
                continue
            row = dict(row)
            row["_badge"] = badge
            row["_badge_kind"] = kind
            self.rows.append(row)

        self.table.setRowCount(len(self.rows))
        selected_row = -1
        for row_index, row in enumerate(self.rows):
            self._render_row(row_index, row)
            if row.get("id") == selected_id:
                selected_row = row_index
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(4, 280)
        self.table.setColumnWidth(5, 220)
        self.table.setColumnWidth(10, 220)
        if selected_row >= 0:
            self.table.selectRow(selected_row)
        favorites = sum(int(row.get("favorite", 0) or 0) for row in self.rows)
        self.status_label.setText(f"目前顯示 {len(self.rows)} 筆物件，其中 {favorites} 筆收藏")

    def _render_row(self, row_index: int, row: dict) -> None:
        schedule_status, schedule_kind = _schedule_status_cell(
            self.schedule_status_map.get(int(row.get("id") or 0))
        )
        values = [
            "★" if int(row.get("favorite", 0) or 0) else "",
            row.get("_badge", ""),
            row.get("id", ""), row.get("external_id", ""), row.get("title", ""),
            row.get("address", ""), row.get("price", ""), row.get("layout", ""),
            row.get("size", ""), row.get("tag", ""), row.get("note", ""),
            schedule_status,
        ]
        for column_index, value in enumerate(values):
            item = QTableWidgetItem(str(value or ""))
            if column_index in (0, 1, 2, 3, 6, 7, 8, 9, 11):
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if column_index == 1 and row.get("_badge_kind"):
                bg, fg = row["_badge_kind"]
                item.setBackground(QColor(bg))
                item.setForeground(QColor(fg))
            if column_index == 11:
                bg, fg = schedule_kind
                item.setBackground(QColor(bg))
                item.setForeground(QColor(fg))
            self.table.setItem(row_index, column_index, item)

    def _refresh_schedule_status_for_property(self, property_id: int) -> None:
        """只更新單一物件的排程狀態欄，不重新查整張 properties 清單、
        不重建整個表格——建一筆排程之後不需要 unnecessary full refresh。
        """
        self.schedule_status_map = self.db.latest_schedule_by_property()
        for row_index, row in enumerate(self.rows):
            if int(row.get("id") or 0) == property_id:
                schedule_status, schedule_kind = _schedule_status_cell(
                    self.schedule_status_map.get(property_id)
                )
                item = self.table.item(row_index, 11)
                if item is not None:
                    item.setText(schedule_status)
                    bg, fg = schedule_kind
                    item.setBackground(QColor(bg))
                    item.setForeground(QColor(fg))
                break

    @staticmethod
    def _status_badge(row: dict, changes_map: dict[int, dict]) -> tuple[str, tuple[str, str] | None]:
        if row.get("status") == "offline":
            return "已下架", ("#E5E9F0", "#526176")
        change = changes_map.get(int(row.get("id") or 0))
        if not change:
            return "", None
        change_type = change.get("change_type")
        if change_type == "created":
            return "🆕 新物件", ("#DBEAFE", "#1D4ED8")
        if change_type == "price_changed":
            return _format_price_delta(change.get("old_value", ""), change.get("new_value", "")), (
                "#FEF3C7", "#B45309",
            )
        if change_type == "content_changed":
            return "已異動", ("#DCFCE7", "#15803D")
        return "", None

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
        if self.runner is not None:
            QMessageBox.information(self, "同步進行中", "目前已有同步正在執行，請稍候。")
            return
        source_url = self.source_url.text().strip()
        if not source_url:
            QMessageBox.warning(self, "缺少網址", "請先輸入永慶或台慶店頭物件列表網址；若要匯入其他公司的單一物件，請按「匯入單一物件網址」。")
            return
        self.db.set_setting("property_source_url", source_url)
        self.sync_button.setEnabled(False)
        self.sync_button.setText("同步中…")
        self.status_label.setText("正在讀取網站，請稍候…（不會卡住畫面，可切換到其他頁面）")

        self.runner = SyncRunner(self.db, {"id": None, "url": source_url, "name": "物件中心手動同步"})
        self.runner.progress.connect(self._on_sync_progress)
        self.runner.finished.connect(self._on_sync_finished)
        self.runner.failed.connect(self._on_sync_failed)
        self.runner.start()

    def _on_sync_progress(self, payload: dict) -> None:
        message = str(payload.get("message", ""))
        if message:
            self.status_label.setText(message)

    def _on_sync_finished(self, payload: dict) -> None:
        counts = payload.get("counts", {})
        found = payload.get("found", 0)
        self.refresh()
        self._reset_sync_button()
        QMessageBox.information(
            self, "同步完成",
            f"網站找到：{found} 筆\n"
            f"新增：{counts.get('new', 0)}，更新：{counts.get('updated', 0)}，"
            f"價格異動：{counts.get('price_changed', 0)}\n\n收藏、標籤與備註不會被覆蓋。",
        )

    def _on_sync_failed(self, message: str) -> None:
        self.status_label.setText("同步失敗，請檢查網址或網路。")
        self._reset_sync_button()
        QMessageBox.critical(self, "同步失敗", f"無法同步物件。\n\n錯誤內容：{message}")

    def _reset_sync_button(self) -> None:
        if self.runner is not None:
            self.runner.wait_and_cleanup()
        self.runner = None
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

    # ------------------------------------------------------------------
    # 2026-09-21 UX 重構：物件中心「安排發文」——一個對話框內完成，
    # 存檔後留在物件中心（不自動跳頁），只更新受影響的那一列。
    # ------------------------------------------------------------------

    def open_quick_schedule(self) -> None:
        row = self.selected()
        if not row:
            QMessageBox.information(self, "尚未選擇物件", "請先點選一筆物件。")
            return

        dialog = QuickScheduleDialog(self.db, int(row["id"]), parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        property_id = int(row["id"])
        self._refresh_schedule_status_for_property(property_id)

        if dialog.trigger_immediate_publish and dialog.created_schedule_id is not None:
            self._start_immediate_publish(dialog.created_schedule_id, property_id)
            return

        message = f"已建立排程\n{dialog.scheduled_at_display} 發布"
        if dialog.delete_at_display:
            message += f"\n{dialog.delete_at_display} 自動刪除"
        show_toast(
            self,
            message,
            kind="success",
            duration_ms=5000,
            action_text="查看排程",
            on_action=self._go_to_schedule_center,
        )

    def _go_to_schedule_center(self) -> None:
        if callable(self.go_schedule):
            self.go_schedule()

    def _start_immediate_publish(self, schedule_id: int, property_id: int) -> None:
        if self.publish_runner is not None:
            show_toast(self, "已建立排程，但目前已有其他貼文正在發布中，請稍後在排程中心手動發布。", kind="info", duration_ms=4000)
            return

        row = self.db.get_schedule(schedule_id)
        if not row:
            return

        self.db.mark_schedule_publishing(schedule_id)
        self._refresh_schedule_status_for_property(property_id)
        self.schedule_btn.setEnabled(False)
        self.status_label.setText(f"正在發布：{row.get('property_title', '')} ……")

        self.publish_runner = SchedulePublishRunner(self.db, dict(row))
        self.publish_runner.finished.connect(lambda payload: self._on_immediate_publish_finished(payload, property_id))
        self.publish_runner.failed.connect(lambda message: self._on_immediate_publish_failed(message, property_id))
        self.publish_runner.start()

    def _on_immediate_publish_finished(self, payload: dict, property_id: int) -> None:
        success = bool(payload.get("success"))
        message = str(payload.get("message", ""))
        if success:
            show_toast(
                self, "✓ 發布成功", kind="success",
                action_text="查看排程", on_action=self._go_to_schedule_center,
            )
        else:
            show_toast(self, f"發布失敗：{message}", kind="danger", duration_ms=4000)
        self._finish_immediate_publish(property_id)

    def _on_immediate_publish_failed(self, message: str, property_id: int) -> None:
        show_toast(self, f"發布發生錯誤：{message}", kind="danger", duration_ms=4000)
        self._finish_immediate_publish(property_id)

    def _finish_immediate_publish(self, property_id: int) -> None:
        if self.publish_runner is not None:
            self.publish_runner.wait_and_cleanup()
        self.publish_runner = None
        self.schedule_btn.setEnabled(True)
        self.status_label.setText("準備完成")
        self._refresh_schedule_status_for_property(property_id)