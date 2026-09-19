from __future__ import annotations

from collections.abc import Callable

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
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.services import brand_profile
from app.services.database import Database
from app.widgets.common import SectionTitle


def _scrollable(inner: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setWidget(inner)
    return scroll


class SettingsPage(QWidget):
    def __init__(self, db: Database, on_saved: Callable[[], None] | None = None) -> None:
        super().__init__()

        self.db = db
        self.on_saved = on_saved

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 24)
        root.setSpacing(14)

        root.addWidget(
            SectionTitle(
                "設定",
                "管理個人品牌、經紀業合規資訊與系統設定。",
            )
        )

        tabs = QTabWidget()
        tabs.addTab(self._build_general_tab(), "一般設定")
        tabs.addTab(self._build_brand_tab(), "品牌與經紀業資訊")
        tabs.addTab(self._build_social_tab(), "社群帳號")
        tabs.addTab(self._build_ai_tab(), "AI 文案設定")
        tabs.addTab(self._build_sync_tab(), "同步設定")
        tabs.addTab(self._build_automation_tab(), "排程設定")
        root.addWidget(tabs, 1)

        button_row = QHBoxLayout()
        reset_button = QPushButton("恢復預設")
        reset_button.setObjectName("SecondaryButton")
        reset_button.clicked.connect(self.reset_defaults)

        save_button = QPushButton("儲存設定")
        save_button.setObjectName("PrimaryButton")
        save_button.clicked.connect(self.save)

        button_row.addStretch()
        button_row.addWidget(reset_button)
        button_row.addWidget(save_button)
        root.addLayout(button_row)

    # ------------------------------------------------------------------
    # 一般設定
    # ------------------------------------------------------------------

    def _build_general_tab(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 12, 12, 0)
        layout.setSpacing(16)

        group = QGroupBox("基本資料")
        form = QFormLayout(group)

        self.name = QLineEdit(self.db.get_setting("agent_name", ""))
        self.company = QLineEdit(self.db.get_setting("company_name", ""))
        self.video_outro = QPlainTextEdit(self.db.get_setting("video_outro", ""))
        self.video_outro.setMaximumHeight(80)

        form.addRow("姓名", self.name)
        form.addRow("公司", self.company)
        form.addRow("短影音結尾文字", self.video_outro)

        layout.addWidget(group)
        layout.addStretch()

        return _scrollable(content)

    # ------------------------------------------------------------------
    # 品牌與經紀業資訊
    # ------------------------------------------------------------------

    def _build_brand_tab(self) -> QWidget:
        content = QWidget()
        outer = QHBoxLayout(content)
        outer.setContentsMargins(0, 12, 12, 0)
        outer.setSpacing(16)

        form_container = QWidget()
        form_layout = QVBoxLayout(form_container)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(16)

        brand_group = QGroupBox("品牌資料")
        brand_form = QFormLayout(brand_group)

        self.display_name = QLineEdit(self.db.get_setting("display_name", ""))
        self.service_area = QLineEdit(self.db.get_setting("service_area", ""))
        self.slogan = QPlainTextEdit(self.db.get_setting("brand_slogan", ""))
        self.slogan.setMaximumHeight(70)
        self.phone = QLineEdit(self.db.get_setting("agent_phone", ""))
        self.line_id = QLineEdit(self.db.get_setting("line_id", ""))
        self.email = QLineEdit(self.db.get_setting("agent_email", ""))
        self.default_cta = QPlainTextEdit(self.db.get_setting("default_cta", ""))
        self.default_cta.setMaximumHeight(80)
        self.default_hashtags = QPlainTextEdit(self.db.get_setting("default_hashtags", ""))
        self.default_hashtags.setMaximumHeight(90)

        brand_form.addRow("顯示名稱／個人品牌", self.display_name)
        brand_form.addRow("服務區域", self.service_area)
        brand_form.addRow("品牌標語", self.slogan)
        brand_form.addRow("電話", self.phone)
        brand_form.addRow("LINE", self.line_id)
        brand_form.addRow("Email", self.email)
        brand_form.addRow("預設 CTA", self.default_cta)
        brand_form.addRow("預設 Hashtag", self.default_hashtags)

        form_layout.addWidget(brand_group)

        brokerage_group = QGroupBox("不動產經紀業資訊（會自動加入所有物件貼文）")
        brokerage_form = QFormLayout(brokerage_group)

        self.brokerage_name = QLineEdit(self.db.get_setting("brokerage_name", ""))
        self.salesperson_name = QLineEdit(self.db.get_setting("salesperson_name", ""))
        self.salesperson_license = QLineEdit(self.db.get_setting("salesperson_license", ""))
        self.broker_name = QLineEdit(self.db.get_setting("broker_name", ""))
        self.broker_license = QLineEdit(self.db.get_setting("broker_license", ""))
        self.company_address = QLineEdit(self.db.get_setting("company_address", ""))
        self.company_phone = QLineEdit(self.db.get_setting("company_phone", ""))

        brokerage_form.addRow("經紀業名稱＊", self.brokerage_name)
        brokerage_form.addRow("營業員姓名", self.salesperson_name)
        brokerage_form.addRow("營業員證號＊", self.salesperson_license)
        brokerage_form.addRow("經紀人姓名", self.broker_name)
        brokerage_form.addRow("經紀人證號＊", self.broker_license)
        brokerage_form.addRow("公司地址", self.company_address)
        brokerage_form.addRow("公司電話", self.company_phone)

        note = QLabel(
            "＊ 標示欄位為必填。物件貼文（立即發布或加入排程）會先檢查這三項是否\n"
            "已填寫，未完成前無法發布，避免漏掉法定應揭露資訊。"
        )
        note.setObjectName("MutedLabel")
        note.setWordWrap(True)
        brokerage_form.addRow("", note)

        form_layout.addWidget(brokerage_group)
        form_layout.addStretch()

        outer.addWidget(form_container, 3)

        preview_group = QGroupBox("發文資訊預覽")
        preview_layout = QVBoxLayout(preview_group)
        self.brand_preview = QPlainTextEdit()
        self.brand_preview.setReadOnly(True)
        self.brand_preview.setPlaceholderText("填寫左側欄位後，這裡會即時顯示物件貼文結尾會自動加入的內容。")
        preview_layout.addWidget(self.brand_preview)
        outer.addWidget(preview_group, 2)

        for widget in (
            self.display_name, self.service_area, self.phone, self.line_id, self.email,
            self.brokerage_name, self.salesperson_name, self.salesperson_license,
            self.broker_name, self.broker_license,
        ):
            widget.textChanged.connect(self._refresh_brand_preview)
        for widget in (self.slogan, self.default_cta, self.default_hashtags):
            widget.textChanged.connect(self._refresh_brand_preview)

        self._refresh_brand_preview()

        return _scrollable(content)

    def _refresh_brand_preview(self) -> None:
        profile = {
            "brokerage_name": self.brokerage_name.text().strip(),
            "salesperson_name": self.salesperson_name.text().strip(),
            "salesperson_license": self.salesperson_license.text().strip(),
            "broker_name": self.broker_name.text().strip(),
            "broker_license": self.broker_license.text().strip(),
        }
        footer = brand_profile.format_compliance_footer(profile)
        hashtags = self.default_hashtags.toPlainText().strip()

        lines: list[str] = []
        if footer:
            lines.append(footer)
        else:
            missing = brand_profile.missing_compliance_labels(profile)
            lines.append(f"（經紀業資訊尚未完整，缺少：{'、'.join(missing)}）")

        if hashtags:
            lines.append("")
            lines.append(hashtags)

        self.brand_preview.setPlainText("\n".join(lines))

    # ------------------------------------------------------------------
    # 社群帳號
    # ------------------------------------------------------------------

    def _build_social_tab(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 12, 12, 0)
        layout.setSpacing(16)

        group = QGroupBox("Facebook")
        form = QFormLayout(group)

        self.facebook_name = QLineEdit(self.db.get_setting("facebook_name", ""))
        self.facebook_profile_url = QLineEdit(self.db.get_setting("facebook_profile_url", ""))

        form.addRow("Facebook 顯示名稱", self.facebook_name)
        form.addRow("Facebook 個人網址", self.facebook_profile_url)

        layout.addWidget(group)
        layout.addStretch()

        return _scrollable(content)

    # ------------------------------------------------------------------
    # AI 文案設定
    # ------------------------------------------------------------------

    def _build_ai_tab(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 12, 12, 0)
        layout.setSpacing(16)

        style_group = QGroupBox("文案風格")
        style_form = QFormLayout(style_group)

        self.copy_style = QComboBox()
        self.copy_style.addItems(["親切自然", "專業分析", "成交導向", "簡短直接", "短影音口吻"])
        saved_style = self.db.get_setting("copy_style", "親切自然")
        style_index = self.copy_style.findText(saved_style)
        if style_index >= 0:
            self.copy_style.setCurrentIndex(style_index)
        style_form.addRow("文案風格", self.copy_style)
        layout.addWidget(style_group)

        ai_group = QGroupBox("OpenAI（選用）")
        ai_form = QFormLayout(ai_group)

        self.api_key = QLineEdit(self.db.get_setting("openai_api_key", ""))
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)

        self.ai_enabled = QCheckBox("啟用 OpenAI 文案功能")
        self.ai_enabled.setChecked(self.db.get_setting("ai_enabled", "0") == "1")

        ai_note = QLabel("目前 AJ Copy Engine 不需要 OpenAI；只有啟用 AI 功能時才會使用 API Key。")
        ai_note.setWordWrap(True)
        ai_note.setObjectName("MutedLabel")

        ai_form.addRow("OpenAI API Key", self.api_key)
        ai_form.addRow("AI 狀態", self.ai_enabled)
        ai_form.addRow("", ai_note)

        layout.addWidget(ai_group)
        layout.addStretch()

        return _scrollable(content)

    # ------------------------------------------------------------------
    # 排程設定（Automation Engine）
    # ------------------------------------------------------------------

    def _build_automation_tab(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 12, 12, 0)
        layout.setSpacing(16)

        publish_group = QGroupBox("自動排程發布")
        publish_form = QFormLayout(publish_group)

        self.automation_enabled = QCheckBox("啟用自動排程發布")
        self.automation_enabled.setChecked(
            self.db.get_setting("automation_enabled", "1") == "1"
        )
        publish_form.addRow("", self.automation_enabled)

        self.minimize_to_tray = QCheckBox("關閉視窗時最小化到系統匣")
        self.minimize_to_tray.setChecked(
            self.db.get_setting("minimize_to_tray", "1") == "1"
        )
        publish_form.addRow("", self.minimize_to_tray)

        self.check_interval = QSpinBox()
        self.check_interval.setRange(5, 3600)
        self.check_interval.setSuffix(" 秒")
        self.check_interval.setValue(
            int(self.db.get_setting("automation_check_interval_seconds", "30") or 30)
        )
        publish_form.addRow("自動檢查間隔", self.check_interval)

        self.max_publish_retries = QSpinBox()
        self.max_publish_retries.setRange(0, 10)
        self.max_publish_retries.setValue(
            int(self.db.get_setting("automation_max_publish_retries", "3") or 3)
        )
        publish_form.addRow("發布失敗最大重試次數", self.max_publish_retries)

        layout.addWidget(publish_group)

        delete_group = QGroupBox("自動刪除已發布貼文")
        delete_form = QFormLayout(delete_group)

        self.automation_delete_enabled = QCheckBox("啟用自動刪文")
        self.automation_delete_enabled.setChecked(
            self.db.get_setting("automation_delete_enabled", "1") == "1"
        )
        delete_form.addRow("", self.automation_delete_enabled)

        self.default_delete_days = QSpinBox()
        self.default_delete_days.setRange(1, 365)
        self.default_delete_days.setSuffix(" 天")
        self.default_delete_days.setValue(
            int(self.db.get_setting("automation_default_delete_days", "15") or 15)
        )
        delete_form.addRow("預設自動刪文", self.default_delete_days)

        self.max_delete_retries = QSpinBox()
        self.max_delete_retries.setRange(0, 10)
        self.max_delete_retries.setValue(
            int(self.db.get_setting("automation_max_delete_retries", "3") or 3)
        )
        delete_form.addRow("刪文失敗最大重試次數", self.max_delete_retries)

        delete_note = QLabel(
            "目前發布流程還沒有辦法可靠取得 Facebook 貼文的網址／ID，\n"
            "所以自動刪文功能已經完整建好，但實際上會顯示「需要人工處理」，\n"
            "要等之後的版本補上可靠的貼文識別方式才能真的自動執行。"
        )
        delete_note.setObjectName("MutedLabel")
        delete_note.setWordWrap(True)
        delete_form.addRow("", delete_note)

        layout.addWidget(delete_group)

        history_group = QGroupBox("排程歷史紀錄")
        history_form = QFormLayout(history_group)

        self.history_retention_days = QSpinBox()
        self.history_retention_days.setRange(1, 365)
        self.history_retention_days.setSuffix(" 天")
        self.history_retention_days.setValue(
            int(self.db.get_setting("history_retention_days", "15") or 15)
        )
        history_form.addRow("排程歷史保留天數", self.history_retention_days)

        history_note = QLabel(
            "這裡清除的是 HouseFlow 資料庫裡「已完全結束」的排程紀錄列"
            "（發布成功／失敗／已取消，且沒有還在等待的自動刪文工作），\n"
            "跟 Facebook 上貼文本身的自動刪除是兩件事，不會刪除還在進行中的排程。"
        )
        history_note.setObjectName("MutedLabel")
        history_note.setWordWrap(True)
        history_form.addRow("", history_note)

        cleanup_button = QPushButton("立即清理歷史紀錄")
        cleanup_button.setObjectName("SecondaryButton")
        cleanup_button.clicked.connect(self._cleanup_history_now)
        history_form.addRow("", cleanup_button)

        layout.addWidget(history_group)
        layout.addStretch()

        return _scrollable(content)

    def _cleanup_history_now(self) -> None:
        removed = self.db.cleanup_old_schedule_history(self.history_retention_days.value())
        QMessageBox.information(self, "已清理歷史紀錄", f"已清除 {removed} 筆超過保留天數的排程歷史紀錄。")

    # ------------------------------------------------------------------
    # 同步設定（Auto Sync Center 全域設定）
    # ------------------------------------------------------------------

    def _build_sync_tab(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 12, 12, 0)
        layout.setSpacing(16)

        sync_group = QGroupBox("自動同步")
        sync_form = QFormLayout(sync_group)

        self.automation_sync_enabled = QCheckBox("啟用自動同步")
        self.automation_sync_enabled.setChecked(
            self.db.get_setting("automation_sync_enabled", "1") == "1"
        )
        sync_form.addRow("", self.automation_sync_enabled)

        self.automation_sync_max_concurrent = QSpinBox()
        self.automation_sync_max_concurrent.setRange(1, 5)
        self.automation_sync_max_concurrent.setValue(
            int(self.db.get_setting("automation_sync_max_concurrent", "1") or 1)
        )
        sync_form.addRow("最大同時同步來源", self.automation_sync_max_concurrent)

        self.automation_sync_timeout_seconds = QSpinBox()
        self.automation_sync_timeout_seconds.setRange(30, 600)
        self.automation_sync_timeout_seconds.setSuffix(" 秒")
        self.automation_sync_timeout_seconds.setValue(
            int(self.db.get_setting("automation_sync_timeout_seconds", "120") or 120)
        )
        sync_form.addRow("同步 timeout", self.automation_sync_timeout_seconds)

        self.automation_sync_max_retries = QSpinBox()
        self.automation_sync_max_retries.setRange(0, 10)
        self.automation_sync_max_retries.setValue(
            int(self.db.get_setting("automation_sync_max_retries", "3") or 3)
        )
        sync_form.addRow("同步失敗最大重試", self.automation_sync_max_retries)

        sync_note = QLabel(
            "本版預設 sequential 同步（同一時間只跑一個來源），避免一次開啟"
            "太多瀏覽器。個別來源的自動同步開關與頻率請到「同步中心」的"
            "來源卡片→「設定」調整。"
        )
        sync_note.setObjectName("MutedLabel")
        sync_note.setWordWrap(True)
        sync_form.addRow("", sync_note)

        layout.addWidget(sync_group)

        history_group = QGroupBox("同步歷史紀錄")
        history_form = QFormLayout(history_group)

        self.sync_history_retention_days = QSpinBox()
        self.sync_history_retention_days.setRange(1, 365)
        self.sync_history_retention_days.setSuffix(" 天")
        self.sync_history_retention_days.setValue(
            int(self.db.get_setting("sync_history_retention_days", "30") or 30)
        )
        history_form.addRow("同步歷史保留天數", self.sync_history_retention_days)

        sync_history_note = QLabel(
            "這裡只清除 sync_runs 同步紀錄列，不會刪除 property_changes"
            "（新增／異動／下架紀錄，未來分析可能會用到，這一輪不自動清除）。"
        )
        sync_history_note.setObjectName("MutedLabel")
        sync_history_note.setWordWrap(True)
        history_form.addRow("", sync_history_note)

        sync_cleanup_button = QPushButton("立即清理同步歷史")
        sync_cleanup_button.setObjectName("SecondaryButton")
        sync_cleanup_button.clicked.connect(self._cleanup_sync_history_now)
        history_form.addRow("", sync_cleanup_button)

        layout.addWidget(history_group)
        layout.addStretch()

        return _scrollable(content)

    def _cleanup_sync_history_now(self) -> None:
        removed = self.db.cleanup_old_sync_runs(self.sync_history_retention_days.value())
        QMessageBox.information(self, "已清理同步歷史", f"已清除 {removed} 筆超過保留天數的同步歷史紀錄。")

    # ------------------------------------------------------------------

    @staticmethod
    def _build_placeholder_tab(message: str) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 24, 12, 0)
        label = QLabel(message)
        label.setObjectName("MutedLabel")
        label.setWordWrap(True)
        layout.addWidget(label)
        layout.addStretch()
        return content

    # ------------------------------------------------------------------

    def save(self) -> None:
        settings = {
            "agent_name": self.name.text().strip(),
            "company_name": self.company.text().strip(),
            "video_outro": self.video_outro.toPlainText().strip(),
            "display_name": self.display_name.text().strip(),
            "service_area": self.service_area.text().strip(),
            "brand_slogan": self.slogan.toPlainText().strip(),
            "agent_phone": self.phone.text().strip(),
            "line_id": self.line_id.text().strip(),
            "agent_email": self.email.text().strip(),
            "default_cta": self.default_cta.toPlainText().strip(),
            "default_hashtags": self.default_hashtags.toPlainText().strip(),
            "brokerage_name": self.brokerage_name.text().strip(),
            "salesperson_name": self.salesperson_name.text().strip(),
            "salesperson_license": self.salesperson_license.text().strip(),
            "broker_name": self.broker_name.text().strip(),
            "broker_license": self.broker_license.text().strip(),
            "company_address": self.company_address.text().strip(),
            "company_phone": self.company_phone.text().strip(),
            "facebook_name": self.facebook_name.text().strip(),
            "facebook_profile_url": self.facebook_profile_url.text().strip(),
            "copy_style": self.copy_style.currentText(),
            "openai_api_key": self.api_key.text().strip(),
            "ai_enabled": "1" if self.ai_enabled.isChecked() else "0",
            "automation_enabled": "1" if self.automation_enabled.isChecked() else "0",
            "minimize_to_tray": "1" if self.minimize_to_tray.isChecked() else "0",
            "automation_check_interval_seconds": str(self.check_interval.value()),
            "automation_max_publish_retries": str(self.max_publish_retries.value()),
            "automation_delete_enabled": "1" if self.automation_delete_enabled.isChecked() else "0",
            "automation_default_delete_days": str(self.default_delete_days.value()),
            "automation_max_delete_retries": str(self.max_delete_retries.value()),
            "history_retention_days": str(self.history_retention_days.value()),
            "automation_sync_enabled": "1" if self.automation_sync_enabled.isChecked() else "0",
            "automation_sync_max_concurrent": str(self.automation_sync_max_concurrent.value()),
            "automation_sync_timeout_seconds": str(self.automation_sync_timeout_seconds.value()),
            "automation_sync_max_retries": str(self.automation_sync_max_retries.value()),
            "sync_history_retention_days": str(self.sync_history_retention_days.value()),
        }

        for key, value in settings.items():
            self.db.set_setting(key, value)

        if callable(self.on_saved):
            self.on_saved()

        QMessageBox.information(self, "儲存完成", "設定已儲存。")

    def reset_defaults(self) -> None:
        answer = QMessageBox.question(
            self,
            "恢復預設",
            "確定要清空這些欄位嗎？（不會自動還原成最初的種子資料）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        for widget in (
            self.name, self.company, self.display_name, self.service_area,
            self.phone, self.line_id, self.email, self.brokerage_name,
            self.salesperson_name, self.salesperson_license, self.broker_name,
            self.broker_license, self.company_address, self.company_phone,
            self.facebook_name, self.facebook_profile_url, self.api_key,
        ):
            widget.setText("")

        for widget in (self.video_outro, self.slogan, self.default_cta, self.default_hashtags):
            widget.setPlainText("")

        self.copy_style.setCurrentText("親切自然")
        self.ai_enabled.setChecked(False)

        QMessageBox.information(self, "已清空", "請確認內容後按「儲存設定」。")
