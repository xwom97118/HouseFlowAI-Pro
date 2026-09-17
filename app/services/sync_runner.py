from __future__ import annotations

import threading
import time

from PySide6.QtCore import QCoreApplication, QObject, QThread, Signal

from app.services.database import Database
from app.services.sync_service import YungchingSyncService


class SyncRunner(QObject):
    """在背景 QThread 執行整店同步，避免卡住 PySide6 UI 執行緒。

    取消僅在「列表頁讀取階段」之間生效；一旦進入單一物件詳細資料／
    照片下載階段（ThreadPoolExecutor），目前批次仍會完成，避免中途
    中斷造成資料寫入到一半的不一致狀態。
    """

    progress = Signal(dict)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, db: Database, source: dict) -> None:
        super().__init__()
        self.db = db
        self.source = source
        self._cancel_event = threading.Event()
        self._qthread: QThread | None = None

    def cancel(self) -> None:
        self._cancel_event.set()

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

        # 搬回主執行緒再排入刪除，避免物件卡在一個事件迴圈已經停止的
        # QThread 上（deleteLater 需要物件自己所屬執行緒的事件迴圈處理）。
        app = QCoreApplication.instance()
        if app is not None:
            self.moveToThread(app.thread())

        self.deleteLater()
        self._qthread.deleteLater()

    def _run(self) -> None:
        source_id = self.source.get("id")
        source_url = str(self.source.get("url", "")).strip()
        run_id = self.db.create_sync_run(source_id, source_url)
        service = YungchingSyncService()
        started = time.perf_counter()

        try:
            def on_progress(payload: dict) -> None:
                self.progress.emit(payload)

            result = service.fetch(
                source_url,
                progress_callback=on_progress,
                cancel_event=self._cancel_event,
            )

            full_success = not result.had_failures and result.found > 0

            counts = self.db.sync_properties_for_source(
                result.properties,
                source_url=source_url,
                source_id=source_id,
                sync_run_id=run_id,
                mark_offline=full_success,
            )

            if result.cancelled:
                status = "cancelled"
            elif result.had_failures:
                status = "partial"
            else:
                status = "success"

            duration = result.duration_seconds or int(time.perf_counter() - started)

            self.db.finish_sync_run(
                run_id,
                status=status,
                found_count=result.found,
                new_count=counts["new"],
                updated_count=counts["updated"],
                offline_count=counts["offline"],
                failed_count=len(result.failed_pages),
                duration_seconds=duration,
                error_message=result.message,
            )

            if source_id is not None:
                self.db.touch_sync_source_last_sync(source_id)

            self.finished.emit(
                {
                    "run_id": run_id,
                    "status": status,
                    "counts": counts,
                    "found": result.found,
                    "message": result.message,
                }
            )

        except Exception as exc:
            self.db.finish_sync_run(
                run_id,
                status="failed",
                duration_seconds=int(time.perf_counter() - started),
                error_message=str(exc),
            )
            self.failed.emit(str(exc))
