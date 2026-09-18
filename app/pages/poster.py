from __future__ import annotations

import uuid
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.services import brand_profile
from app.services.database import Database
from app.services.facebook_service import FacebookService
from app.services.copywriting_engine import AJCopyEngine
from app.services.schedule_runner import AdHocPublishRunner
from app.widgets.property_picker import PropertyPicker
from app.widgets.common import ImagePreviewList, PropertySummaryCard, SectionTitle, get_thumbnail_icon, show_toast
from app.widgets.schedule_dialog import DeleteRuleSelector, ScheduleTimePicker

COPY_STYLES = ["親切自然", "專業分析", "成交導向", "簡短直接", "短影音口吻"]


class PosterPage(QWidget):
    def __init__(
        self,
        db: Database,
        navigate,
        on_scheduled: Callable[[str, int], None] | None = None,
    ) -> None:
        super().__init__()

        self.db = db
        self.navigate = navigate
        self.on_scheduled = on_scheduled
        self.facebook = FacebookService()
        self.copy_engine = AJCopyEngine()
        self.current_property_id: int | None = None
        self.image_paths: list[str] = []
        self.use_sync_images = True
        self.group_checks: list[tuple[QCheckBox, str]] = []
        self.publish_runner: AdHocPublishRunner | None = None

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(scroll, 1)

        content = QWidget()
        scroll.setWidget(content)

        root = QVBoxLayout(content)
        root.setContentsMargins(24, 22, 24, 16)
        root.setSpacing(14)

        header = QHBoxLayout()

        back_button = QPushButton("← 返回 Dashboard")
        back_button.setObjectName("SecondaryButton")
        back_button.clicked.connect(lambda _=False: self.navigate("dashboard"))

        self.login_button = QPushButton("登入 Facebook")
        self.login_button.setObjectName("SecondaryButton")
        self.login_button.clicked.connect(self.login_facebook)

        header.addWidget(back_button)
        header.addStretch()
        header.addWidget(self.login_button)
        root.addLayout(header)

        root.addWidget(
            SectionTitle(
                "Facebook 發文中心",
                "依照步驟選擇物件、確認文案與圖片，再排程或發布。",
            )
        )

        # STEP 1：選擇物件 ------------------------------------------------
        step1 = self._step_card("STEP 1", "選擇物件")
        step1_layout = step1.layout()

        self.property_picker = PropertyPicker()
        self.property_picker.property_selected.connect(self.property_changed)
        step1_layout.addWidget(self.property_picker)

        self.property_summary = PropertySummaryCard()
        step1_layout.addWidget(self.property_summary)

        root.addWidget(step1)

        # STEP 2：編輯文案 ------------------------------------------------
        step2 = self._step_card("STEP 2", "編輯文案")
        step2_layout = step2.layout()

        content_toolbar = QHBoxLayout()
        content_toolbar.addStretch()

        generate_button = QPushButton("產生文案")
        generate_button.setObjectName("SecondaryButton")
        generate_button.clicked.connect(self.generate_content)

        template_button = QPushButton("套用模板")
        template_button.setObjectName("SecondaryButton")
        template_button.clicked.connect(self.apply_template)

        insert_compliance_button = QPushButton("插入經紀業資訊")
        insert_compliance_button.setObjectName("SecondaryButton")
        insert_compliance_button.clicked.connect(self.insert_compliance_footer)

        clear_content_button = QPushButton("清空")
        clear_content_button.setObjectName("SecondaryButton")
        clear_content_button.clicked.connect(self.clear_content)

        content_toolbar.addWidget(generate_button)
        content_toolbar.addWidget(template_button)
        content_toolbar.addWidget(insert_compliance_button)
        content_toolbar.addWidget(clear_content_button)
        step2_layout.addLayout(content_toolbar)

        self.content_editor = QPlainTextEdit()
        self.content_editor.setPlaceholderText("請輸入要發布的 Facebook 文案……")
        self.content_editor.setMinimumHeight(220)
        self.content_editor.textChanged.connect(self._update_char_count)
        step2_layout.addWidget(self.content_editor)

        content_footer = QHBoxLayout()
        self.char_count_label = QLabel("字數：0")
        self.char_count_label.setObjectName("Muted")
        compliance_hint = QLabel("經紀業資訊會依設定自動加入。")
        compliance_hint.setObjectName("Muted")
        content_footer.addWidget(self.char_count_label)
        content_footer.addStretch()
        content_footer.addWidget(compliance_hint)
        step2_layout.addLayout(content_footer)

        root.addWidget(step2)

        # STEP 3：選擇圖片 ------------------------------------------------
        step3 = self._step_card("STEP 3", "選擇圖片")
        step3_layout = step3.layout()

        image_row = QHBoxLayout()

        self.image_label = QLabel("尚未選擇圖片")
        self.image_label.setObjectName("Muted")
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
        step3_layout.addLayout(image_row)

        preview_hint = QLabel("圖片可拖曳排序；雙擊放大；右鍵可設為封面或移除。")
        preview_hint.setObjectName("Muted")
        step3_layout.addWidget(preview_hint)

        self.preview_list = ImagePreviewList(self.image_order_changed)
        self.preview_list.setMinimumHeight(190)
        self.preview_list.setMaximumHeight(320)
        self.preview_list.itemDoubleClicked.connect(self.open_image_preview)
        self.preview_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.preview_list.customContextMenuRequested.connect(self.show_image_menu)
        step3_layout.addWidget(self.preview_list)

        root.addWidget(step3)

        # STEP 4：選擇發布位置 --------------------------------------------
        step4 = self._step_card("STEP 4", "選擇發布位置")
        step4_layout = step4.layout()

        self.publish_profile = QCheckBox("Facebook 個人動態")
        self.publish_profile.toggled.connect(self._update_target_summary)
        step4_layout.addWidget(self.publish_profile)

        group_header = QHBoxLayout()
        group_header.addWidget(QLabel("已儲存的 Facebook 社團"))
        group_header.addStretch()

        select_all_button = QPushButton("全選社團")
        select_all_button.setObjectName("SecondaryButton")
        select_all_button.clicked.connect(self.select_all_groups)

        clear_all_button = QPushButton("取消全選")
        clear_all_button.setObjectName("SecondaryButton")
        clear_all_button.clicked.connect(self.clear_all_groups)

        refresh_groups_button = QPushButton("重新載入社團")
        refresh_groups_button.setObjectName("SecondaryButton")
        refresh_groups_button.clicked.connect(self.reload_groups)

        group_header.addWidget(select_all_button)
        group_header.addWidget(clear_all_button)
        group_header.addWidget(refresh_groups_button)
        step4_layout.addLayout(group_header)

        self.groups_container = QWidget()
        self.groups_layout = QVBoxLayout(self.groups_container)
        self.groups_layout.setContentsMargins(4, 4, 4, 4)
        self.groups_layout.setSpacing(6)

        self.groups_scroll = QScrollArea()
        self.groups_scroll.setWidgetResizable(True)
        self.groups_scroll.setMaximumHeight(160)
        self.groups_scroll.setWidget(self.groups_container)
        step4_layout.addWidget(self.groups_scroll)

        self.target_summary_label = QLabel("已選擇 0 個發布位置")
        self.target_summary_label.setObjectName("Muted")
        step4_layout.addWidget(self.target_summary_label)

        root.addWidget(step4)

        utility_row = QHBoxLayout()
        reload_button = QPushButton("重新載入物件")
        reload_button.setObjectName("SecondaryButton")
        reload_button.clicked.connect(self.reload_properties)

        copy_button = QPushButton("複製文案")
        copy_button.setObjectName("SecondaryButton")
        copy_button.clicked.connect(self.copy_content)
        utility_row.addWidget(reload_button)
        utility_row.addWidget(copy_button)
        utility_row.addStretch()
        root.addLayout(utility_row)

        # STEP 5：發布方式 --------------------------------------------------
        step5 = self._step_card("STEP 5", "發布方式")
        step5_layout = step5.layout()

        self.mode_group = QButtonGroup(self)
        self.mode_immediate = QRadioButton("立即發布")
        self.mode_schedule = QRadioButton("加入排程")
        self.mode_schedule.setChecked(True)  # HouseFlow 主要工作流程是自動排程，預設選它
        self.mode_group.addButton(self.mode_immediate)
        self.mode_group.addButton(self.mode_schedule)
        self.mode_immediate.toggled.connect(self._update_cta_mode)

        mode_row = QHBoxLayout()
        mode_row.addWidget(self.mode_immediate)
        mode_row.addWidget(self.mode_schedule)
        mode_row.addStretch()
        step5_layout.addLayout(mode_row)

        self.immediate_panel = QFrame()
        immediate_layout = QVBoxLayout(self.immediate_panel)
        immediate_layout.setContentsMargins(0, 4, 0, 0)
        immediate_hint = QLabel("確認後 HouseFlow 會自動操作 Facebook 完成發布，過程中請勿關閉瀏覽器視窗。")
        immediate_hint.setObjectName("Muted")
        immediate_hint.setWordWrap(True)
        immediate_layout.addWidget(immediate_hint)
        step5_layout.addWidget(self.immediate_panel)

        self.schedule_panel = QFrame()
        schedule_panel_layout = QVBoxLayout(self.schedule_panel)
        schedule_panel_layout.setContentsMargins(0, 4, 0, 0)
        schedule_panel_layout.setSpacing(10)

        schedule_panel_layout.addWidget(QLabel("發布時間"))
        self.time_picker = ScheduleTimePicker()
        schedule_panel_layout.addWidget(self.time_picker)

        schedule_panel_layout.addWidget(QLabel("自動刪除貼文"))
        self.delete_rule = DeleteRuleSelector(db)
        schedule_panel_layout.addWidget(self.delete_rule)

        step5_layout.addWidget(self.schedule_panel)

        root.addWidget(step5)
        root.addStretch()

        # 主要操作（固定在畫面底部，不隨內容捲動）：同一時間只有一個主要 CTA -----
        cta_bar = QFrame()
        cta_bar.setObjectName("CtaBar")
        cta_layout = QHBoxLayout(cta_bar)
        cta_layout.setContentsMargins(24, 12, 24, 12)

        self.status_label = QLabel("請先登入 Facebook，再選擇發布位置。")
        self.status_label.setObjectName("Muted")
        cta_layout.addWidget(self.status_label, 1)

        draft_button = QPushButton("儲存草稿")
        draft_button.setObjectName("SecondaryButton")
        draft_button.clicked.connect(self.save_draft)

        preview_button = QPushButton("預覽貼文")
        preview_button.setObjectName("SecondaryButton")
        preview_button.clicked.connect(self.preview_post)

        self.primary_cta_button = QPushButton("加入排程")
        self.primary_cta_button.setObjectName("PrimaryButton")
        self.primary_cta_button.clicked.connect(self._on_primary_cta_clicked)

        cta_layout.addWidget(draft_button)
        cta_layout.addWidget(preview_button)
        cta_layout.addWidget(self.primary_cta_button)

        outer.addWidget(cta_bar)

        self._update_cta_mode()
        self.reload_properties()
        self.reload_groups()
        self.refresh_image_preview()
        self._update_char_count()
        self._update_target_summary()

    @staticmethod
    def _step_card(step: str, title: str) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        badge = QLabel(step)
        badge.setObjectName("StepBadge")
        title_label = QLabel(title)
        title_label.setObjectName("StepTitle")
        header.addWidget(badge)
        header.addWidget(title_label)
        header.addStretch()
        layout.addLayout(header)

        return card

    # ------------------------------------------------------------------
    # 圖片
    # ------------------------------------------------------------------

    def choose_images(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "選擇 Facebook 貼文圖片",
            "",
            "圖片檔案 (*.jpg *.jpeg *.png *.webp)",
        )

        if not paths:
            return

        self.image_paths = paths
        names = [Path(path).name for path in paths]

        self.image_label.setText(
            f"已選擇 {len(paths)} 張："
            + "、".join(names[:3])
            + ("…" if len(names) > 3 else "")
        )
        self.refresh_image_preview()

    def clear_images(self) -> None:
        self.image_paths = []
        self.image_label.setText("尚未選擇圖片")
        self.refresh_image_preview()

    def refresh_image_preview(self) -> None:
        self.preview_list.clear()

        valid_paths = [
            str(Path(path).resolve())
            for path in self.image_paths
            if Path(path).is_file()
        ]

        self.image_paths = valid_paths

        if not self.image_paths:
            item = QListWidgetItem("目前沒有可預覽的圖片")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.preview_list.addItem(item)
            return

        for index, image_path in enumerate(self.image_paths):
            icon = get_thumbnail_icon(image_path)

            prefix = "★ 封面" if index == 0 else f"{index + 1:02d}"
            item = QListWidgetItem(icon, f"{prefix}\n{Path(image_path).name}")
            item.setData(Qt.ItemDataRole.UserRole, image_path)
            item.setToolTip(image_path)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsDragEnabled
                | Qt.ItemFlag.ItemIsDropEnabled
            )

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
            self.status_label.setText("圖片順序已更新，Facebook 將依此順序上傳。")

    def open_image_preview(self, item: QListWidgetItem) -> None:
        image_path = item.data(Qt.ItemDataRole.UserRole)

        if not image_path:
            return

        pixmap = QPixmap(str(image_path))

        if pixmap.isNull():
            QMessageBox.warning(self, "無法開啟圖片", "這張圖片無法載入。")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(Path(str(image_path)).name)
        dialog.resize(1000, 760)

        layout = QVBoxLayout(dialog)

        image_label = QLabel()
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        scaled = pixmap.scaled(
            940, 680,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        image_label.setPixmap(scaled)

        close_button = QPushButton("關閉")
        close_button.setObjectName("SecondaryButton")
        close_button.clicked.connect(dialog.accept)

        layout.addWidget(image_label, 1)
        layout.addWidget(close_button)

        dialog.exec()

    def show_image_menu(self, position) -> None:
        item = self.preview_list.itemAt(position)

        if item is None:
            return

        image_path = item.data(Qt.ItemDataRole.UserRole)

        if not image_path:
            return

        menu = QMenu(self)

        cover_action = menu.addAction("★ 設為封面")
        preview_action = menu.addAction("放大預覽")
        menu.addSeparator()
        remove_action = menu.addAction("移除這張圖片")

        selected = menu.exec(self.preview_list.mapToGlobal(position))

        if selected == cover_action:
            self.set_cover_image(str(image_path))
        elif selected == preview_action:
            self.open_image_preview(item)
        elif selected == remove_action:
            self.remove_image(str(image_path))

    def set_cover_image(self, image_path: str) -> None:
        if image_path not in self.image_paths:
            return

        self.image_paths.remove(image_path)
        self.image_paths.insert(0, image_path)
        self.refresh_image_preview()

        self.status_label.setText(f"已將 {Path(image_path).name} 設為封面。")

    def remove_image(self, image_path: str) -> None:
        if image_path not in self.image_paths:
            return

        answer = QMessageBox.question(
            self,
            "移除圖片",
            f"確定不發布這張圖片嗎？\n{Path(image_path).name}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        self.image_paths.remove(image_path)
        self.refresh_image_preview()

        self.status_label.setText(f"已移除 {Path(image_path).name}，原始檔案沒有被刪除。")

    def sync_image_mode_changed(self, checked: bool) -> None:
        self.use_sync_images = checked

        if checked:
            self.property_changed()
        else:
            self.refresh_image_preview()

    # ------------------------------------------------------------------
    # 物件 / 社團
    # ------------------------------------------------------------------

    def reload_properties(self) -> None:
        current_id = self.current_property_id or self.property_picker.current_property_id()
        rows = self.db.list_properties()
        self.property_picker.set_properties(rows, selected_id=current_id)

    def reload_groups(self) -> None:
        selected_urls = {url for checkbox, url in self.group_checks if checkbox.isChecked()}

        while self.groups_layout.count():
            item = self.groups_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.group_checks.clear()
        groups = self.db.enabled_groups()

        if not groups:
            empty_label = QLabel("尚未建立社團。請先到「社團管理」新增常用社團。")
            empty_label.setObjectName("Muted")
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
            checkbox.setChecked(url in selected_urls)
            checkbox.toggled.connect(self._update_target_summary)

            self.groups_layout.addWidget(checkbox)
            self.group_checks.append((checkbox, url))

        self.groups_layout.addStretch()
        self._update_target_summary()

    def select_all_groups(self) -> None:
        for checkbox, _ in self.group_checks:
            checkbox.setChecked(True)

    def clear_all_groups(self) -> None:
        for checkbox, _ in self.group_checks:
            checkbox.setChecked(False)

    def _update_target_summary(self, *_args) -> None:
        count = len(self.get_targets())
        self.target_summary_label.setText(f"已選擇 {count} 個發布位置")

    def _update_char_count(self) -> None:
        length = len(self.content_editor.toPlainText())
        self.char_count_label.setText(f"字數：{length}")

    def property_changed(self, property_id: int | None = None) -> None:
        if property_id is None:
            property_id = self.property_picker.current_property_id()

        if property_id is None:
            self.current_property_id = None
            self.content_editor.clear()
            self.image_paths = []
            self.property_summary.set_property(None)
            self.refresh_image_preview()
            return

        self.current_property_id = int(property_id)

        property_data = self.db.get_property(self.current_property_id)

        if not property_data:
            self.content_editor.clear()
            self.property_summary.set_property(None)
            return

        self.property_summary.set_property(property_data)

        profile = brand_profile.load_profile(self.db)
        content = self.copy_engine.generate(property_data, profile=profile)
        self.content_editor.setPlainText(content)

        if self.use_sync_images:
            image_paths = str(property_data.get("image_paths", "")).strip()

            self.image_paths = [
                path for path in image_paths.split("\n") if path and Path(path).exists()
            ]

            if self.image_paths:
                self.image_label.setText(f"已同步 {len(self.image_paths)} 張照片")
            else:
                self.image_label.setText("此物件尚未同步照片")

            self.refresh_image_preview()

    # ------------------------------------------------------------------
    # 文案工具列
    # ------------------------------------------------------------------

    def generate_content(self) -> None:
        if self.current_property_id is None:
            QMessageBox.information(self, "尚未選擇物件", "請先選擇一筆物件。")
            return
        self.property_changed(self.current_property_id)
        self.status_label.setText("已重新產生文案。")

    def apply_template(self) -> None:
        if self.current_property_id is None:
            QMessageBox.information(self, "尚未選擇物件", "請先選擇一筆物件。")
            return

        menu = QMenu(self)
        actions = {menu.addAction(style): style for style in COPY_STYLES}
        selected = menu.exec(QGuiApplication.instance().primaryScreen().availableGeometry().center())
        chosen_style = actions.get(selected)
        if not chosen_style:
            return

        self.db.set_setting("copy_style", chosen_style)
        property_data = self.db.get_property(self.current_property_id)
        if not property_data:
            return

        profile = brand_profile.load_profile(self.db)
        content = self.copy_engine.generate(property_data, profile=profile, style=chosen_style)
        self.content_editor.setPlainText(content)
        self.status_label.setText(f"已套用「{chosen_style}」模板。")

    def insert_compliance_footer(self) -> None:
        profile = brand_profile.load_profile(self.db)

        if not brand_profile.is_compliance_complete(profile):
            missing = "、".join(brand_profile.missing_compliance_labels(profile))
            self._prompt_missing_compliance(missing)
            return

        current_text = self.content_editor.toPlainText()
        updated = brand_profile.insert_or_replace_compliance_footer(current_text, profile)
        self.content_editor.setPlainText(updated)
        self.status_label.setText("已插入（或更新）經紀業合規資訊。")

    def clear_content(self) -> None:
        answer = QMessageBox.question(self, "清空文案", "確定要清空目前的貼文內容嗎？")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.content_editor.clear()

    def login_facebook(self) -> None:
        self.login_button.setEnabled(False)
        self.status_label.setText("正在開啟 Facebook……")
        QApplication.processEvents()

        try:
            self.facebook.open_login()
            self.status_label.setText("Facebook 視窗已關閉，登入狀態已保存。")
        except Exception as exc:
            QMessageBox.critical(self, "Facebook 開啟失敗", str(exc))
            self.status_label.setText("Facebook 開啟失敗。")
        finally:
            self.login_button.setEnabled(True)

    def copy_content(self) -> None:
        content = self.content_editor.toPlainText().strip()

        if not content:
            QMessageBox.warning(self, "沒有內容", "請先輸入貼文內容。")
            return

        QGuiApplication.clipboard().setText(content)
        self.status_label.setText("貼文內容已複製。")

    def preview_post(self) -> None:
        content = self.content_editor.toPlainText().strip()
        targets = self.get_targets()

        if not content:
            QMessageBox.warning(self, "沒有內容", "請先輸入貼文內容。")
            return

        if not targets:
            QMessageBox.warning(self, "沒有發布位置", "請勾選個人動態或至少一個社團。")
            return

        selected_group_count = sum(1 for checkbox, _ in self.group_checks if checkbox.isChecked())

        QMessageBox.information(
            self,
            "發布前確認",
            f"發布位置：{len(targets)} 個\n"
            f"其中社團：{selected_group_count} 個\n"
            f"圖片：{len(self.image_paths)} 張\n\n"
            f"{content[:700]}",
        )

    def get_targets(self) -> list[str]:
        targets: list[str] = []

        if self.publish_profile.isChecked():
            targets.append("https://www.facebook.com/")

        for checkbox, url in self.group_checks:
            if checkbox.isChecked() and url:
                targets.append(url)

        return targets

    def get_target_pairs(self) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        if self.publish_profile.isChecked():
            pairs.append(("https://www.facebook.com/", "Facebook 個人動態"))
        for checkbox, url in self.group_checks:
            if checkbox.isChecked() and url:
                pairs.append((url, checkbox.text()))
        return pairs

    # ------------------------------------------------------------------
    # 經紀業合規檢查
    # ------------------------------------------------------------------

    def _prompt_missing_compliance(self, missing_text: str) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("尚未完成經紀業資訊設定")
        box.setText("尚未完成經紀業資訊設定")
        box.setInformativeText(f"缺少：{missing_text}\n\n請先到「設定」完成經紀業資訊，才能發布物件貼文。")
        go_settings = box.addButton("前往設定", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() == go_settings:
            self.navigate("settings")

    def _check_compliance_before_publish(self) -> bool:
        """回傳 True 代表可以繼續（經紀業資訊完整）。"""
        profile = brand_profile.load_profile(self.db)
        if brand_profile.is_compliance_complete(profile):
            return True
        missing = "、".join(brand_profile.missing_compliance_labels(profile))
        self._prompt_missing_compliance(missing)
        return False

    # ------------------------------------------------------------------
    # 草稿 / 排程 / 發布
    # ------------------------------------------------------------------

    def save_draft(self) -> None:
        if self.current_property_id is None:
            QMessageBox.information(self, "尚未選擇物件", "請先選擇一筆物件。")
            return

        content = self.content_editor.toPlainText().strip()
        targets = self.get_target_pairs()

        if not content:
            QMessageBox.warning(self, "沒有內容", "請先輸入貼文內容。")
            return

        if not targets:
            QMessageBox.warning(self, "沒有發布位置", "請勾選個人動態或至少一個社團。")
            return

        for target_url, target_label in targets:
            self.db.create_schedule(
                {
                    "property_id": self.current_property_id,
                    "platform": "facebook",
                    "target": target_url,
                    "target_label": target_label,
                    "copy_text": content,
                    "images": self.image_paths,
                    "scheduled_at": "",
                    "status": "draft",
                }
            )

        show_toast(self, f"✓ 已儲存 {len(targets)} 筆草稿", kind="success")
        self.status_label.setText(f"已儲存 {len(targets)} 筆草稿，可以到「排程管理」繼續編輯。")

    # ------------------------------------------------------------------
    # STEP 5：發布方式（立即發布 / 加入排程，同一時間只有一個主要 CTA）
    # ------------------------------------------------------------------

    def _update_cta_mode(self, *_args) -> None:
        immediate = self.mode_immediate.isChecked()
        self.immediate_panel.setVisible(immediate)
        self.schedule_panel.setVisible(not immediate)
        self.primary_cta_button.setText("確認立即發布" if immediate else "加入排程")
        self.primary_cta_button.setObjectName("SuccessButton" if immediate else "PrimaryButton")
        style = self.primary_cta_button.style()
        if style is not None:
            style.unpolish(self.primary_cta_button)
            style.polish(self.primary_cta_button)

    def _on_primary_cta_clicked(self) -> None:
        if self.mode_immediate.isChecked():
            self._do_immediate_publish()
        else:
            self._do_add_to_schedule()

    def _validate_common(self) -> tuple[str, list[tuple[str, str]]] | None:
        if self.current_property_id is None:
            QMessageBox.information(self, "尚未選擇物件", "請先選擇一筆物件。")
            return None

        content = self.content_editor.toPlainText().strip()
        targets = self.get_target_pairs()

        if not content:
            QMessageBox.warning(self, "沒有內容", "請先輸入貼文內容。")
            return None

        if not targets:
            QMessageBox.warning(self, "沒有發布位置", "請勾選個人動態或至少一個社團。")
            return None

        if not self._check_compliance_before_publish():
            return None

        return content, targets

    def _do_add_to_schedule(self) -> None:
        validated = self._validate_common()
        if validated is None:
            return
        content, targets = validated

        if not self.time_picker.is_valid():
            QMessageBox.warning(self, "發布時間不正確", "發布時間不能早於目前時間。")
            return

        # 立即給回饋：按下去馬上看到「建立中…」，不用等整頁 refresh 才知道有沒有反應。
        self.primary_cta_button.setEnabled(False)
        self.primary_cta_button.setText("建立中…")
        QApplication.processEvents()

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

        created_count = len(targets)
        self.primary_cta_button.setEnabled(True)
        self._update_cta_mode()

        show_toast(self, f"✓ 已加入排程：{created_count} 筆，等待核准", kind="success")
        self.status_label.setText(f"已加入排程：{created_count} 筆，已導向排程中心。")

        if callable(self.on_scheduled):
            self.on_scheduled(batch_id, created_count)
        else:
            self.navigate("schedule")

    def _do_immediate_publish(self) -> None:
        if self.publish_runner is not None:
            QMessageBox.information(self, "發布進行中", "目前已有發布正在進行，請稍候。")
            return

        validated = self._validate_common()
        if validated is None:
            return
        content, target_pairs = validated
        targets = [url for url, _label in target_pairs]

        target_lines = [f"• {label}" for _url, label in target_pairs]
        preview_content = content if len(content) <= 800 else content[:800] + "\n……"

        confirmation = QMessageBox(self)
        confirmation.setIcon(QMessageBox.Icon.Warning)
        confirmation.setWindowTitle("確認立即發布")
        confirmation.setText("確認後，HouseFlow 會自動按下 Facebook 的「發布」。")
        confirmation.setInformativeText(
            "發布位置：\n"
            + "\n".join(target_lines)
            + f"\n\n圖片：{len(self.image_paths)} 張"
            + f"\n文案：{len(content)} 字"
            + "\n\n文案預覽：\n"
            + preview_content
        )

        publish_now = confirmation.addButton("確認並開始發布", QMessageBox.ButtonRole.AcceptRole)
        confirmation.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        confirmation.setDefaultButton(publish_now)
        confirmation.exec()

        if confirmation.clickedButton() != publish_now:
            return

        QGuiApplication.clipboard().setText(content)

        self._selected_group_names_snapshot = [
            checkbox.text() for checkbox, _ in self.group_checks if checkbox.isChecked()
        ]
        self._publish_profile_snapshot = self.publish_profile.isChecked()

        # 真正的 Facebook 自動化（Playwright）放到背景 QThread 執行，
        # 不能卡住 GUI——這裡只是換了執行緒，publish_posts() 本身完全沒有改。
        self.primary_cta_button.setEnabled(False)
        self.primary_cta_button.setText("發布中…")
        self.login_button.setEnabled(False)
        self.status_label.setText(f"正在自動發布，共 {len(targets)} 個位置，請勿關閉 HouseFlow 或 Chromium……")

        self.publish_runner = AdHocPublishRunner(targets, content, self.image_paths)
        self.publish_runner.finished.connect(self._on_publish_finished)
        self.publish_runner.failed.connect(self._on_publish_failed)
        self.publish_runner.start()

    def _on_publish_finished(self, report: dict) -> None:
        success_count = int(report.get("success_count", 0))
        failed_count = int(report.get("failed_count", 0))
        results = list(report.get("results", []))
        selected_group_names = getattr(self, "_selected_group_names_snapshot", [])
        publish_profile_checked = getattr(self, "_publish_profile_snapshot", False)

        result_lines: list[str] = []
        for index, result in enumerate(results, start=1):
            success = bool(result.get("success"))
            url = str(result.get("url", ""))
            message = str(result.get("message", ""))
            icon = "✓" if success else "✕"

            if url == "https://www.facebook.com/":
                target_name = "Facebook 個人動態"
            else:
                offset = 2 if publish_profile_checked else 1
                position = index - offset
                target_name = (
                    selected_group_names[position]
                    if 0 <= position < len(selected_group_names)
                    else url
                )

            result_lines.append(f"{icon} {target_name}" + ("" if success else f"\n   原因：{message}"))

        self.status_label.setText(f"發布完成：成功 {success_count}，失敗 {failed_count}。")
        summary = f"成功：{success_count}\n失敗：{failed_count}\n\n" + "\n".join(result_lines)

        if failed_count:
            QMessageBox.warning(self, "立即發布完成", summary)
        else:
            show_toast(self, "✓ 發布完成", kind="success")

        self._finish_publish_ui()

    def _on_publish_failed(self, message: str) -> None:
        QMessageBox.critical(self, "立即發布失敗", message)
        self.status_label.setText("Facebook 立即發布失敗。")
        self._finish_publish_ui()

    def _finish_publish_ui(self) -> None:
        if self.publish_runner is not None:
            self.publish_runner.wait_and_cleanup()
        self.publish_runner = None
        self.login_button.setEnabled(True)
        self.primary_cta_button.setEnabled(True)
        self._update_cta_mode()
