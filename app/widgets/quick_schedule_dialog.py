from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from PySide6.QtCore import QDateTime, Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from app.services import brand_profile
from app.services.content_safety import InternalMarkerDetectedError, assert_public_content_safe
from app.services.copywriting_engine import AJCopyEngine
from app.services.database import Database, local_str_plus, now_local_str
from app.widgets.common import ImagePreviewList, PropertySummaryCard, load_thumbnails_async
from app.widgets.schedule_dialog import DeleteRuleSelector, ScheduleTimePicker

# 2026-09-21 UX 重構：物件中心「安排發文」的快速排程視窗。跟既有的
# NewScheduleDialog（社團管理、待檢核流程）是兩條不同的路徑，不共用
# 同一個 class——這裡刻意省略社團多選＋待檢核審核步驟，目標是「一個
# 流程內完成」，不是取代既有的完整排程建立流程（排程管理頁面的
# 「＋新增排程」還是走 NewScheduleDialog，兩者都會建立同一張
# schedules table 的資料列，不影響 AutomationEngine 的撿取邏輯）。
_QUICK_DELETE_PRESET_DAYS = (1, 3, 7, 14, 30)


class QuickScheduleDialog(QDialog):
    """從物件中心一次完成：確認文案／圖片／發布位置／發布時間／自動刪除，
    存檔後不跳頁——呼叫端（PropertiesPage）自己決定要不要導去排程中心。

    這個 dialog 本身只負責寫入 schedules table（status='scheduled'，
    跳過 pending_review 審核——使用者已經在這個視窗裡親自確認過內容），
    不會自己觸發真正的 Facebook 發布。選「立即發布」時，只是把
    scheduled_at 設成現在，並且設定 self.trigger_immediate_publish=True
    讓呼叫端（PropertiesPage）自己啟動 SchedulePublishRunner——runner的
    生命週期要交給會一直存在的頁面物件管理，不能交給即將關閉的 dialog。
    """

    def __init__(self, db: Database, property_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self.property_id = property_id
        self.copy_engine = AJCopyEngine()
        self.image_paths: list[str] = []
        self.group_checks: list[tuple[QCheckBox, str]] = []
        self._thumb_signals = None  # 保留參照，避免背景解碼的 signal 提早被 GC

        self.created_schedule_id: int | None = None
        self.trigger_immediate_publish = False
        self.scheduled_at_display = ""
        self.delete_at_display = ""

        self.property_data = db.get_property(property_id) or {}

        self.setWindowTitle("安排發文")
        self.resize(760, 780)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        # ---- 物件 ----
        self.property_card = PropertySummaryCard()
        self.property_card.set_property(self.property_data)
        root.addWidget(self.property_card)

        # ---- 貼文內容 ----
        content_header = QHBoxLayout()
        content_header.addWidget(QLabel("貼文內容"))
        content_header.addStretch()
        self.char_count_label = QLabel("0 字")
        self.char_count_label.setObjectName("MutedLabel")
        content_header.addWidget(self.char_count_label)
        root.addLayout(content_header)

        self.content_editor = QPlainTextEdit()
        self.content_editor.setMinimumHeight(180)
        self.content_editor.textChanged.connect(self._update_char_count)
        root.addWidget(self.content_editor, 1)

        # ---- 圖片 ----
        root.addWidget(QLabel("圖片（勾選要發布的照片，可拖曳調整順序）"))
        self.image_status_label = QLabel("正在載入圖片…")
        self.image_status_label.setObjectName("MutedLabel")
        root.addWidget(self.image_status_label)

        self.preview_list = ImagePreviewList(self._image_order_changed)
        self.preview_list.setMinimumHeight(140)
        self.preview_list.setMaximumHeight(200)
        self.preview_list.itemChanged.connect(self._image_check_changed)
        root.addWidget(self.preview_list)

        # ---- 發布位置 ----
        target_box = QGroupBox("發布位置")
        target_layout = QVBoxLayout(target_box)
        self.publish_profile = QCheckBox("Facebook 個人動態")
        self.publish_profile.setChecked(True)
        target_layout.addWidget(self.publish_profile)

        groups = db.enabled_groups()
        for group in groups:
            name = str(group.get("name") or "未命名社團")
            url = str(group.get("url") or "").strip()
            if not url:
                continue
            checkbox = QCheckBox(name)
            checkbox.setToolTip(url)
            target_layout.addWidget(checkbox)
            self.group_checks.append((checkbox, url))
        root.addWidget(target_box)

        # ---- 發布時間 ----
        timing_box = QGroupBox("發布時間")
        timing_layout = QVBoxLayout(timing_box)

        self.timing_group = QButtonGroup(self)
        self.publish_now_radio = QRadioButton("立即發布")
        self.publish_later_radio = QRadioButton("排程發布")
        self.publish_later_radio.setChecked(True)
        self.timing_group.addButton(self.publish_now_radio)
        self.timing_group.addButton(self.publish_later_radio)
        timing_layout.addWidget(self.publish_now_radio)
        timing_layout.addWidget(self.publish_later_radio)

        self.time_picker = ScheduleTimePicker()
        timing_layout.addWidget(self.time_picker)

        self.publish_now_radio.toggled.connect(self._on_timing_mode_changed)
        self.time_picker.changed.connect(self._update_delete_preview)
        root.addWidget(timing_box)

        # ---- 自動刪除 ----
        delete_box = QGroupBox("自動刪除")
        delete_layout = QVBoxLayout(delete_box)
        self.delete_rule = DeleteRuleSelector(db, preset_days_options=_QUICK_DELETE_PRESET_DAYS)
        for radio, _days in self.delete_rule.radios:
            radio.toggled.connect(self._update_delete_preview)
        self.delete_rule.custom_radio.toggled.connect(self._update_delete_preview)
        self.delete_rule.custom_days.valueChanged.connect(self._update_delete_preview)
        delete_layout.addWidget(self.delete_rule)

        self.delete_preview_label = QLabel("")
        self.delete_preview_label.setObjectName("MutedLabel")
        delete_layout.addWidget(self.delete_preview_label)
        root.addWidget(delete_box)

        # ---- 按鈕 ----
        button_row = QHBoxLayout()
        cancel_button = QPushButton("取消")
        cancel_button.setObjectName("SecondaryButton")
        cancel_button.clicked.connect(self.reject)

        self.save_button = QPushButton("儲存排程")
        self.save_button.setObjectName("PrimaryButton")
        self.save_button.clicked.connect(self._save)

        button_row.addStretch()
        button_row.addWidget(cancel_button)
        button_row.addWidget(self.save_button)
        root.addLayout(button_row)

        self._load_content_and_images()
        self._on_timing_mode_changed()
        self._update_delete_preview()

    # ------------------------------------------------------------------

    def _load_content_and_images(self) -> None:
        profile = brand_profile.load_profile(self.db)
        content = self.copy_engine.generate(self.property_data, profile=profile)
        self.content_editor.setPlainText(content)

        image_paths_raw = str(self.property_data.get("image_paths", "")).strip()
        candidate_paths = [p for p in image_paths_raw.split("\n") if p.strip()]
        # 先用同步的 Path.exists() 過濾（純 I/O stat，跟解碼縮圖不是同一件
        # 事，成本很低），縮圖解碼本身才是真正需要移出主執行緒的部分。
        self.image_paths = [p for p in candidate_paths if Path(p).is_file()]

        self.preview_list.clear()
        if not self.image_paths:
            self.image_status_label.setText("此物件尚未同步照片")
            return

        self.image_status_label.setText(f"共 {len(self.image_paths)} 張，載入縮圖中…")
        for index, path in enumerate(self.image_paths):
            item = QListWidgetItem(f"{index + 1:02d}\n{Path(path).name}")
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.preview_list.addItem(item)

        self._thumb_signals = load_thumbnails_async(self.image_paths, self._on_thumbnail_ready)

    def _on_thumbnail_ready(self, path: str, icon) -> None:
        for index in range(self.preview_list.count()):
            item = self.preview_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == path:
                item.setIcon(icon)
        loaded = sum(1 for i in range(self.preview_list.count()) if not self.preview_list.item(i).icon().isNull())
        total = self.preview_list.count()
        if loaded >= total:
            checked = sum(
                1 for i in range(self.preview_list.count())
                if self.preview_list.item(i).checkState() == Qt.CheckState.Checked
            )
            self.image_status_label.setText(f"共 {total} 張，已選 {checked} 張")
        else:
            self.image_status_label.setText(f"共 {total} 張，載入縮圖中…（{loaded}/{total}）")

    def _image_check_changed(self, _item: QListWidgetItem) -> None:
        checked = sum(
            1 for i in range(self.preview_list.count())
            if self.preview_list.item(i).checkState() == Qt.CheckState.Checked
        )
        total = self.preview_list.count()
        self.image_status_label.setText(f"共 {total} 張，已選 {checked} 張")

    def _image_order_changed(self) -> None:
        pass  # 順序已經反映在 QListWidget 本身，_checked_image_paths() 直接讀取當下順序即可。

    def _checked_image_paths(self) -> list[str]:
        paths: list[str] = []
        for index in range(self.preview_list.count()):
            item = self.preview_list.item(index)
            if item.checkState() == Qt.CheckState.Checked:
                path = item.data(Qt.ItemDataRole.UserRole)
                if path:
                    paths.append(str(path))
        return paths

    def _update_char_count(self) -> None:
        self.char_count_label.setText(f"{len(self.content_editor.toPlainText())} 字")

    # ------------------------------------------------------------------

    def _on_timing_mode_changed(self, *_args) -> None:
        is_now = self.publish_now_radio.isChecked()
        self.time_picker.setVisible(not is_now)
        self.save_button.setText("立即發布" if is_now else "儲存排程")
        self._update_delete_preview()

    def _update_delete_preview(self, *_args) -> None:
        delete_days = self.delete_rule.value()
        if not delete_days:
            self.delete_preview_label.setText("不會自動刪除")
            return

        base = now_local_str() if self.publish_now_radio.isChecked() else self.time_picker.value_str()
        delete_at = local_str_plus(base, days=delete_days)
        try:
            display = QDateTime.fromString(delete_at, "yyyy-MM-dd HH:mm:ss").toString("yyyy/MM/dd HH:mm")
        except Exception:
            display = delete_at
        self.delete_preview_label.setText(f"預計刪除時間：{display}")

    def _get_targets(self) -> list[tuple[str, str]]:
        targets: list[tuple[str, str]] = []
        if self.publish_profile.isChecked():
            targets.append(("https://www.facebook.com/", "Facebook 個人動態"))
        for checkbox, url in self.group_checks:
            if checkbox.isChecked() and url:
                targets.append((url, checkbox.text()))
        return targets

    # ------------------------------------------------------------------

    def _save(self) -> None:
        content = self.content_editor.toPlainText().strip()
        if not content:
            QMessageBox.warning(self, "沒有內容", "請先確認貼文內容。")
            return

        try:
            assert_public_content_safe(content)
        except InternalMarkerDetectedError as exc:
            QMessageBox.critical(self, "內容含有內部標記", str(exc))
            return

        targets = self._get_targets()
        if not targets:
            QMessageBox.warning(self, "沒有發布位置", "請至少勾選一個發布位置。")
            return

        images = self._checked_image_paths()

        is_now = self.publish_now_radio.isChecked()
        if is_now:
            scheduled_at = now_local_str()
        else:
            if not self.time_picker.is_valid():
                QMessageBox.warning(self, "發布時間不正確", "發布時間不能早於目前時間。")
                return
            scheduled_at = self.time_picker.value_str()

        delete_after_days = self.delete_rule.value()
        batch_id = uuid.uuid4().hex

        first_id: int | None = None
        for target_url, target_label in targets:
            schedule_id = self.db.create_schedule(
                {
                    "property_id": self.property_id,
                    "platform": "facebook",
                    "target": target_url,
                    "target_label": target_label,
                    "copy_text": content,
                    "images": images,
                    "scheduled_at": scheduled_at,
                    "status": "scheduled",
                    "batch_id": batch_id,
                    "delete_after_days": delete_after_days,
                }
            )
            if first_id is None:
                first_id = schedule_id

        self.created_schedule_id = first_id
        self.trigger_immediate_publish = is_now
        try:
            self.scheduled_at_display = QDateTime.fromString(
                scheduled_at, "yyyy-MM-dd HH:mm:ss"
            ).toString("M/d HH:mm")
        except Exception:
            self.scheduled_at_display = scheduled_at
        if delete_after_days:
            delete_at = local_str_plus(scheduled_at, days=delete_after_days)
            try:
                self.delete_at_display = QDateTime.fromString(
                    delete_at, "yyyy-MM-dd HH:mm:ss"
                ).toString("M/d HH:mm")
            except Exception:
                self.delete_at_display = delete_at
        else:
            self.delete_at_display = ""

        self.accept()
