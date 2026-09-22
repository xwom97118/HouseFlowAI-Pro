from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.services import brand_profile
from app.services.ai_service import AIService
from app.services.database import Database
from app.widgets.common import SectionTitle


class AICenterPage(QWidget):
    PLATFORMS = [
        "Facebook",
        "Instagram",
        "Threads",
        "Reels 15秒",
        "Reels 30秒",
        "Reels 60秒",
    ]

    def __init__(self, db: Database) -> None:
        super().__init__()

        self.db = db
        self.ai: AIService | None = None
        self.property_id: int | None = None
        self.property_data: dict = {}
        self.editors: dict[str, QPlainTextEdit] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 24)
        root.setSpacing(14)

        root.addWidget(
            SectionTitle(
                "AI 文案中心",
                "選擇物件後，一鍵生成各平台文案與 Reels 腳本。",
            )
        )

        form = QFormLayout()

        self.property_combo = QComboBox()
        self.property_combo.currentIndexChanged.connect(
            self._property_changed
        )

        self.style_combo = QComboBox()
        self.style_combo.addItems(
            list(AIService.STYLE_MAP.keys())
        )

        self.extra = QPlainTextEdit()
        self.extra.setMaximumHeight(80)
        self.extra.setPlaceholderText(
            "補充要求，例如：強調雙車位、適合首購、"
            "開頭先講總價、不要太浮誇…"
        )

        form.addRow("選擇物件", self.property_combo)
        form.addRow("文案風格", self.style_combo)
        form.addRow("補充要求", self.extra)

        root.addLayout(form)

        actions = QHBoxLayout()

        self.generate_button = QPushButton("✨ AI 一鍵生成全部")
        self.generate_button.setObjectName("PrimaryButton")
        self.generate_button.clicked.connect(self.generate_all)

        self.generate_current_button = QPushButton(
            "只生成目前分頁"
        )
        self.generate_current_button.setObjectName(
            "SecondaryButton"
        )
        self.generate_current_button.clicked.connect(
            self.generate_current
        )

        save_button = QPushButton("儲存全部")
        save_button.setObjectName("SecondaryButton")
        save_button.clicked.connect(self.save_all)

        actions.addWidget(self.generate_button)
        actions.addWidget(self.generate_current_button)
        actions.addWidget(save_button)
        actions.addStretch()

        root.addLayout(actions)

        self.status_label = QLabel("準備完成")
        self.status_label.setObjectName("MutedLabel")
        root.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, len(self.PLATFORMS))
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.hide()
        root.addWidget(self.progress)

        self.tabs = QTabWidget()

        for platform in self.PLATFORMS:
            page = QWidget()
            layout = QVBoxLayout(page)

            editor = QPlainTextEdit()
            editor.setPlaceholderText(
                f"{platform} 文案會顯示在這裡…"
            )

            copy_button = QPushButton("複製此內容")
            copy_button.setObjectName("SecondaryButton")
            copy_button.clicked.connect(
                lambda _=False, current_platform=platform:
                self.copy_text(current_platform)
            )

            layout.addWidget(editor, 1)
            layout.addWidget(copy_button)

            self.tabs.addTab(page, platform)
            self.editors[platform] = editor

        root.addWidget(self.tabs, 1)

        self.reload_properties()

    def _get_ai_service(self) -> AIService:
        if self.ai is None:
            self.ai = AIService()

        return self.ai

    def reload_properties(
        self,
        select_id: int | None = None,
    ) -> None:
        rows = self.db.list_properties()

        self.property_combo.blockSignals(True)
        self.property_combo.clear()

        for row in rows:
            title = str(
                row.get("title")
                or f"物件 #{row.get('id')}"
            )

            price = str(row.get("price") or "").strip()

            display_text = (
                f"{title}｜{price}"
                if price
                else title
            )

            self.property_combo.addItem(
                display_text,
                row.get("id"),
            )

        self.property_combo.blockSignals(False)

        if select_id is not None:
            index = self.property_combo.findData(select_id)

            if index >= 0:
                self.property_combo.setCurrentIndex(index)

        self._property_changed()

    def select_property(self, property_id: int) -> None:
        self.reload_properties(property_id)

    def _property_changed(self) -> None:
        property_id = self.property_combo.currentData()

        self.property_id = (
            int(property_id)
            if property_id is not None
            else None
        )

        if self.property_id is None:
            self.property_data = {}
            self.status_label.setText("目前沒有可用物件")
            return

        self.property_data = (
            self.db.get_property(self.property_id)
            or {}
        )

        title = self.property_data.get(
            "title",
            "未命名物件",
        )

        self.status_label.setText(
            f"目前選擇：{title}"
        )

    def generate_all(self) -> None:
        if not self._validate_property():
            return

        self._set_generating_state(True)
        self.progress.show()
        self.progress.setValue(0)

        style = self.style_combo.currentText()
        extra = self.extra.toPlainText().strip()

        try:
            ai_service = self._get_ai_service()

            for index, platform in enumerate(
                self.PLATFORMS,
                start=1,
            ):
                self.status_label.setText(
                    f"正在生成 {platform}…"
                )

                QApplication.processEvents()

                content = ai_service.generate(
                    self.property_data,
                    platform,
                    style,
                    extra,
                    brand_profile=brand_profile.load_profile(self.db),
                )

                self.editors[platform].setPlainText(content)
                self.progress.setValue(index)

            self.status_label.setText(
                "全部文案生成完成"
            )

            QMessageBox.information(
                self,
                "生成完成",
                "Facebook、Instagram、Threads "
                "及 Reels 腳本已全部完成。",
            )

        except Exception as exc:
            self.status_label.setText("AI 生成失敗")

            QMessageBox.critical(
                self,
                "AI 生成失敗",
                str(exc),
            )

        finally:
            self._set_generating_state(False)

    def generate_current(self) -> None:
        if not self._validate_property():
            return

        platform = self.tabs.tabText(
            self.tabs.currentIndex()
        )

        style = self.style_combo.currentText()
        extra = self.extra.toPlainText().strip()

        self._set_generating_state(True)
        self.status_label.setText(
            f"正在生成 {platform}…"
        )

        QApplication.setOverrideCursor(
            Qt.CursorShape.WaitCursor
        )
        QApplication.processEvents()

        try:
            content = self._get_ai_service().generate(
                self.property_data,
                platform,
                style,
                extra,
                brand_profile=brand_profile.load_profile(self.db),
            )

            self.editors[platform].setPlainText(content)
            self.status_label.setText(
                f"{platform} 生成完成"
            )

        except Exception as exc:
            self.status_label.setText("AI 生成失敗")

            QMessageBox.critical(
                self,
                "AI 生成失敗",
                str(exc),
            )

        finally:
            QApplication.restoreOverrideCursor()
            self._set_generating_state(False)

    def _validate_property(self) -> bool:
        if self.property_data:
            return True

        QMessageBox.information(
            self,
            "尚未選擇物件",
            "請先選擇一筆物件。",
        )

        return False

    def _set_generating_state(
        self,
        generating: bool,
    ) -> None:
        self.generate_button.setEnabled(not generating)
        self.generate_current_button.setEnabled(
            not generating
        )

        if generating:
            QApplication.setOverrideCursor(
                Qt.CursorShape.WaitCursor
            )
        else:
            QApplication.restoreOverrideCursor()

    def save_all(self) -> None:
        if self.property_id is None:
            QMessageBox.information(
                self,
                "尚未選擇物件",
                "請先選擇一筆物件。",
            )
            return

        style = self.style_combo.currentText()
        saved_count = 0

        for platform, editor in self.editors.items():
            text = editor.toPlainText().strip()

            if not text:
                continue

            self.db.save_generation(
                self.property_id,
                platform,
                style,
                text,
            )

            saved_count += 1

        if saved_count == 0:
            QMessageBox.information(
                self,
                "沒有內容",
                "目前沒有可儲存的文案。",
            )
            return

        self.status_label.setText(
            f"已儲存 {saved_count} 份文案"
        )

        QMessageBox.information(
            self,
            "儲存完成",
            f"已儲存 {saved_count} 份 AI 文案。",
        )

    def copy_text(self, platform: str) -> None:
        content = (
            self.editors[platform]
            .toPlainText()
            .strip()
        )

        if not content:
            QMessageBox.information(
                self,
                "沒有內容",
                "這個分頁目前沒有可複製的內容。",
            )
            return

        QGuiApplication.clipboard().setText(content)

        self.status_label.setText(
            f"已複製 {platform} 內容"
        )