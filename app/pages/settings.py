from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.services.database import Database
from app.widgets.common import SectionTitle


class SettingsPage(QWidget):
    def __init__(self, db: Database) -> None:
        super().__init__()

        self.db = db

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 24)
        root.setSpacing(16)

        root.addWidget(
            SectionTitle(
                "個人化設定",
                "設定個人品牌、聯絡方式與預設文案內容。",
            )
        )

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 12, 0)
        content_layout.setSpacing(16)

        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        basic_group = QGroupBox("基本資料")
        basic_form = QFormLayout(basic_group)

        self.name = QLineEdit(
            self.db.get_setting(
                "agent_name",
                "黃冠嘉",
            )
        )
        self.display_name = QLineEdit(
            self.db.get_setting(
                "display_name",
                "阿嘉",
            )
        )
        self.company = QLineEdit(
            self.db.get_setting(
                "company_name",
                "台慶不動產",
            )
        )
        self.brand = QLineEdit(
            self.db.get_setting(
                "brand",
                "龍潭成交策略",
            )
        )
        self.service_area = QLineEdit(
            self.db.get_setting(
                "service_area",
                "龍潭、中壢、平鎮、楊梅、新竹",
            )
        )
        self.phone = QLineEdit(
            self.db.get_setting(
                "agent_phone",
                "",
            )
        )
        self.line_id = QLineEdit(
            self.db.get_setting(
                "line_id",
                "",
            )
        )
        self.email = QLineEdit(
            self.db.get_setting(
                "agent_email",
                "",
            )
        )

        basic_form.addRow("姓名", self.name)
        basic_form.addRow("對外稱呼", self.display_name)
        basic_form.addRow("公司", self.company)
        basic_form.addRow("品牌名稱", self.brand)
        basic_form.addRow("服務區域", self.service_area)
        basic_form.addRow("電話", self.phone)
        basic_form.addRow("LINE ID", self.line_id)
        basic_form.addRow("Email", self.email)

        content_layout.addWidget(basic_group)

        brand_group = QGroupBox("品牌與文案")
        brand_form = QFormLayout(brand_group)

        self.slogan = QPlainTextEdit(
            self.db.get_setting(
                "brand_slogan",
                "我是阿嘉，幫你更了解你的不動產價值。",
            )
        )
        self.slogan.setMaximumHeight(80)

        self.default_cta = QPlainTextEdit(
            self.db.get_setting(
                "default_cta",
                "留言「賞屋」，我把完整照片與物件資料傳給你。",
            )
        )
        self.default_cta.setMaximumHeight(90)

        self.default_hashtags = QPlainTextEdit(
            self.db.get_setting(
                "default_hashtags",
                "#不動產買賣找阿嘉\n#龍潭成交策略",
            )
        )
        self.default_hashtags.setMaximumHeight(110)

        self.video_outro = QPlainTextEdit(
            self.db.get_setting(
                "video_outro",
                "我是阿嘉，幫你更了解你的不動產價值。",
            )
        )
        self.video_outro.setMaximumHeight(80)

        self.copy_style = QComboBox()
        self.copy_style.addItems(
            [
                "親切自然",
                "專業分析",
                "成交導向",
                "簡短直接",
                "短影音口吻",
            ]
        )

        saved_style = self.db.get_setting(
            "copy_style",
            "親切自然",
        )
        style_index = self.copy_style.findText(
            saved_style
        )

        if style_index >= 0:
            self.copy_style.setCurrentIndex(
                style_index
            )

        brand_form.addRow("品牌口號", self.slogan)
        brand_form.addRow("預設 CTA", self.default_cta)
        brand_form.addRow("預設 Hashtag", self.default_hashtags)
        brand_form.addRow("影片結尾", self.video_outro)
        brand_form.addRow("文案風格", self.copy_style)

        content_layout.addWidget(brand_group)

        facebook_group = QGroupBox("Facebook 設定")
        facebook_form = QFormLayout(facebook_group)

        self.facebook_name = QLineEdit(
            self.db.get_setting(
                "facebook_name",
                "",
            )
        )
        self.facebook_profile_url = QLineEdit(
            self.db.get_setting(
                "facebook_profile_url",
                "",
            )
        )

        facebook_form.addRow(
            "Facebook 顯示名稱",
            self.facebook_name,
        )
        facebook_form.addRow(
            "Facebook 個人網址",
            self.facebook_profile_url,
        )

        content_layout.addWidget(facebook_group)

        ai_group = QGroupBox("OpenAI（選用）")
        ai_form = QFormLayout(ai_group)

        self.api_key = QLineEdit(
            self.db.get_setting(
                "openai_api_key",
                "",
            )
        )
        self.api_key.setEchoMode(
            QLineEdit.EchoMode.Password
        )

        self.ai_enabled = QCheckBox(
            "啟用 OpenAI 文案功能"
        )
        self.ai_enabled.setChecked(
            self.db.get_setting(
                "ai_enabled",
                "0",
            ) == "1"
        )

        ai_note = QLabel(
            "目前 AJ Copy Engine 不需要 OpenAI；"
            "只有啟用 AI 功能時才會使用 API Key。"
        )
        ai_note.setWordWrap(True)
        ai_note.setObjectName("MutedLabel")

        ai_form.addRow("OpenAI API Key", self.api_key)
        ai_form.addRow("AI 狀態", self.ai_enabled)
        ai_form.addRow("", ai_note)

        content_layout.addWidget(ai_group)

        content_layout.addStretch()

        button_row = QHBoxLayout()

        reset_button = QPushButton("恢復預設")
        reset_button.setObjectName("SecondaryButton")
        reset_button.clicked.connect(
            self.reset_defaults
        )

        save_button = QPushButton("儲存設定")
        save_button.setObjectName("PrimaryButton")
        save_button.clicked.connect(self.save)

        button_row.addStretch()
        button_row.addWidget(reset_button)
        button_row.addWidget(save_button)

        root.addLayout(button_row)

    def save(self) -> None:
        settings = {
            "agent_name": self.name.text().strip(),
            "display_name": self.display_name.text().strip(),
            "company_name": self.company.text().strip(),
            "brand": self.brand.text().strip(),
            "service_area": self.service_area.text().strip(),
            "agent_phone": self.phone.text().strip(),
            "line_id": self.line_id.text().strip(),
            "agent_email": self.email.text().strip(),
            "brand_slogan": self.slogan.toPlainText().strip(),
            "default_cta": self.default_cta.toPlainText().strip(),
            "default_hashtags": self.default_hashtags.toPlainText().strip(),
            "video_outro": self.video_outro.toPlainText().strip(),
            "copy_style": self.copy_style.currentText(),
            "facebook_name": self.facebook_name.text().strip(),
            "facebook_profile_url": self.facebook_profile_url.text().strip(),
            "openai_api_key": self.api_key.text().strip(),
            "ai_enabled": (
                "1"
                if self.ai_enabled.isChecked()
                else "0"
            ),
        }

        for key, value in settings.items():
            self.db.set_setting(
                key,
                value,
            )

        QMessageBox.information(
            self,
            "儲存完成",
            "個人化設定已儲存。",
        )

    def reset_defaults(self) -> None:
        answer = QMessageBox.question(
            self,
            "恢復預設",
            "確定要恢復預設內容嗎？",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        self.name.setText("")
        self.display_name.setText("")
        self.company.setText("")
        self.brand.setText("")
        self.service_area.setText("")
        self.phone.setText("")
        self.line_id.setText("")
        self.email.setText("")
        self.slogan.setPlainText("")
        self.default_cta.setPlainText(
            "留言「賞屋」，我把完整照片與物件資料傳給你。"
        )
        self.default_hashtags.setPlainText("")
        self.video_outro.setPlainText("")
        self.copy_style.setCurrentText(
            "親切自然"
        )
        self.facebook_name.setText("")
        self.facebook_profile_url.setText("")
        self.api_key.setText("")
        self.ai_enabled.setChecked(False)

        QMessageBox.information(
            self,
            "已恢復預設",
            "請確認內容後按「儲存設定」。",
        )