from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import (
    QApplication,
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
from app.services.universal_import_service import (
    UniversalPropertyImportService,
)


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
        self.service = (
            UniversalPropertyImportService()
        )

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

        close_button = QPushButton("關閉")
        close_button.setObjectName(
            "SecondaryButton"
        )
        close_button.clicked.connect(
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
        button_row.addWidget(close_button)
        button_row.addWidget(
            self.import_button
        )

        root.addLayout(button_row)

    def import_property(self) -> None:
        url = self.url_input.text().strip()

        if not url:
            QMessageBox.warning(
                self,
                "尚未輸入網址",
                "請貼上單一物件網址。",
            )
            return

        self.import_button.setEnabled(False)
        self.preview.setPlainText(
            "正在讀取網頁與下載照片，請稍候……"
        )
        QApplication.processEvents()

        try:
            result = self.service.import_url(
                url
            )
            data = result.property_data

            saved = self.db.upsert_properties(
                [data],
                source_url=url,
            )

            preview_lines = [
                result.message,
                "",
                f"來源：{result.source_name}",
                f"標題：{data.get('title', '')}",
                f"總價：{data.get('price', '') or '未抓到'}",
                f"地址：{data.get('address', '') or '未抓到'}",
                f"格局：{data.get('layout', '') or '未抓到'}",
                f"坪數：{data.get('size', '') or '未抓到'}",
                f"類型：{data.get('property_type', '')}",
                f"照片：{data.get('image_count', 0)} 張",
                f"寫入資料庫：{saved} 筆",
            ]
            self.preview.setPlainText(
                "\n".join(preview_lines)
            )

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

        except Exception as exc:
            self.preview.setPlainText(
                f"匯入失敗：\n{exc}"
            )
            QMessageBox.critical(
                self,
                "匯入失敗",
                str(exc),
            )

        finally:
            self.import_button.setEnabled(
                True
            )