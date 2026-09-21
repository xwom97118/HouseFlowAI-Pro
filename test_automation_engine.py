"""3.3 Automation Engine 的 mock 回歸測試——完全不碰真實 Facebook，
用注入的 MockFacebookService 驗證核心安全機制：

- atomic claim 防止重複發文/刪文
- 多個 target 互相獨立（部分成功不影響其他 target）
- 失敗重試有 backoff、不會 sleep()
- 結果不確定時進 needs_review，絕對不會自動重發
- 開機時卡在 publishing 的排程一律進 needs_review（crash recovery）
- 刪文安全閘門：沒有可靠 post_url 絕對不會呼叫 Facebook 刪除
- 取消自動刪除後到期也不會執行

用獨立的暫存 sqlite 檔案，不會動到 dev/production 的 houseflow.db。
直接執行：python test_automation_engine.py
"""
from __future__ import annotations

import sys
import tempfile
import uuid
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from app.services.automation_engine import AutomationCycleWorker
from app.services.database import Database

app = QCoreApplication(sys.argv)

tmp_path = Path(tempfile.gettempdir()) / f"houseflow_test_{uuid.uuid4().hex}.db"
db = Database(tmp_path)

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        failures.append(name)


def make_property() -> int:
    with db.connect() as conn:
        cur = conn.execute("INSERT INTO properties(title) VALUES ('測試物件')")
        return int(cur.lastrowid)


def make_schedule(
    property_id: int,
    target: str = "personal",
    scheduled_at: str | None = None,
    delete_after_days: int | None = None,
    batch_id: str = "",
) -> int:
    from app.services.database import now_local_str

    return db.create_schedule({
        "property_id": property_id,
        "target": target,
        "target_label": target,
        "copy_text": "測試文案",
        "images": "",
        "scheduled_at": scheduled_at or now_local_str(),
        "status": "scheduled",
        "delete_after_days": delete_after_days,
        "batch_id": batch_id,
    })


class MockFacebookService:
    """行為佇列由測試自己塞，先進先出。不接觸真實 Facebook/Playwright。"""

    queue: list[dict] = []

    def publish_posts(self, targets, copy_text, image_paths):
        behavior = MockFacebookService.queue.pop(0) if MockFacebookService.queue else {
            "success": True, "message": "ok"
        }
        return {"results": [behavior]}

    def delete_post(self, remote_post_url, expected_content_prefix="", expected_post_id=""):
        return MockFacebookService.queue.pop(0) if MockFacebookService.queue else {
            "success": True, "message": "deleted"
        }


def run_worker(max_publish_retries: int = 3, max_delete_retries: int = 3) -> dict:
    loop = QEventLoop()
    worker = AutomationCycleWorker(db, max_publish_retries, max_delete_retries, facebook_factory=MockFacebookService)
    result: dict = {}

    worker.finished.connect(lambda summary: (result.update(summary=summary), loop.quit()))
    worker.failed.connect(lambda msg: (result.update(error=msg), loop.quit()))
    worker.start()

    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    worker.wait_and_cleanup()
    app.processEvents()
    return result


def main() -> int:
    pid = make_property()

    # A：正常發布
    MockFacebookService.queue = [{"success": True, "message": "ok"}]
    sid_a = make_schedule(pid, target="A")
    run_worker()
    row = db.get_schedule(sid_a)
    check("A 正常發布 -> published", row["status"] == "published")
    check("A published_at 有寫入", bool(row["published_at"]))

    # B：重複保護（atomic claim）
    sid_b = make_schedule(pid, target="B")
    ok1 = db.claim_schedule_for_publish(sid_b, uuid.uuid4().hex)
    ok2 = db.claim_schedule_for_publish(sid_b, uuid.uuid4().hex)
    check("B 兩次同時 claim 只有一次成功", ok1 is True and ok2 is False)
    db.mark_schedule_published(sid_b)

    # C：多個 target，部分成功
    batch_id = uuid.uuid4().hex
    MockFacebookService.queue = [
        {"success": True, "message": "ok"},
        {"success": True, "message": "ok"},
        {"success": True, "message": "ok"},
        {"success": False, "message": "不明原因失敗"},
    ]
    for i in range(4):
        make_schedule(pid, target=f"grp{i}", batch_id=batch_id)
    run_worker()
    batch_rows = db.list_batch_schedules(batch_id)
    success_count = sum(1 for r in batch_rows if r["status"] == "published")
    check("C 4 個 target 中 3 個成功、互不影響", success_count == 3 and len(batch_rows) == 4)

    # D：明確失敗 -> 重試 + backoff，不是馬上重試
    sid_d = make_schedule(pid, target="D")
    MockFacebookService.queue = [{"success": False, "message": "明確失敗，可重試"}]
    run_worker()
    row = db.get_schedule(sid_d)
    check("D 明確失敗 -> 回到 scheduled 等重試", row["status"] == "scheduled")
    check("D retry_count 累加", row["retry_count"] == 1)
    check("D next_retry_at 有 backoff（不是立即重試）", bool(row["next_retry_at"]) and row["next_retry_at"] > row["scheduled_at"])

    # E：結果不確定（timeout）-> needs_review，不能自動重發
    sid_e = make_schedule(pid, target="E")
    MockFacebookService.queue = [{"success": False, "message": "連線 timeout"}]
    run_worker()
    row = db.get_schedule(sid_e)
    check("E 不確定結果 -> needs_review", row["status"] == "needs_review")
    db.resolve_needs_review(sid_e, "already_published")
    row = db.get_schedule(sid_e)
    check("E 人工確認「已發布」-> 標記 published", row["status"] == "published")

    # F：crash recovery，卡在 publishing 一律進 needs_review
    sid_f = make_schedule(pid, target="F")
    with db.connect() as conn:
        conn.execute(
            "UPDATE schedules SET status='publishing', started_at='2000-01-01 00:00:00' WHERE id=?",
            (sid_f,),
        )
    MockFacebookService.queue = []
    run_worker()
    row = db.get_schedule(sid_f)
    check("F 重啟後卡住的 publishing -> needs_review（絕不盲目重發）", row["status"] == "needs_review")

    # G：有可靠 remote id 的自動刪文
    sid_g = make_schedule(pid, target="G", delete_after_days=15)
    MockFacebookService.queue = [{"success": True, "message": "ok"}]
    run_worker()
    with db.connect() as conn:
        conn.execute(
            "UPDATE schedules SET post_url='https://facebook.com/fake_post_g', delete_at='2000-01-01 00:00:00' WHERE id=?",
            (sid_g,),
        )
    MockFacebookService.queue = [{"success": True, "message": "deleted"}]
    run_worker()
    row = db.get_schedule(sid_g)
    check("G 到期自動刪除執行成功", row["delete_status"] == "deleted" and bool(row["deleted_at"]))

    # H：沒有可靠識別 -> 絕對不呼叫 Facebook 刪除
    sid_h = make_schedule(pid, target="H", delete_after_days=15)
    MockFacebookService.queue = [{"success": True, "message": "ok"}]
    run_worker()
    with db.connect() as conn:
        conn.execute("UPDATE schedules SET delete_at='2000-01-01 00:00:00' WHERE id=?", (sid_h,))
    MockFacebookService.queue = [{"success": True, "message": "SHOULD NOT BE CALLED"}]
    run_worker()
    row = db.get_schedule(sid_h)
    check("H 沒有 post_url -> manual_required", row["delete_status"] == "manual_required")
    check("H Facebook 刪除方法完全沒被呼叫", len(MockFacebookService.queue) == 1)
    MockFacebookService.queue = []

    # I：多個刪除 target 互相獨立
    sid_i1 = make_schedule(pid, target="I1", delete_after_days=1)
    sid_i2 = make_schedule(pid, target="I2", delete_after_days=1)
    MockFacebookService.queue = [{"success": True, "message": "ok"}, {"success": True, "message": "ok"}]
    run_worker()
    with db.connect() as conn:
        conn.execute(
            "UPDATE schedules SET post_url='https://facebook.com/i1', delete_at='2000-01-01 00:00:00' WHERE id=?",
            (sid_i1,),
        )
        conn.execute("UPDATE schedules SET delete_at='2000-01-01 00:00:00' WHERE id=?", (sid_i2,))
    MockFacebookService.queue = [{"success": True, "message": "deleted"}]
    run_worker()
    check("I 有 post_url 的 target 正常刪除", db.get_schedule(sid_i1)["delete_status"] == "deleted")
    check("I 沒有 post_url 的 target 獨立進 manual_required", db.get_schedule(sid_i2)["delete_status"] == "manual_required")

    # J：取消自動刪除後到期也不會執行
    sid_j = make_schedule(pid, target="J", delete_after_days=1)
    MockFacebookService.queue = [{"success": True, "message": "ok"}]
    run_worker()
    with db.connect() as conn:
        conn.execute(
            "UPDATE schedules SET post_url='https://facebook.com/j', delete_at='2000-01-01 00:00:00' WHERE id=?",
            (sid_j,),
        )
    db.cancel_auto_delete(sid_j)
    MockFacebookService.queue = [{"success": True, "message": "SHOULD NOT RUN"}]
    run_worker()
    check("J 取消後到期不會執行刪除", db.get_schedule(sid_j)["delete_status"] == "cancelled")
    check("J Facebook 刪除方法沒被呼叫", len(MockFacebookService.queue) == 1)

    print()
    if failures:
        print(f"REGRESSION FAILURES: {len(failures)} -> {failures}")
        return 1

    print("ALL AUTOMATION ENGINE MOCK TESTS PASSED")
    return 0


if __name__ == "__main__":
    exit_code = main()
    try:
        tmp_path.unlink(missing_ok=True)
    except OSError:
        pass
    sys.exit(exit_code)
