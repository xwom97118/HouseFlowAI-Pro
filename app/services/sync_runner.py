from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable

from PySide6.QtCore import QCoreApplication, QObject, Qt, QThread, Signal

from app.services.database import Database
from app.services.sync_service import YungchingSyncService


class SyncAlreadyRunningError(Exception):
    """這個來源已經有同步在進行中——手動按「立即同步」跟 Automation tick
    互相排斥用；不是真正的錯誤，呼叫端應該安靜跳過，不要當成失敗。
    """


def execute_source_sync(
    db: Database,
    source: dict[str, Any],
    service_factory: Callable[[], YungchingSyncService] = YungchingSyncService,
    progress_callback: Callable[[dict], None] | None = None,
    cancel_event: threading.Event | None = None,
    max_retries: int = 3,
) -> dict[str, Any]:
    """完整同步一個來源：fetch → 分類結果 → 寫入 DB → 更新來源的下一次
    同步時間／重試狀態。手動同步（SyncRunner，包在 QThread 裡）跟自動
    同步（AutomationCycleWorker，本身已經在背景執行緒）都呼叫這一個
    函式，確保走完全相同的 pipeline，不會出現「手動一套、自動一套」
    兩邊分別長 bug 的情況。

    對有真正 sync_source id 的來源會先做 atomic claim（sync_status
    idle -> syncing）；claim 不到代表已經有別的呼叫（手動或自動）在
    同步這個來源，這裡直接拋 SyncAlreadyRunningError，呼叫端各自決定
    怎麼處理（手動：告訴使用者同步中；自動：安靜跳過，等下一個 tick）。
    """
    source_id = source.get("id")
    source_url = str(source.get("url", "")).strip()

    token = uuid.uuid4().hex
    if source_id is not None:
        if not db.claim_sync_source_for_sync(int(source_id), token):
            raise SyncAlreadyRunningError(f"來源 {source_id} 已經有同步正在進行中。")

    run_id = db.create_sync_run(source_id, source_url)
    started = time.perf_counter()

    try:
        service = service_factory()
        result = service.fetch(
            source_url,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
        )

        previous_active = (
            db.count_active_properties_for_source(int(source_id)) if source_id is not None else 0
        )
        # 整次同步結果疑似不完整（例如平常 60 筆這次只抓到 0～2 筆）：
        # 不能拿這次的「沒看到」去推進任何物件的下線倒數，只能老實記錄
        # 這次同步可疑，等下一次正常同步再判斷。見 TEST J/K。
        suspicious = result.found == 0 or (
            previous_active > 5 and result.found < max(3, int(previous_active * 0.15))
        )
        full_success = not result.had_failures and result.found > 0
        mark_offline = full_success and not suspicious

        counts = db.sync_properties_for_source(
            result.properties,
            source_url=source_url,
            source_id=source_id,
            sync_run_id=run_id,
            mark_offline=mark_offline,
        )

        if result.cancelled:
            status = "cancelled"
        elif suspicious:
            status = "suspicious"
        elif result.had_failures:
            status = "partial"
        else:
            status = "success"

        duration = result.duration_seconds or int(time.perf_counter() - started)
        error_message = result.message if status in ("suspicious", "partial") else ""

        db.finish_sync_run(
            run_id,
            status=status,
            found_count=result.found,
            new_count=counts["new"],
            updated_count=counts["updated"],
            offline_count=counts["offline"],
            failed_count=len(result.failed_pages),
            duration_seconds=duration,
            error_message=error_message,
        )

        if source_id is not None:
            if status in ("success", "partial", "suspicious"):
                if status == "success":
                    db.mark_sync_source_success(int(source_id))
                else:
                    db.mark_sync_source_partial_or_suspicious(
                        int(source_id), status, error_message
                    )
            # cancelled：使用者自己按了取消，不算失敗也不算成功，來源狀態
            # 維持不變（保留 sync_status idle 讓下次可以正常重新嘗試）。
            elif status == "cancelled":
                db.mark_sync_source_partial_or_suspicious(int(source_id), "cancelled", "")

        return {
            "run_id": run_id,
            "status": status,
            "counts": counts,
            "found": result.found,
            "message": result.message,
        }

    except Exception as exc:
        duration = int(time.perf_counter() - started)
        db.finish_sync_run(
            run_id, status="failed", duration_seconds=duration, error_message=str(exc)
        )
        if source_id is not None:
            db.mark_sync_source_retry_or_fail(int(source_id), str(exc), max_retries=max_retries)
        raise


class SyncRunner(QObject):
    """在背景 QThread 執行整店同步（手動觸發），避免卡住 PySide6 UI
    執行緒。實際同步邏輯在 execute_source_sync()，跟 Automation Engine
    的自動同步共用。

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
        # DirectConnection：見 automation_engine.py/schedule_runner.py 的
        # 註解——quit() 要在背景執行緒 emit finished 的當下立刻執行，不能
        # 排到主執行緒佇列後面，否則 wait_and_cleanup() 的 wait() 會卡到
        # timeout 才回傳（實測會造成數秒 GUI 凍結）。
        self.finished.connect(self._qthread.quit, Qt.ConnectionType.DirectConnection)
        self.failed.connect(self._qthread.quit, Qt.ConnectionType.DirectConnection)
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
        try:
            payload = execute_source_sync(
                self.db,
                self.source,
                progress_callback=self.progress.emit,
                cancel_event=self._cancel_event,
            )
            self.finished.emit(payload)
        except SyncAlreadyRunningError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc))
