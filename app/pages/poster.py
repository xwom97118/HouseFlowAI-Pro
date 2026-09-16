from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QAbstractItemView,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.services.database import Database
from app.services.facebook_service import FacebookService
from app.services.copywriting_engine import AJCopyEngine
from app.widgets.property_picker import PropertyPicker
from app.widgets.common import SectionTitle


class ImagePreviewList(QListWidget):
    def __init__(self, order_changed) -> None:
        super().__init__()

        self.order_changed = order_changed
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Snap)
        self.setWrapping(True)
        self.setSpacing(10)
        self.setIconSize(QSize(150, 110))
        self.setGridSize(QSize(180, 160))
        self.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.setDragDropMode(
            QAbstractItemView.DragDropMode.InternalMove
        )
        self.setDefaultDropAction(
            Qt.DropAction.MoveAction
        )

    def dropEvent(self, event) -> None:
        super().dropEvent(event)

        if callable(self.order_changed):
            self.order_changed()



class PosterPage(QWidget):
    def __init__(self, db: Database, go_dashboard) -> None:
        super().__init__()

        self.db = db
        self.go_dashboard = go_dashboard
        self.facebook = FacebookService()
        self.copy_engine = AJCopyEngine()
        self.current_property_id: int | None = None
        self.image_paths: list[str] = []
        self.use_sync_images = True
        self.group_checks: list[tuple[QCheckBox, str]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 24)
        root.setSpacing(14)

        header = QHBoxLayout()

        back_button = QPushButton("← 返回 Dashboard")
        back_button.setObjectName("SecondaryButton")
        back_button.clicked.connect(self.go_dashboard)

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
                "選擇物件、確認文案與圖片，再一鍵發布至 Facebook。",
            )
        )

        root.addWidget(QLabel("選擇物件"))

        self.property_picker = PropertyPicker()
        self.property_picker.property_selected.connect(
            self.property_changed
        )
        root.addWidget(self.property_picker)

        root.addWidget(QLabel("貼文內容"))

        self.content_editor = QPlainTextEdit()
        self.content_editor.setPlaceholderText(
            "請輸入要發布的 Facebook 文案……"
        )
        root.addWidget(self.content_editor, 1)

        image_row = QHBoxLayout()

        self.image_label = QLabel("尚未選擇圖片")
        self.use_sync_checkbox = QCheckBox("使用同步照片")
        self.use_sync_checkbox.setChecked(True)
        self.use_sync_checkbox.toggled.connect(
            self.sync_image_mode_changed
        )

        image_row.addWidget(self.use_sync_checkbox)
        self.image_label.setObjectName("MutedLabel")

        choose_images_button = QPushButton("選擇圖片")
        choose_images_button.setObjectName("SecondaryButton")
        choose_images_button.clicked.connect(self.choose_images)

        clear_images_button = QPushButton("清除圖片")
        clear_images_button.setObjectName("SecondaryButton")
        clear_images_button.clicked.connect(self.clear_images)

        image_row.addWidget(self.image_label, 1)
        image_row.addWidget(choose_images_button)
        image_row.addWidget(clear_images_button)
        root.addLayout(image_row)

        preview_hint = QLabel(
            "圖片可拖曳排序；雙擊放大；右鍵可設為封面或移除。"
        )
        preview_hint.setObjectName("MutedLabel")
        root.addWidget(preview_hint)

        self.preview_list = ImagePreviewList(
            self.image_order_changed
        )
        self.preview_list.setMinimumHeight(190)
        self.preview_list.setMaximumHeight(360)
        self.preview_list.itemDoubleClicked.connect(
            self.open_image_preview
        )
        self.preview_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.preview_list.customContextMenuRequested.connect(
            self.show_image_menu
        )
        root.addWidget(self.preview_list)

        target_box = QGroupBox("發布位置")
        target_layout = QVBoxLayout(target_box)

        self.publish_profile = QCheckBox(
            "準備發布至 Facebook 個人動態"
        )
        target_layout.addWidget(self.publish_profile)

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
        target_layout.addLayout(group_header)

        self.groups_container = QWidget()
        self.groups_layout = QVBoxLayout(self.groups_container)
        self.groups_layout.setContentsMargins(4, 4, 4, 4)
        self.groups_layout.setSpacing(6)

        self.groups_scroll = QScrollArea()
        self.groups_scroll.setWidgetResizable(True)
        self.groups_scroll.setMaximumHeight(160)
        self.groups_scroll.setWidget(self.groups_container)
        target_layout.addWidget(self.groups_scroll)

        root.addWidget(target_box)

        button_row = QHBoxLayout()

        reload_button = QPushButton("重新載入物件")
        reload_button.setObjectName("SecondaryButton")
        reload_button.clicked.connect(self.reload_properties)

        copy_button = QPushButton("複製文案")
        copy_button.setObjectName("SecondaryButton")
        copy_button.clicked.connect(self.copy_content)

        preview_button = QPushButton("確認發布內容")
        preview_button.setObjectName("SecondaryButton")
        preview_button.clicked.connect(self.preview_post)

        self.publish_button = QPushButton("確認並一鍵發布")
        self.publish_button.setObjectName("PrimaryButton")
        self.publish_button.clicked.connect(self.start_publish)

        button_row.addWidget(reload_button)
        button_row.addWidget(copy_button)
        button_row.addWidget(preview_button)
        button_row.addStretch()
        button_row.addWidget(self.publish_button)

        root.addLayout(button_row)

        self.status_label = QLabel(
            "請先登入 Facebook，再選擇發布位置。"
        )
        self.status_label.setObjectName("MutedLabel")
        root.addWidget(self.status_label)

        self.reload_properties()
        self.reload_groups()
        self.refresh_image_preview()

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
            pixmap = QPixmap(image_path)

            if pixmap.isNull():
                icon = QIcon()
            else:
                scaled = pixmap.scaled(
                    150,
                    110,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                icon = QIcon(scaled)

            prefix = "★ 封面" if index == 0 else f"{index + 1:02d}"
            item = QListWidgetItem(
                icon,
                f"{prefix}\n{Path(image_path).name}",
            )
            item.setData(
                Qt.ItemDataRole.UserRole,
                image_path,
            )
            item.setToolTip(image_path)
            item.setTextAlignment(
                Qt.AlignmentFlag.AlignCenter
            )
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsDragEnabled
                | Qt.ItemFlag.ItemIsDropEnabled
            )

            self.preview_list.addItem(item)

        self.image_label.setText(
            f"目前共 {len(self.image_paths)} 張照片"
        )

    def image_order_changed(self) -> None:
        ordered_paths: list[str] = []

        for index in range(self.preview_list.count()):
            item = self.preview_list.item(index)
            path = item.data(
                Qt.ItemDataRole.UserRole
            )

            if path:
                ordered_paths.append(str(path))

        if ordered_paths:
            self.image_paths = ordered_paths
            self.refresh_image_preview()
            self.status_label.setText(
                "圖片順序已更新，Facebook 將依此順序上傳。"
            )

    def open_image_preview(
        self,
        item: QListWidgetItem,
    ) -> None:
        image_path = item.data(
            Qt.ItemDataRole.UserRole
        )

        if not image_path:
            return

        pixmap = QPixmap(str(image_path))

        if pixmap.isNull():
            QMessageBox.warning(
                self,
                "無法開啟圖片",
                "這張圖片無法載入。",
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(
            Path(str(image_path)).name
        )
        dialog.resize(1000, 760)

        layout = QVBoxLayout(dialog)

        image_label = QLabel()
        image_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        scaled = pixmap.scaled(
            940,
            680,
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

        image_path = item.data(
            Qt.ItemDataRole.UserRole
        )

        if not image_path:
            return

        menu = QMenu(self)

        cover_action = menu.addAction("★ 設為封面")
        preview_action = menu.addAction("放大預覽")
        menu.addSeparator()
        remove_action = menu.addAction("移除這張圖片")

        selected = menu.exec(
            self.preview_list.mapToGlobal(position)
        )

        if selected == cover_action:
            self.set_cover_image(str(image_path))
        elif selected == preview_action:
            self.open_image_preview(item)
        elif selected == remove_action:
            self.remove_image(str(image_path))

    def set_cover_image(
        self,
        image_path: str,
    ) -> None:
        if image_path not in self.image_paths:
            return

        self.image_paths.remove(image_path)
        self.image_paths.insert(0, image_path)
        self.refresh_image_preview()

        self.status_label.setText(
            f"已將 {Path(image_path).name} 設為封面。"
        )

    def remove_image(
        self,
        image_path: str,
    ) -> None:
        if image_path not in self.image_paths:
            return

        answer = QMessageBox.question(
            self,
            "移除圖片",
            f"確定不發布這張圖片嗎？\n{Path(image_path).name}",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        self.image_paths.remove(image_path)
        self.refresh_image_preview()

        self.status_label.setText(
            f"已移除 {Path(image_path).name}，原始檔案沒有被刪除。"
        )

    def sync_image_mode_changed(self, checked: bool) -> None:
        self.use_sync_images = checked

        if checked:
            self.property_changed()
        else:
            self.refresh_image_preview()

    def reload_properties(self) -> None:
        current_id = (
            self.current_property_id
            or self.property_picker.current_property_id()
        )

        rows = self.db.list_properties()

        self.property_picker.set_properties(
            rows,
            selected_id=current_id,
        )

    def reload_groups(self) -> None:
        selected_urls = {
            url
            for checkbox, url in self.group_checks
            if checkbox.isChecked()
        }

        while self.groups_layout.count():
            item = self.groups_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.group_checks.clear()
        groups = self.db.enabled_groups()

        if not groups:
            empty_label = QLabel(
                "尚未建立社團。請先到「社團管理」新增常用社團。"
            )
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
            checkbox.setChecked(url in selected_urls)

            self.groups_layout.addWidget(checkbox)
            self.group_checks.append((checkbox, url))

        self.groups_layout.addStretch()

    def select_all_groups(self) -> None:
        for checkbox, _ in self.group_checks:
            checkbox.setChecked(True)

    def clear_all_groups(self) -> None:
        for checkbox, _ in self.group_checks:
            checkbox.setChecked(False)

    def property_changed(
        self,
        property_id: int | None = None,
    ) -> None:
        if property_id is None:
            property_id = (
                self.property_picker.current_property_id()
            )

        if property_id is None:
            self.current_property_id = None
            self.content_editor.clear()
            self.image_paths = []
            self.refresh_image_preview()
            return

        self.current_property_id = int(property_id)

        property_data = self.db.get_property(
            self.current_property_id
        )

        if not property_data:
            self.content_editor.clear()
            return

        profile = {
            "brand_slogan": self.db.get_setting(
                "brand_slogan",
                "",
            ),
            "default_cta": self.db.get_setting(
                "default_cta",
                "",
            ),
            "default_hashtags": self.db.get_setting(
                "default_hashtags",
                "",
            ),
        }

        content = self.copy_engine.generate(
            property_data,
            profile=profile,
        )
        self.content_editor.setPlainText(content)

        if self.use_sync_images:
            image_paths = str(
                property_data.get(
                    "image_paths",
                    "",
                )
            ).strip()

            self.image_paths = [
                path
                for path in image_paths.split("\n")
                if path and Path(path).exists()
            ]

            if self.image_paths:
                self.image_label.setText(
                    f"已同步 {len(self.image_paths)} 張照片"
                )
            else:
                self.image_label.setText(
                    "此物件尚未同步照片"
                )

            self.refresh_image_preview()

    def login_facebook(self) -> None:
        self.login_button.setEnabled(False)
        self.status_label.setText("正在開啟 Facebook……")
        QApplication.processEvents()

        try:
            self.facebook.open_login()
            self.status_label.setText(
                "Facebook 視窗已關閉，登入狀態已保存。"
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Facebook 開啟失敗",
                str(exc),
            )
            self.status_label.setText("Facebook 開啟失敗。")
        finally:
            self.login_button.setEnabled(True)

    def copy_content(self) -> None:
        content = self.content_editor.toPlainText().strip()

        if not content:
            QMessageBox.warning(
                self,
                "沒有內容",
                "請先輸入貼文內容。",
            )
            return

        QGuiApplication.clipboard().setText(content)
        self.status_label.setText("貼文內容已複製。")

    def preview_post(self) -> None:
        content = self.content_editor.toPlainText().strip()
        targets = self.get_targets()

        if not content:
            QMessageBox.warning(
                self,
                "沒有內容",
                "請先輸入貼文內容。",
            )
            return

        if not targets:
            QMessageBox.warning(
                self,
                "沒有發布位置",
                "請勾選個人動態或至少一個社團。",
            )
            return

        selected_group_count = sum(
            1
            for checkbox, _ in self.group_checks
            if checkbox.isChecked()
        )

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

    def start_publish(self) -> None:
        content = self.content_editor.toPlainText().strip()
        targets = self.get_targets()

        if not content:
            QMessageBox.warning(
                self,
                "沒有內容",
                "請先輸入貼文內容。",
            )
            return

        if not targets:
            QMessageBox.warning(
                self,
                "沒有發布位置",
                "請勾選個人動態或至少一個社團。",
            )
            return

        selected_group_names = [
            checkbox.text()
            for checkbox, _ in self.group_checks
            if checkbox.isChecked()
        ]

        target_lines: list[str] = []

        if self.publish_profile.isChecked():
            target_lines.append("• Facebook 個人動態")

        target_lines.extend(
            f"• {name}"
            for name in selected_group_names
        )

        preview_content = content

        if len(preview_content) > 800:
            preview_content = (
                preview_content[:800]
                + "\n……"
            )

        confirmation = QMessageBox(self)
        confirmation.setIcon(
            QMessageBox.Icon.Warning
        )
        confirmation.setWindowTitle(
            "確認一鍵發布"
        )
        confirmation.setText(
            "確認後，HouseFlow 會自動按下 Facebook 的「發布」。"
        )
        confirmation.setInformativeText(
            "發布位置：\n"
            + "\n".join(target_lines)
            + f"\n\n圖片：{len(self.image_paths)} 張"
            + f"\n文案：{len(content)} 字"
            + "\n\n文案預覽：\n"
            + preview_content
        )

        publish_now = confirmation.addButton(
            "確認並開始發布",
            QMessageBox.ButtonRole.AcceptRole,
        )
        confirmation.addButton(
            "取消",
            QMessageBox.ButtonRole.RejectRole,
        )
        confirmation.setDefaultButton(
            publish_now
        )
        confirmation.exec()

        if confirmation.clickedButton() != publish_now:
            return

        QGuiApplication.clipboard().setText(
            content
        )

        self.publish_button.setEnabled(False)
        self.login_button.setEnabled(False)
        self.status_label.setText(
            f"正在自動發布 0/{len(targets)}，"
            "請勿關閉 HouseFlow 或 Chromium……"
        )
        QApplication.processEvents()

        try:
            report = self.facebook.publish_posts(
                targets,
                content,
                self.image_paths,
            )

            success_count = int(
                report.get(
                    "success_count",
                    0,
                )
            )
            failed_count = int(
                report.get(
                    "failed_count",
                    0,
                )
            )
            results = list(
                report.get(
                    "results",
                    [],
                )
            )

            result_lines: list[str] = []

            for index, result in enumerate(
                results,
                start=1,
            ):
                success = bool(
                    result.get("success")
                )
                url = str(
                    result.get("url", "")
                )
                message = str(
                    result.get(
                        "message",
                        "",
                    )
                )

                icon = "✓" if success else "✕"

                if (
                    url
                    == "https://www.facebook.com/"
                ):
                    target_name = "Facebook 個人動態"
                else:
                    target_name = (
                        selected_group_names[
                            index - (
                                2
                                if self.publish_profile.isChecked()
                                else 1
                            )
                        ]
                        if (
                            0
                            <= index - (
                                2
                                if self.publish_profile.isChecked()
                                else 1
                            )
                            < len(selected_group_names)
                        )
                        else url
                    )

                result_lines.append(
                    f"{icon} {target_name}"
                    + (
                        ""
                        if success
                        else f"\n   原因：{message}"
                    )
                )

            self.status_label.setText(
                f"發布完成：成功 {success_count}，"
                f"失敗 {failed_count}。"
            )

            summary = (
                f"成功：{success_count}\n"
                f"失敗：{failed_count}\n\n"
                + "\n".join(result_lines)
            )

            if failed_count:
                QMessageBox.warning(
                    self,
                    "一鍵發布完成",
                    summary,
                )
            else:
                QMessageBox.information(
                    self,
                    "一鍵發布完成",
                    summary,
                )

        except Exception as exc:
            QMessageBox.critical(
                self,
                "一鍵發布失敗",
                str(exc),
            )
            self.status_label.setText(
                "Facebook 一鍵發布失敗。"
            )

        finally:
            self.publish_button.setEnabled(True)
            self.login_button.setEnabled(True)