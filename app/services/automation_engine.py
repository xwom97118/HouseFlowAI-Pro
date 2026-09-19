from __future__ import annotations

import time
import traceback
import uuid
from typing import Any

from PySide6.QtCore import QCoreApplication, QObject, Qt, QThread, QTimer, Signal

from app.services.automation_logger import log_event, log_heartbeat
from app.services.database import Database
from app.services.facebook_service import FacebookService
from app.services.sync_runner import SyncAlreadyRunningError, execute_source_sync
from app.services.sync_service import YungchingSyncService

# App 剛啟動時先不要立刻打一堆 network request 影響 startup UX——啟動後
# 這段時間內，即使有到期的 auto sync source，tick 也不會去處理它。
SYNC_STARTUP_DELAY_SECONDS = 20

# 明確判定為「登入/安全驗證問題」的關鍵字 —— 這些直接沿用
# facebook_service.py 既有 _raise_if_blocked() 本來就會拋出的訊息內容，
# 不是憑空猜的。出現這些字時，Automation Engine 會整批暫停 Facebook
# 工作（發布跟刪除都停），而不是繼續對同一個 target 重試。
LOGIN_ISSUE_KEYWORDS = (
    "安全驗證",
    "確認你的身分",
    "帳號暫時受限",
    "操作遭封鎖",
    "security check",
    "confirm your identity",
    "temporarily blocked",
    "action blocked",
    "登入",
    "log in",
    "login",
)

# 結果不確定（可能已經送出但沒等到完成確認），不能自動重發，避免重複貼文。
AMBIGUOUS_KEYWORDS = ("timeout", "逾時", "timed out")

# 發布 / 刪除失敗重試的等待時間（分鐘），依 attempt 次數遞增。
PUBLISH_RETRY_BACKOFF_MINUTES = (5, 30, 120)
DELETE_RETRY_BACKOFF_MINUTES = (5, 30, 120)

STALE_PUBLISHING_MINUTES = 10


def classify_failure(message: str) -> str:
    """回傳 'login_required' / 'needs_review' / 'failed' 三種之一。"""
    lowered = (message or "").lower()
    if any(keyword.lower() in lowered for keyword in LOGIN_ISSUE_KEYWORDS):
        return "login_required"
    if any(keyword.lower() in lowered for keyword in AMBIGUOUS_KEYWORDS):
        return "needs_review"
    return "failed"


class AutomationCycleWorker(QObject):
    """在背景 QThread 執行一次完整的檢查週期：復原卡住的工作、處理到期
    發布、處理到期刪文。每一筆的 claim 都是 DB 層的 atomic UPDATE，
    這個 worker 本身可以放心被同時觸發也不會造成重複發文/刪文 —— 真正
    的保護在 database.py 的 claim_schedule_for_publish/_delete。
    """

    finished = Signal(dict)
    failed = Signal(str)

    def __init__(
        self,
        db: Database,
        max_publish_retries: int,
        max_delete_retries: int,
        facebook_factory=FacebookService,
        sync_service_factory=YungchingSyncService,
        sync_phase_enabled: bool = True,
    ) -> None:
        super().__init__()
        self.db = db
        self.max_publish_retries = max_publish_retries
        self.max_delete_retries = max_delete_retries
        self.facebook_factory = facebook_factory
        self.sync_service_factory = sync_service_factory
        self.sync_phase_enabled = sync_phase_enabled
        self._qthread: QThread | None = None

    def start(self) -> None:
        self._qthread = QThread()
        self.moveToThread(self._qthread)
        self._qthread.started.connect(self._run)
        # DirectConnection：quit() 要在 worker 執行緒 emit finished 的當下就
        # 立刻執行（thread-safe，可跨執行緒呼叫），不能排到主執行緒佇列後面
        # 才處理——呼叫端（AutomationEngine._start_cycle）比這裡先連上
        # finished/failed，兩個 slot 都是 QueuedConnection 的話，呼叫端的
        # handler 會先跑，裡面呼叫的 wait_and_cleanup() 會卡住主執行緒事件
        # 佇列，擋住還沒被處理的 quit()，變成整整卡到 timeout（實測造成 ~5
        # 秒的 GUI 凍結）。改成 DirectConnection 後 quit() 不用排隊，
        # wait() 才能幾乎立刻回傳。
        self.finished.connect(self._qthread.quit, Qt.ConnectionType.DirectConnection)
        self.failed.connect(self._qthread.quit, Qt.ConnectionType.DirectConnection)
        self._qthread.start()

    def wait_and_cleanup(self, timeout_ms: int = 5000) -> None:
        if self._qthread is None:
            return
        self._qthread.wait(timeout_ms)
        app = QCoreApplication.instance()
        if app is not None:
            self.moveToThread(app.thread())
        self.deleteLater()
        self._qthread.deleteLater()

    def _run(self) -> None:
        summary = {
            "published": 0,
            "failed": 0,
            "needs_review": 0,
            "deleted": 0,
            "delete_failed": 0,
            "manual_delete_required": 0,
            "login_required": False,
            "sync_success": 0,
            "sync_failed": 0,
            "sync_new": 0,
            "sync_price_changed": 0,
            "sync_offline": 0,
        }

        try:
            log_heartbeat("cycle starting")
            self._recover_stale(summary)
            login_blocked = self._process_publishes(summary)
            if not login_blocked:
                self._process_deletes(summary)
            # Auto Sync 跟 Facebook 發文/刪文完全獨立——Facebook 登入卡住
            # 不該影響同步整店物件，反過來同步失敗也不該擋住 Facebook 工作，
            # 所以這裡永遠執行，不看 login_blocked。
            self._process_due_sync_sources(summary)
            self.finished.emit(summary)
        except Exception as exc:
            self.failed.emit(str(exc))

    def _recover_stale(self, summary: dict[str, Any]) -> None:
        stale = self.db.list_stale_publishing(STALE_PUBLISHING_MINUTES)
        for row in stale:
            self.db.mark_schedule_needs_review(
                row["id"],
                "APP 重新啟動時發現這筆卡在「發布中」超過合理時間，"
                "無法確認 Facebook 是否已經真的發布成功，需要人工確認。",
            )
            summary["needs_review"] += 1
            log_event("recovery", f"schedule_id={row['id']} 卡在 publishing，標記 needs_review")

    def _process_publishes(self, summary: dict[str, Any]) -> bool:
        """回傳 True 代表這次週期遇到登入/安全驗證問題，呼叫端應該跳過
        刪文階段（同一個 Facebook session 有問題，繼續操作沒有意義）。
        """
        due = self.db.list_due_publish_schedules()

        for row in due:
            schedule_id = int(row["id"])
            token = uuid.uuid4().hex

            if not self.db.claim_schedule_for_publish(schedule_id, token):
                continue  # 被其他呼叫搶先 claim，跳過。

            log_event("job_claimed", f"schedule_id={schedule_id} type=publish token={token[:8]}")

            attempt_number = int(row.get("retry_count", 0)) + 1
            execution_id = self.db.create_execution(
                schedule_id, "publish", attempt_number, token
            )

            target = str(row.get("target", "")).strip()
            copy_text = str(row.get("copy_text", ""))
            images_raw = str(row.get("images", "") or "")
            image_paths = [p for p in images_raw.split("\n") if p.strip()]

            try:
                facebook = self.facebook_factory()
                report = facebook.publish_posts([target], copy_text, image_paths)
                results = report.get("results", [])
                result = results[0] if results else {"success": False, "message": "沒有回傳結果"}
            except Exception as exc:
                # 不能只留 str(exc)（例如單純一句「[WinError 2] 系統找不到
                # 指定的檔案」）——加上例外類型，並把完整 traceback 寫進
                # log，2026-09-19 的事故就是靠這個才追出真正原因。
                result = {"success": False, "message": f"{type(exc).__name__}: {exc}"}
                log_event(
                    "publish_exception",
                    f"schedule_id={schedule_id} {type(exc).__name__}: {exc}\n{traceback.format_exc()}",
                )

            if result.get("success"):
                # 注意：facebook_service.publish_posts() 目前不會回傳可靠
                # 的貼文網址/ID（見 delete_post() 的說明），所以這裡不猜，
                # post_url/post_id 留空，代表這個 target 之後無法自動刪文
                # （只能人工刪除）。
                self.db.mark_schedule_published(schedule_id, post_url="", post_id="")
                self.db.finish_execution(execution_id, "success")
                summary["published"] += 1
                # post_url/post_id 目前永遠是空字串（見上方註解），記錄下來
                # 是刻意的——之後補上可靠識別方式時，這行 log 格式不用改。
                log_event("publish_success", f"schedule_id={schedule_id} post_url= post_id=")
                continue

            message = str(result.get("message", "") or "未知錯誤")
            classification = classify_failure(message)

            if classification == "login_required":
                # 不重試、不消耗 retry 次數 —— 把它放回 scheduled，
                # 等使用者重新登入、engine 恢復後自然會再撿起來。
                self.db.schedule_publish_retry(schedule_id, {"minutes": 0}, message)
                self.db.finish_execution(execution_id, "needs_review", message)
                summary["login_required"] = True
                log_event("login_required", f"schedule_id={schedule_id} reason={message}")
                return True

            if classification == "needs_review":
                self.db.mark_schedule_needs_review(schedule_id, message)
                self.db.finish_execution(execution_id, "needs_review", message)
                summary["needs_review"] += 1
                log_event("publish_needs_review", f"schedule_id={schedule_id} reason={message}")
                continue

            # classification == "failed"：明確失敗，可以照規則重試。
            if attempt_number >= self.max_publish_retries:
                self.db.mark_schedule_failed(schedule_id, message)
                self.db.finish_execution(execution_id, "failed", message)
                summary["failed"] += 1
                log_event(
                    "publish_failed",
                    f"schedule_id={schedule_id} attempt={attempt_number}（終止重試） reason={message}",
                )
            else:
                backoff_minutes = PUBLISH_RETRY_BACKOFF_MINUTES[
                    min(attempt_number - 1, len(PUBLISH_RETRY_BACKOFF_MINUTES) - 1)
                ]
                self.db.schedule_publish_retry(schedule_id, {"minutes": backoff_minutes}, message)
                self.db.finish_execution(execution_id, "failed", message)
                log_event(
                    "publish_retry_scheduled",
                    f"schedule_id={schedule_id} attempt={attempt_number} 等待 {backoff_minutes} 分鐘 reason={message}",
                )

        return False

    def _process_deletes(self, summary: dict[str, Any]) -> None:
        due = self.db.list_due_delete_schedules()

        for row in due:
            schedule_id = int(row["id"])
            remote_post_url = str(row.get("post_url", "")).strip()

            # 安全閘門：沒有可靠 remote 識別，絕對不能刪、也不能猜。
            if not remote_post_url:
                self.db.mark_delete_manual_required(
                    schedule_id, "沒有可靠的 remote_post_url，無法自動刪除。"
                )
                summary["manual_delete_required"] += 1
                log_event("delete_manual_required", f"schedule_id={schedule_id} 沒有可靠的 post_url")
                continue

            token = uuid.uuid4().hex
            if not self.db.claim_schedule_for_delete(schedule_id, token):
                continue

            log_event("job_claimed", f"schedule_id={schedule_id} type=delete token={token[:8]}")

            attempt_number = int(row.get("delete_attempt_count", 0)) + 1
            execution_id = self.db.create_execution(
                schedule_id, "delete", attempt_number, token
            )

            try:
                facebook = self.facebook_factory()
                result = facebook.delete_post(remote_post_url)
            except Exception as exc:
                result = {"success": False, "message": str(exc)}

            if result.get("success"):
                self.db.mark_schedule_deleted(schedule_id)
                self.db.finish_execution(execution_id, "success")
                summary["deleted"] += 1
                log_event("delete_success", f"schedule_id={schedule_id}")
                continue

            message = str(result.get("message", "") or "未知錯誤")
            classification = classify_failure(message)

            if classification == "login_required":
                self.db.schedule_delete_retry(schedule_id, {"minutes": 0}, message)
                self.db.finish_execution(execution_id, "needs_review", message)
                summary["login_required"] = True
                log_event("login_required", f"schedule_id={schedule_id} (delete)")
                return

            if attempt_number >= self.max_delete_retries:
                self.db.mark_delete_failed_terminal(schedule_id, message)
                self.db.finish_execution(execution_id, "failed", message)
                summary["delete_failed"] += 1
                log_event("delete_failed", f"schedule_id={schedule_id} attempt={attempt_number}（終止重試）")
            else:
                backoff_minutes = DELETE_RETRY_BACKOFF_MINUTES[
                    min(attempt_number - 1, len(DELETE_RETRY_BACKOFF_MINUTES) - 1)
                ]
                self.db.schedule_delete_retry(schedule_id, {"minutes": backoff_minutes}, message)
                self.db.finish_execution(execution_id, "failed", message)
                log_event(
                    "delete_retry_scheduled",
                    f"schedule_id={schedule_id} attempt={attempt_number} 等待 {backoff_minutes} 分鐘",
                )

    def _process_due_sync_sources(self, summary: dict[str, Any]) -> None:
        """跟發文/刪文用一樣的「查 due → atomic claim → 執行 → 分類結果」
        模式，但實際同步邏輯直接呼叫 execute_source_sync()（跟手動「立即
        同步」共用同一個 pipeline，見 sync_runner.py），不是另外兜一套。

        本版同一個 tick 只 sequential 處理，不會同時開很多 Chromium。
        """
        if not self.sync_phase_enabled:
            return
        if self.db.get_setting("automation_sync_enabled", "1") != "1":
            return

        max_retries = self._sync_int_setting("automation_sync_max_retries", 3)
        max_concurrent = max(1, self._sync_int_setting("automation_sync_max_concurrent", 1))

        due = self.db.list_due_sync_sources(limit=max_concurrent)

        for source in due:
            source_id = int(source["id"])
            try:
                payload = execute_source_sync(
                    self.db, source, service_factory=self.sync_service_factory,
                    max_retries=max_retries,
                )
            except SyncAlreadyRunningError:
                # 手動「立即同步」正在跑同一個來源，這個 tick 安靜跳過。
                continue
            except Exception as exc:
                summary["sync_failed"] += 1
                log_event("sync_failed", f"source_id={source_id} error={exc}")
                continue

            status = payload["status"]
            counts = payload.get("counts", {})
            if status == "success":
                summary["sync_success"] += 1
                summary["sync_new"] += counts.get("new", 0)
                summary["sync_price_changed"] += counts.get("price_changed", 0)
                summary["sync_offline"] += counts.get("offline", 0)
                log_event(
                    "sync_success",
                    f"source_id={source_id} found={payload['found']} new={counts.get('new', 0)} "
                    f"price_changed={counts.get('price_changed', 0)} offline={counts.get('offline', 0)}",
                )
            elif status in ("partial", "suspicious"):
                summary["sync_success"] += 1
                log_event("sync_" + status, f"source_id={source_id} found={payload['found']}")
            else:
                summary["sync_failed"] += 1
                log_event("sync_" + status, f"source_id={source_id}")

        # 明確失敗（例外）的來源已經在 execute_source_sync() 內部處理過
        # retry/needs_review 的狀態轉移，這裡不用重複做。

    def _sync_int_setting(self, key: str, default: int) -> int:
        try:
            return int(self.db.get_setting(key, str(default)))
        except ValueError:
            return default


class AutomationEngine(QObject):
    """常駐在主執行緒的排程器：用 QTimer 定期（預設 30 秒）觸發一次
    AutomationCycleWorker，週期本身在背景 QThread 執行，不會卡住 UI。

    不是為每一筆 schedule 建立一個 QTimer；固定用「中央排程器定期查
    due jobs」的模式。
    """

    status_changed = Signal(str, str)  # (text, kind) -- kind 給 StatusBadge 用
    notify = Signal(str)  # tray 通知文字
    cycle_finished = Signal()  # 給 UI 刷新用（不帶資料，UI 自己重新 query）
    login_required = Signal()

    def __init__(
        self,
        db: Database,
        facebook_factory=FacebookService,
        sync_service_factory=YungchingSyncService,
    ) -> None:
        super().__init__()
        self.db = db
        self.facebook_factory = facebook_factory
        self.sync_service_factory = sync_service_factory

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)

        self._worker: AutomationCycleWorker | None = None
        self._paused = False
        self._login_blocked = False
        self._rerun_requested = False
        self._started = False
        self._start_monotonic: float | None = None
        self._force_sync_next_cycle = False

    # ------------------------------------------------------------------
    # 生命週期
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._start_monotonic = time.monotonic()
        self._apply_interval_from_settings()
        enabled = self.db.get_setting("automation_enabled", "1") == "1"
        self._paused = not enabled
        self._timer.start()
        self._emit_status()
        log_event("automation_started", f"paused={self._paused}")

    def stop(self) -> None:
        self._timer.stop()
        if self._worker is not None:
            self._worker.wait_and_cleanup()
            self._worker = None
        self._started = False
        log_event("automation_stopped")

    def pause(self) -> None:
        self._paused = True
        self.db.set_setting("automation_enabled", "0")
        self._emit_status()
        log_event("automation_paused")

    def resume(self) -> None:
        self._paused = False
        self._login_blocked = False
        self.db.set_setting("automation_enabled", "1")
        self._emit_status()
        log_event("automation_resumed")

    def is_paused(self) -> bool:
        return self._paused

    def reload_interval_from_settings(self) -> None:
        self._apply_interval_from_settings()

    def sync_from_settings(self) -> None:
        """設定頁儲存後呼叫：讓正在跑的 engine 立刻反映新的檢查間隔跟
        啟用/停用開關，不用等使用者重開 app。設定本身已經被 Settings
        頁存進 DB，這裡只是同步記憶體中的執行狀態。
        """
        self._apply_interval_from_settings()
        enabled = self.db.get_setting("automation_enabled", "1") == "1"
        if self._paused != (not enabled):
            self._paused = not enabled
            self._emit_status()

    def _apply_interval_from_settings(self) -> None:
        try:
            seconds = int(self.db.get_setting("automation_check_interval_seconds", "30"))
        except ValueError:
            seconds = 30
        seconds = max(5, seconds)
        self._timer.setInterval(seconds * 1000)

    # ------------------------------------------------------------------
    # 觸發
    # ------------------------------------------------------------------

    def trigger_now(self) -> None:
        """「立即檢查排程」按鈕 / tray 選單用。跟 timer tick 走同一條路
        徑；如果目前已經有一個週期在跑，只是標記「跑完再跑一次」，
        不會另外開一個 worker 去跟目前的搶 DB。
        """
        if self._paused:
            return
        if self._worker is not None:
            self._rerun_requested = True
            return
        self._start_cycle()

    def sync_all_sources_now(self) -> None:
        """Tray「立即同步所有來源」用：強制這次 cycle 一定跑 sync 階段，
        繞過開機後的啟動延遲（使用者主動要求，不算是「一開機就打一堆
        network request」）。
        """
        self._force_sync_next_cycle = True
        self.trigger_now()

    def _sync_phase_ready(self) -> bool:
        if self._force_sync_next_cycle:
            return True
        if self._start_monotonic is None:
            return True
        return (time.monotonic() - self._start_monotonic) >= SYNC_STARTUP_DELAY_SECONDS

    def _on_tick(self) -> None:
        if self._paused or self._login_blocked:
            return
        if self._worker is not None:
            return
        self._start_cycle()

    def _start_cycle(self) -> None:
        max_publish_retries = self._int_setting("automation_max_publish_retries", 3)
        max_delete_retries = self._int_setting("automation_max_delete_retries", 3)
        sync_phase_enabled = self._sync_phase_ready()
        self._force_sync_next_cycle = False

        self._worker = AutomationCycleWorker(
            self.db, max_publish_retries, max_delete_retries, self.facebook_factory,
            sync_service_factory=self.sync_service_factory,
            sync_phase_enabled=sync_phase_enabled,
        )
        self._worker.finished.connect(self._on_cycle_finished)
        self._worker.failed.connect(self._on_cycle_failed)
        self._emit_status(kind="publishing", text="⏳ 正在檢查排程")
        self._worker.start()

    def _int_setting(self, key: str, default: int) -> int:
        try:
            return int(self.db.get_setting(key, str(default)))
        except ValueError:
            return default

    # ------------------------------------------------------------------
    # 週期結果處理
    # ------------------------------------------------------------------

    def _on_cycle_finished(self, summary: dict[str, Any]) -> None:
        if self._worker is not None:
            self._worker.wait_and_cleanup()
            self._worker = None

        if summary.get("login_required"):
            self._login_blocked = True
            self.login_required.emit()
            self.notify.emit("HouseFlow：Facebook 需要重新登入")
            self._emit_status(kind="danger", text="⚠ Facebook 需要重新登入")
        else:
            self._emit_status()
            self._maybe_notify(summary)

        self.cycle_finished.emit()

        if self._rerun_requested and not self._paused and not self._login_blocked:
            self._rerun_requested = False
            self._start_cycle()

    def _on_cycle_failed(self, message: str) -> None:
        if self._worker is not None:
            self._worker.wait_and_cleanup()
            self._worker = None
        self._emit_status(kind="danger", text="● 自動化發生錯誤")
        self.cycle_finished.emit()

    def _maybe_notify(self, summary: dict[str, Any]) -> None:
        published = summary.get("published", 0)
        failed = summary.get("failed", 0) + summary.get("needs_review", 0)
        deleted = summary.get("deleted", 0)

        if published and not failed:
            self.notify.emit("HouseFlow：貼文發布完成")
        elif published and failed:
            total = published + failed
            self.notify.emit(f"HouseFlow：{published}/{total} 個發布位置成功")
        elif failed and not published:
            self.notify.emit("HouseFlow：有排程發布失敗，請到排程管理查看")

        if deleted:
            self.notify.emit("HouseFlow：到期貼文已刪除")

        sync_new = summary.get("sync_new", 0)
        sync_price_changed = summary.get("sync_price_changed", 0)
        sync_offline = summary.get("sync_offline", 0)
        sync_failed = summary.get("sync_failed", 0)

        # 完全沒有變更就不要一直跳通知——只有新增/異動/下架/失敗才通知。
        if sync_new or sync_price_changed or sync_offline:
            self.notify.emit(
                f"HouseFlow 同步完成\n新增 {sync_new}　價格異動 {sync_price_changed}　下架 {sync_offline}"
            )
        if sync_failed:
            self.notify.emit(f"⚠ HouseFlow：{sync_failed} 個來源同步失敗，將依規則自動重試")

    # ------------------------------------------------------------------
    # 狀態顯示
    # ------------------------------------------------------------------

    def _emit_status(self, kind: str = "", text: str = "") -> None:
        if text:
            self.status_changed.emit(text, kind or "info")
            return
        if self._paused:
            self.status_changed.emit("○ 自動化已暫停", "neutral")
        elif self._login_blocked:
            self.status_changed.emit("⚠ Facebook 需要重新登入", "danger")
        else:
            self.status_changed.emit("● 自動化運行中", "success")
