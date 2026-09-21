"""License 相關 UI（2026-09-21 產品化 Phase 1）：Settings 頁的「授權
資訊」面板 + First Run / Activation 對話框原型（規格第 19 節 J、25
節）。

這一輪刻意「不」把 ActivationDialog 接進 MainWindow 的啟動流程——那
會改變 HouseFlow 每一次啟動的行為，屬於會影響現有使用方式的變更，
需要先給你驗收這個 UI 本身，再決定要不要接上真正的啟動流程。目前的
進入點是 Settings 頁「授權資訊」分頁裡的「開始試用／輸入 License
Key」按鈕，純手動觸發，不影響現有任何啟動路徑。
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.services.license import (
    DeviceLimitReachedError,
    LicenseError,
    LicenseService,
    LicenseStatus,
    TrialAlreadyUsedError,
    compute_device_fingerprint,
)
from app.services.license.fingerprint import current_device_name
from app.widgets.common import SectionTitle


class LicenseInfoPanel(QWidget):
    """Settings 頁「授權資訊」分頁：顯示方案、狀態、到期日、剩餘天數、
    裝置、最後驗證時間（規格第 19 節 J）。純顯示——實際啟用／續訂走
    ActivationDialog。
    """

    def __init__(self, license_service: LicenseService, get_setting, set_setting) -> None:
        super().__init__()
        self.license_service = license_service
        self.get_setting = get_setting
        self.set_setting = set_setting

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(12)

        root.addWidget(SectionTitle("授權資訊", "HouseFlow Professional 的訂閱狀態、到期日與裝置綁定。"))

        form = QFormLayout()
        self.plan_label = QLabel("—")
        self.status_label = QLabel("—")
        self.expires_label = QLabel("—")
        self.remaining_label = QLabel("—")
        self.device_label = QLabel("—")
        self.last_verified_label = QLabel("—")
        self.message_label = QLabel("")
        self.message_label.setWordWrap(True)
        self.message_label.setObjectName("MutedLabel")

        form.addRow("方案：", self.plan_label)
        form.addRow("狀態：", self.status_label)
        form.addRow("到期日：", self.expires_label)
        form.addRow("剩餘天數：", self.remaining_label)
        form.addRow("裝置：", self.device_label)
        form.addRow("最後驗證時間：", self.last_verified_label)
        root.addLayout(form)
        root.addWidget(self.message_label)

        button_row = QHBoxLayout()
        self.activate_button = QPushButton("開始試用／輸入 License Key")
        self.activate_button.setObjectName("PrimaryButton")
        self.activate_button.clicked.connect(self.open_activation_dialog)
        refresh_button = QPushButton("重新整理")
        refresh_button.setObjectName("SecondaryButton")
        refresh_button.clicked.connect(self.refresh)
        button_row.addWidget(self.activate_button)
        button_row.addWidget(refresh_button)
        button_row.addStretch()
        root.addLayout(button_row)

        self.refresh()

    def _device_fingerprint(self) -> str:
        return compute_device_fingerprint(self.get_setting, self.set_setting)

    def refresh(self) -> None:
        license_ = self.license_service.get_current_license()
        fingerprint = self._device_fingerprint()

        if license_ is None:
            self.plan_label.setText("—")
            self.status_label.setText("尚未開始試用")
            self.expires_label.setText("—")
            self.remaining_label.setText("—")
            self.device_label.setText("—")
            self.last_verified_label.setText("—")
            self.message_label.setText("點擊下方按鈕開始 7 天免費試用，或輸入 License Key。")
            self.activate_button.setText("開始試用／輸入 License Key")
            return

        result = self.license_service.check_license(fingerprint)

        plan_text = "HouseFlow Professional"
        if license_.is_early_bird and license_.locked_price:
            plan_text += f"（早鳥價 NT${license_.locked_price}/月）"
        self.plan_label.setText(plan_text)

        status_text = {
            LicenseStatus.TRIAL: "試用中",
            LicenseStatus.ACTIVE: "使用中",
            LicenseStatus.EXPIRED: "已到期",
            LicenseStatus.SUSPENDED: "已停權",
        }.get(result.effective_status, result.effective_status.value)
        if result.is_offline_grace:
            status_text += "（離線寬限期）"
        self.status_label.setText(status_text)

        self.expires_label.setText(license_.expires_at or license_.trial_ends_at or "—")
        self.remaining_label.setText(f"{result.days_remaining} 天" if result.days_remaining is not None else "—")
        self.device_label.setText(current_device_name())
        self.last_verified_label.setText(self.get_setting("license_last_verified_at", "") or "—")
        self.message_label.setText(result.message)
        self.activate_button.setText("續訂／重新輸入 License Key" if result.effective_status != LicenseStatus.TRIAL else "輸入 License Key")

    def open_activation_dialog(self) -> None:
        dialog = ActivationDialog(self.license_service, self.get_setting, self.set_setting, parent=self)
        dialog.exec()
        self.refresh()


class ActivationDialog(QDialog):
    """First Run / Activation 對話框原型（規格第 25 節）：開始試用，或
    輸入 License Key 啟用。這一輪是可以獨立測試、獨立開啟的 UI 原型，
    沒有接進 MainWindow 的啟動流程（見本檔案開頭說明）。
    """

    def __init__(
        self,
        license_service: LicenseService,
        get_setting,
        set_setting,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.license_service = license_service
        self.get_setting = get_setting
        self.set_setting = set_setting

        self.setWindowTitle("歡迎使用 HouseFlow")
        self.resize(480, 360)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(16)

        root.addWidget(SectionTitle("歡迎使用 HouseFlow", "開始 7 天免費試用，或輸入 License Key。"))

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        # ---- 選擇畫面 ----
        choice_page = QWidget()
        choice_layout = QVBoxLayout(choice_page)
        choice_layout.setSpacing(12)

        trial_button = QPushButton("開始 7 天免費試用（完整功能，不需信用卡）")
        trial_button.setObjectName("PrimaryButton")
        trial_button.clicked.connect(self.start_trial)
        choice_layout.addWidget(trial_button)

        key_button = QPushButton("我已經有 License Key")
        key_button.setObjectName("SecondaryButton")
        key_button.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        choice_layout.addWidget(key_button)
        choice_layout.addStretch()
        self.stack.addWidget(choice_page)

        # ---- License Key 輸入畫面 ----
        key_page = QWidget()
        key_layout = QVBoxLayout(key_page)
        key_layout.setSpacing(12)
        form = QFormLayout()
        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("HF-PRO-XXXX-XXXX-XXXX")
        form.addRow("License Key：", self.key_input)
        key_layout.addLayout(form)

        key_button_row = QHBoxLayout()
        back_button = QPushButton("← 返回")
        back_button.setObjectName("SecondaryButton")
        back_button.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        activate_button = QPushButton("啟用")
        activate_button.setObjectName("PrimaryButton")
        activate_button.clicked.connect(self.activate_key)
        key_button_row.addWidget(back_button)
        key_button_row.addStretch()
        key_button_row.addWidget(activate_button)
        key_layout.addLayout(key_button_row)
        key_layout.addStretch()
        self.stack.addWidget(key_page)

        close_button = QPushButton("關閉")
        close_button.setObjectName("SecondaryButton")
        close_button.clicked.connect(self.reject)
        root.addWidget(close_button)

    def _device_fingerprint(self) -> str:
        return compute_device_fingerprint(self.get_setting, self.set_setting)

    def start_trial(self) -> None:
        try:
            self.license_service.start_trial(self._device_fingerprint(), current_device_name())
        except TrialAlreadyUsedError as exc:
            QMessageBox.warning(self, "無法開始試用", str(exc))
            return
        except LicenseError as exc:
            QMessageBox.critical(self, "開始試用失敗", str(exc))
            return
        QMessageBox.information(self, "試用已開始", "7 天免費試用已開始，祝使用愉快！")
        self.accept()

    def activate_key(self) -> None:
        key = self.key_input.text().strip()
        if not key:
            QMessageBox.warning(self, "請輸入 License Key", "License Key 不能是空白。")
            return
        try:
            self.license_service.activate_license(key, self._device_fingerprint(), current_device_name())
        except DeviceLimitReachedError as exc:
            QMessageBox.critical(self, "裝置數已達上限", str(exc))
            return
        except (LicenseError, LookupError) as exc:
            QMessageBox.critical(self, "啟用失敗", str(exc))
            return
        QMessageBox.information(self, "啟用成功", "HouseFlow Professional 已啟用。")
        self.accept()
