from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from app.services.database import Database
from app.services.import_runner import UniversalImportRunner


class UniversalImportDialog(QDialog):
    """任何公司單一物件網址匯入視窗。"""

    def __init__(
        self,
        db: Database,
        on_imported: Callable[[], None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self.db = db
        self.on_imported = on_imported
        self.runner: UniversalImportRunner | None = None

        self.setWindowTitle(
            "單一物件網址匯入"
        )
        self.resize(760, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(
            22,
            20,
            22,
            20,
        )
        root.setSpacing(14)

        title = QLabel(
            "萬用單一物件匯入"
        )
        title.setStyleSheet(
            "font-size:20px;font-weight:700;"
        )

        note = QLabel(
            "貼上任何房仲公司的單一物件公開網址，"
            "HouseFlow 會嘗試抓取標題、價格、地址、"
            "格局、坪數與照片。"
        )
        note.setWordWrap(True)
        note.setObjectName("MutedLabel")

        root.addWidget(title)
        root.addWidget(note)

        form = QFormLayout()

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText(
            "https://..."
        )
        form.addRow(
            "單一物件網址",
            self.url_input,
        )

        root.addLayout(form)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText(
            "匯入結果會顯示在這裡。"
        )
        root.addWidget(
            self.preview,
            1,
        )

        button_row = QHBoxLayout()

        self.close_button = QPushButton("關閉")
        self.close_button.setObjectName(
            "SecondaryButton"
        )
        self.close_button.clicked.connect(
            self.reject
        )

        self.import_button = QPushButton(
            "開始匯入"
        )
        self.import_button.setObjectName(
            "PrimaryButton"
        )
        self.import_button.clicked.connect(
            self.import_property
        )

        button_row.addStretch()
        button_row.addWidget(self.close_button)
        button_row.addWidget(
            self.import_button
        )

        root.addLayout(button_row)

    def reject(self) -> None:
        if self.runner is not None:
            # 匯入中：忽略 Esc / 視窗右上角關閉，避免中途砍掉背景執行緒。
            return
        super().reject()

    def import_property(self) -> None:
        if self.runner is not None:
            QMessageBox.information(self, "匯入進行中", "目前已有匯入正在執行，請稍候。")
            return

        url = self.url_input.text().strip()

        if not url:
            QMessageBox.warning(
                self,
                "尚未輸入網址",
                "請貼上單一物件網址。",
            )
            return

        self.import_button.setEnabled(False)
        self.close_button.setEnabled(False)
        self.preview.setPlainText("正在讀取物件頁面…")

        self.runner = UniversalImportRunner(self.db, url)
        self.runner.progress.connect(self._on_progress)
        self.runner.finished.connect(self._on_finished)
        self.runner.failed.connect(self._on_failed)
        self.runner.start()

    def _on_progress(self, payload: dict) -> None:
        message = str(payload.get("message", ""))
        if message:
            self.preview.setPlainText(message)

    def _on_finished(self, payload: dict) -> None:
        data = payload.get("property_data", {})
        saved = payload.get("saved", 0)

        preview_lines = [
            payload.get("message", ""),
            "",
            f"來源：{payload.get('source_name', '')}",
            f"標題：{data.get('title', '')}",
            f"總價：{data.get('price', '') or '未抓到'}",
            f"地址：{data.get('address', '') or '未抓到'}",
            f"格局：{data.get('layout', '') or '未抓到'}",
            f"坪數：{data.get('size', '') or '未抓到'}",
            f"類型：{data.get('property_type', '')}",
            f"照片：{data.get('image_count', 0)} 張",
            f"寫入資料庫：{saved} 筆",
        ]
        self.preview.setPlainText("\n".join(preview_lines))

        self._reset_buttons()

        if callable(self.on_imported):
            self.on_imported()

        QMessageBox.information(
            self,
            "匯入完成",
            (
                f"{data.get('title', '物件')}\n\n"
                f"已寫入 HouseFlow，"
                f"照片 {data.get('image_count', 0)} 張。"
            ),
        )

    def _on_failed(self, message: str) -> None:
        self.preview.setPlainText(f"匯入失敗：\n{message}")
        self._reset_buttons()
        QMessageBox.critical(self, "匯入失敗", message)

    def _reset_buttons(self) -> None:
        if self.runner is not None:
            self.runner.wait_and_cleanup()
        self.runner = None
        self.import_button.setEnabled(True)
        self.close_button.setEnabled(True)