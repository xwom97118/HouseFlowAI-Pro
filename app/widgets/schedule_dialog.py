from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from PySide6.QtCore import QDate, QDateTime, QTime, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from app.services.copywriting_engine import AJCopyEngine
from app.services.database import Database
from app.widgets.common import ImagePreviewList, get_thumbnail_icon
from app.widgets.property_picker import PropertyPicker


class ScheduleTimePicker(QWidget):
    """發布日期＋時間選擇：QDateEdit + QTimeEdit + 快速按鈕，取代讓使用者
    自己輸入文字時間。預設「今天、目前時間 + 30 分鐘」；選到過去時間會
    立刻顯示警告，is_valid() 回傳 False 讓呼叫端擋下建立動作。
    """

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        row = QHBoxLayout()
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy/MM/dd")
        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm")
        row.addWidget(self.date_edit)
        row.addWidget(self.time_edit)
        row.addStretch()
        layout.addLayout(row)

        quick_row = QHBoxLayout()
        quick_row.setSpacing(6)
        for label, minutes in (("+10 分鐘", 10), ("+30 分鐘", 30), ("+1 小時", 60)):
            button = QPushButton(label)
            button.setObjectName("SecondaryButton")
            button.clicked.connect(lambda _=False, m=minutes: self._bump(m))
            quick_row.addWidget(button)

        today_button = QPushButton("今天")
        today_button.setObjectName("SecondaryButton")
        today_button.clicked.connect(lambda: self.date_edit.setDate(QDate.currentDate()))
        tomorrow_button = QPushButton("明天")
        tomorrow_button.setObjectName("SecondaryButton")
        tomorrow_button.clicked.connect(lambda: self.date_edit.setDate(QDate.currentDate().addDays(1)))
        quick_row.addWidget(today_button)
        quick_row.addWidget(tomorrow_button)
        quick_row.addStretch()
        layout.addLayout(quick_row)

        self.preview_label = QLabel()
        self.preview_label.setObjectName("Muted")
        layout.addWidget(self.preview_label)

        self.warning_label = QLabel()
        self.warning_label.setObjectName("WarningText")
        self.warning_label.setVisible(False)
        layout.addWidget(self.warning_label)

        self.date_edit.dateChanged.connect(self._refresh)
        self.time_edit.timeChanged.connect(self._refresh)

        self.set_default()

    def set_default(self) -> None:
        dt = QDateTime.currentDateTime().addSecs(30 * 60)
        self.date_edit.setDate(dt.date())
        self.time_edit.setTime(QTime(dt.time().hour(), dt.time().minute()))
        self._refresh()

    def _bump(self, minutes: int) -> None:
        dt = self.value().addSecs(minutes * 60)
        self.date_edit.setDate(dt.date())
        self.time_edit.setTime(dt.time())

    def value(self) -> QDateTime:
        return QDateTime(self.date_edit.date(), self.time_edit.time())

    def value_str(self) -> str:
        return self.value().toString("yyyy-MM-dd HH:mm:00")

    def is_valid(self) -> bool:
        return self.value() >= QDateTime.currentDateTime()

    def _refresh(self, *_args) -> None:
        dt = self.value()
        self.preview_label.setText(f"預計發布：{dt.toString('yyyy/MM/dd HH:mm')}")
        past = dt < QDateTime.currentDateTime()
        self.warning_label.setText("⚠ 發布時間不能早於目前時間" if past else "")
        self.warning_label.setVisible(past)
        self.changed.emit()


class DeleteRuleSelector(QWidget):
    """「自動刪除貼文」選項：不刪 / 1,3,7,15,30 天 / 自訂。兩個排程
    建立對話框（NewScheduleDialog、AddToScheduleDialog）共用同一份，
    避免各自兜一份不同的刪文規則 UI。
    """

    PRESET_DAYS = (1, 3, 7, 15, 30)
    _UNSET = object()

    def __init__(self, db: Database, preset_days: int | None = _UNSET) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.group = QButtonGroup(self)
        self.radios: list[tuple[QRadioButton, int | None]] = []

        if preset_days is self._UNSET:
            try:
                default_days = int(db.get_setting("automation_default_delete_days", "15") or 15)
            except ValueError:
                default_days = 15
        else:
            default_days = preset_days

        none_row = QHBoxLayout()
        none_radio = QRadioButton("不自動刪除")
        self.group.addButton(none_radio)
        self.radios.append((none_radio, None))
        none_row.addWidget(none_radio)
        none_row.addStretch()
        layout.addLayout(none_row)

        preset_row = QHBoxLayout()
        for days in self.PRESET_DAYS:
            radio = QRadioButton(f"發布後 {days} 天")
            self.group.addButton(radio)
            self.radios.append((radio, days))
            preset_row.addWidget(radio)
        layout.addLayout(preset_row)

        custom_row = QHBoxLayout()
        self.custom_radio = QRadioButton("自訂")
        self.group.addButton(self.custom_radio)
        self.custom_days = QSpinBox()
        self.custom_days.setRange(1, 365)
        self.custom_days.setSuffix(" 天")
        self.custom_days.setValue(default_days if default_days is not None else 15)
        custom_row.addWidget(self.custom_radio)
        custom_row.addWidget(self.custom_days)
        custom_row.addStretch()
        layout.addLayout(custom_row)

        matched = next((radio for radio, days in self.radios if days == default_days), None)
        if matched is not None:
            matched.setChecked(True)
        else:
            self.custom_radio.setChecked(True)

    def value(self) -> int | None:
        for radio, days in self.radios:
            if radio.isChecked():
                return days
        if self.custom_radio.isChecked():
            return self.custom_days.value()
        return None


class NewScheduleDialog(QDialog):
    """建立一筆或多筆（個人動態 + 多個社團）待檢核排程。"""

    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self.db = db
        self.copy_engine = AJCopyEngine()
        self.current_property_id: int | None = None
        self.image_paths: list[str] = []
        self.use_sync_images = True
        self.group_checks: list[tuple[QCheckBox, str]] = []
        self.created_count = 0

        self.setWindowTitle("新增排程")
        self.resize(820, 760)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        root.addWidget(QLabel("選擇物件"))
        self.property_picker = PropertyPicker()
        root.addWidget(self.property_picker)

        root.addWidget(QLabel("貼文內容"))
        self.content_editor = QPlainTextEdit()
        self.content_editor.setPlaceholderText("選擇物件後會自動產生文案草稿，也可以自行編輯。")
        root.addWidget(self.content_editor, 1)

        image_row = QHBoxLayout()
        self.image_label = QLabel("尚未選擇圖片")
        self.image_label.setObjectName("MutedLabel")
        self.use_sync_checkbox = QCheckBox("使用同步照片")
        self.use_sync_checkbox.setChecked(True)
        self.use_sync_checkbox.toggled.connect(self.sync_image_mode_changed)

        choose_images_button = QPushButton("選擇圖片")
        choose_images_button.setObjectName("SecondaryButton")
        choose_images_button.clicked.connect(self.choose_images)

        clear_images_button = QPushButton("清除圖片")
        clear_images_button.setObjectName("SecondaryButton")
        clear_images_button.clicked.connect(self.clear_images)

        image_row.addWidget(self.use_sync_checkbox)
        image_row.addWidget(self.image_label, 1)
        image_row.addWidget(choose_images_button)
        image_row.addWidget(clear_images_button)
        root.addLayout(image_row)

        self.preview_list = ImagePreviewList(self.image_order_changed)
        self.preview_list.setMinimumHeight(150)
        self.preview_list.setMaximumHeight(220)
        root.addWidget(self.preview_list)

        target_box = QGroupBox("發布位置（會各自建立一筆排程）")
        target_layout = QVBoxLayout(target_box)

        self.publish_profile = QCheckBox("Facebook 個人動態")
        target_layout.addWidget(self.publish_profile)

        self.groups_container = QWidget()
        self.groups_layout = QVBoxLayout(self.groups_container)
        self.groups_layout.setContentsMargins(4, 4, 4, 4)
        self.groups_layout.setSpacing(6)

        groups_scroll = QScrollArea()
        groups_scroll.setWidgetResizable(True)
        groups_scroll.setMaximumHeight(140)
        groups_scroll.setWidget(self.groups_container)
        target_layout.addWidget(groups_scroll)

        root.addWidget(target_box)

        root.addWidget(QLabel("預定發布時間"))
        self.time_picker = ScheduleTimePicker()
        root.addWidget(self.time_picker)

        root.addWidget(QLabel("自動刪除貼文"))
        self.delete_rule = DeleteRuleSelector(db)
        root.addWidget(self.delete_rule)

        button_row = QHBoxLayout()
        cancel_button = QPushButton("取消")
        cancel_button.setObjectName("SecondaryButton")
        cancel_button.clicked.connect(self.reject)

        create_button = QPushButton("建立排程（送出待檢核）")
        create_button.setObjectName("PrimaryButton")
        create_button.clicked.connect(self.create_schedules)

        button_row.addStretch()
        button_row.addWidget(cancel_button)
        button_row.addWidget(create_button)
        root.addLayout(button_row)

        self.reload_groups()

        # 所有會被 property_changed / sync_image_mode_changed 用到的
        # widget 都已經建立完成，這時候才連上信號、載入物件清單 ——
        # set_properties() 可能會立刻 emit property_selected，太早連線
        # 會在 UI 還沒蓋好前就觸發 slot。
        self.property_picker.property_selected.connect(self.property_changed)
        self.property_picker.set_properties(db.list_properties())

    def reload_groups(self) -> None:
        while self.groups_layout.count():
            item = self.groups_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.group_checks.clear()
        groups = self.db.enabled_groups()

        if not groups:
            empty_label = QLabel("尚未建立社團。可以只發布到個人動態，或先到「社團管理」新增社團。")
            empty_label.setObjectName("MutedLabel")
            self.groups_layout.addWidget(empty_label)
            self.groups_layout.addStretch()
            return

        for group in groups:
            name = str(group.get("name") or "未命名社團")
            url = str(group.get("url") or "").strip()
            if not url:
                continue
            checkbox = QCheckBox(name)
            checkbox.setToolTip(url)
            self.groups_layout.addWidget(checkbox)
            self.group_checks.append((checkbox, url))

        self.groups_layout.addStretch()

    def property_changed(self, property_id: int | None = None) -> None:
        if property_id is None:
            property_id = self.property_picker.current_property_id()
        if property_id is None:
            self.current_property_id = None
            return

        self.current_property_id = int(property_id)
        property_data = self.db.get_property(self.current_property_id)
        if not property_data:
            return

        profile = {
            "brand_slogan": self.db.get_setting("brand_slogan", ""),
            "default_cta": self.db.get_setting("default_cta", ""),
            "default_hashtags": self.db.get_setting("default_hashtags", ""),
        }
        content = self.copy_engine.generate(property_data, profile=profile)
        self.content_editor.setPlainText(content)

        if self.use_sync_images:
            image_paths = str(property_data.get("image_paths", "")).strip()
            self.image_paths = [
                path for path in image_paths.split("\n") if path and Path(path).exists()
            ]
            self.refresh_image_preview()

    def sync_image_mode_changed(self, checked: bool) -> None:
        self.use_sync_images = checked
        if checked:
            self.property_changed()
        else:
            self.refresh_image_preview()

    def choose_images(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "選擇排程圖片", "", "圖片檔案 (*.jpg *.jpeg *.png *.webp)"
        )
        if not paths:
            return
        self.image_paths = paths
        self.refresh_image_preview()

    def clear_images(self) -> None:
        self.image_paths = []
        self.refresh_image_preview()

    def refresh_image_preview(self) -> None:
        self.preview_list.clear()
        valid_paths = [
            str(Path(path).resolve()) for path in self.image_paths if Path(path).is_file()
        ]
        self.image_paths = valid_paths

        if not self.image_paths:
            self.image_label.setText("尚未選擇圖片")
            return

        from PySide6.QtWidgets import QListWidgetItem

        for index, image_path in enumerate(self.image_paths):
            icon = get_thumbnail_icon(image_path)
            prefix = "★ 封面" if index == 0 else f"{index + 1:02d}"
            item = QListWidgetItem(icon, f"{prefix}\n{Path(image_path).name}")
            item.setData(Qt.ItemDataRole.UserRole, image_path)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.preview_list.addItem(item)

        self.image_label.setText(f"目前共 {len(self.image_paths)} 張照片")

    def image_order_changed(self) -> None:
        ordered_paths: list[str] = []
        for index in range(self.preview_list.count()):
            item = self.preview_list.item(index)
            path = item.data(Qt.ItemDataRole.UserRole)
            if path:
                ordered_paths.append(str(path))
        if ordered_paths:
            self.image_paths = ordered_paths
            self.refresh_image_preview()

    def get_targets(self) -> list[tuple[str, str]]:
        targets: list[tuple[str, str]] = []
        if self.publish_profile.isChecked():
            targets.append(("https://www.facebook.com/", "Facebook 個人動態"))
        for checkbox, url in self.group_checks:
            if checkbox.isChecked() and url:
                targets.append((url, checkbox.text()))
        return targets

    def create_schedules(self) -> None:
        if self.current_property_id is None:
            QMessageBox.warning(self, "尚未選擇物件", "請先選擇一筆物件。")
            return

        content = self.content_editor.toPlainText().strip()
        if not content:
            QMessageBox.warning(self, "沒有內容", "請先輸入或確認貼文內容。")
            return

        targets = self.get_targets()
        if not targets:
            QMessageBox.warning(self, "沒有發布位置", "請勾選個人動態或至少一個社團。")
            return

        if not self.time_picker.is_valid():
            QMessageBox.warning(self, "發布時間不正確", "發布時間不能早於目前時間。")
            return

        scheduled_at = self.time_picker.value_str()
        delete_after_days = self.delete_rule.value()
        batch_id = uuid.uuid4().hex

        for target_url, target_label in targets:
            self.db.create_schedule(
                {
                    "property_id": self.current_property_id,
                    "platform": "facebook",
                    "target": target_url,
                    "target_label": target_label,
                    "copy_text": content,
                    "images": self.image_paths,
                    "scheduled_at": scheduled_at,
                    "status": "pending_review",
                    "batch_id": batch_id,
                    "delete_after_days": delete_after_days,
                }
            )

        self.created_count = len(targets)
        QMessageBox.information(
            self, "已建立排程", f"已建立 {self.created_count} 筆待檢核排程，可以到排程中心核准。"
        )
        self.accept()
