from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QObject, QThread, Signal

from app.services.database import Database
from app.services.facebook_service import FacebookService


class SchedulePublishRunner(QObject):
    """在背景 QThread 手動觸發單一排程的 Facebook 發布，避免卡住 UI 執行緒。

    呼叫端必須先把該筆排程的狀態改成 publishing（讓畫面立即反應），
    再呼叫 start()；這裡只負責實際發布與寫回結果。
    """

    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, db: Database, schedule: dict) -> None:
        super().__init__()
        self.db = db
        self.schedule = schedule
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

        # self 目前的 thread affinity 還是 self._qthread（一個事件迴圈
        # 已經停止的 QThread）。deleteLater() 必須由物件自己所屬的執行緒
        # 事件迴圈處理才會真的執行；那個迴圈已經停了，這個呼叫永遠不會
        # 觸發，且讓下一個 QThread 在同一個 process 裡啟動時出現卡住的
        # 情況。搬回建立這個 QThread 的主執行緒後再排入刪除。
        app = QCoreApplication.instance()
        if app is not None:
            self.moveToThread(app.thread())

        self.deleteLater()
        self._qthread.deleteLater()

    def _run(self) -> None:
        schedule_id = int(self.schedule["id"])
        target = str(self.schedule.get("target", "")).strip()
        content = str(self.schedule.get("copy_text", "")).strip()
        images_raw = str(self.schedule.get("images", "") or "")
        image_paths = [path for path in images_raw.split("\n") if path.strip()]

        try:
            facebook = FacebookService()
            report = facebook.publish_posts([target], content, image_paths)
            results = report.get("results", [])
            success = bool(results and results[0].get("success"))

            if success:
                self.db.mark_schedule_published(schedule_id)
                self.finished.emit(
                    {"schedule_id": schedule_id, "success": True, "message": "發布成功"}
                )
            else:
                message = (
                    str(results[0].get("message", "")) if results else ""
                ) or "發布失敗（未知原因）"
                self.db.mark_schedule_failed(schedule_id, message)
                self.finished.emit(
                    {"schedule_id": schedule_id, "success": False, "message": message}
                )

        except Exception as exc:
            self.db.mark_schedule_failed(schedule_id, str(exc))
            self.failed.emit(str(exc))
