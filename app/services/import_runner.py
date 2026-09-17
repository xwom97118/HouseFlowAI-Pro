from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal

from app.services.database import Database
from app.services.universal_import_service import UniversalPropertyImportService


class UniversalImportRunner(QObject):
    """在背景 QThread 執行單一物件網址匯入，避免卡住 UI 執行緒。"""

    progress = Signal(dict)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, db: Database, url: str) -> None:
        super().__init__()
        self.db = db
        self.url = url
        self._qthread: QThread | None = None

    def start(self) -> None:
        self._qthread = QThread()
        self.moveToThread(self._qthread)
        self._qthread.started.connect(self._run)
        self.finished.connect(self._qthread.quit)
        self.failed.connect(self._qthread.quit)
        self._qthread.start()

    def wait_and_cleanup(self, timeout_ms: int = 5000) -> None:
        if self._qthread is None:
            return
        self._qthread.wait(timeout_ms)
        self.deleteLater()
        self._qthread.deleteLater()

    def _run(self) -> None:
        service = UniversalPropertyImportService()
        try:
            def on_progress(payload: dict) -> None:
                self.progress.emit(payload)

            result = service.import_url(self.url, progress_callback=on_progress)
            data = result.property_data
            data.setdefault("source_site", result.source_name)

            saved = self.db.upsert_properties([data], source_url=self.url)

            self.finished.emit(
                {
                    "message": result.message,
                    "property_data": data,
                    "source_name": result.source_name,
                    "saved": saved,
                }
            )
        except Exception as exc:
            self.failed.emit(str(exc))
