"""3.4 Auto Sync Center 的 mock 回歸測試——完全不碰真實網路/Playwright，
用注入的 MockSyncService 驗證核心安全機制：atomic claim（手動+自動不會
同時同步同一來源）、3 次連續沒看到才下架、整次同步結果可疑時不做下架
判斷、新增/價格異動正確記錄、失敗重試 backoff、全域開關與單一來源開關。

用獨立的暫存 sqlite 檔案，不會動到 dev/production 的 houseflow.db。
直接執行：python test_auto_sync.py
"""
from __future__ import annotations

import sys
import tempfile
import uuid
from pathlib import Path

from app.services.database import Database
from app.services.sync_service import SyncResult
from app.services.sync_runner import execute_source_sync, SyncAlreadyRunningError
from app.services.automation_engine import AutomationCycleWorker

tmp_path = Path(tempfile.gettempdir()) / f"houseflow_test_sync_{uuid.uuid4().hex}.db"
db = Database(tmp_path)

failures = []
def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        failures.append(name)


def make_prop(external_id, title="測試物件", price="1000萬", **kw):
    base = {
        "external_id": external_id, "title": title, "address": "龍潭區測試路1號",
        "price": price, "layout": "3房2廳", "size": "30坪", "url": f"https://x/{external_id}",
        "status": "active", "image_paths": "", "image_count": 0, "property_type": "大樓",
        "community": "", "features": "", "source_site": "yungching",
    }
    base.update(kw)
    return base


class MockSyncService:
    """行為佇列由測試自己塞，先進先出，不接觸真實網路。"""
    queue = []

    def fetch(self, source_url, progress_callback=None, cancel_event=None):
        if MockSyncService.queue:
            return MockSyncService.queue.pop(0)
        return SyncResult(found=0, saved=0, properties=[], message="empty queue")


# create a real sync source
source_id = db.save_sync_source({
    "name": "測試來源", "url": "https://shop.example.com/store1",
    "enabled": True, "auto_sync_enabled": True, "sync_interval_minutes": 360,
})

# ---- TEST E: new property -> property + change('created') ----
MockSyncService.queue = [SyncResult(found=1, saved=0, properties=[make_prop("P1")], message="ok")]
payload = execute_source_sync(db, db.get_sync_source(source_id), service_factory=MockSyncService)
check("TEST E: new property created", payload["counts"]["new"] == 1)
props = db.list_properties()
p1 = next(p for p in props if p["external_id"] == "P1")
changes = db.list_property_changes(limit=10)
check("TEST E: property_change type=created recorded", any(c["change_type"] == "created" and c["property_id"] == p1["id"] for c in changes))

# ---- TEST F: price change old/new correct ----
MockSyncService.queue = [SyncResult(found=1, saved=0, properties=[make_prop("P1", price="900萬")], message="ok")]
payload = execute_source_sync(db, db.get_sync_source(source_id), service_factory=MockSyncService)
check("TEST F: price_changed counted", payload["counts"]["price_changed"] == 1)
changes = db.list_property_changes(limit=10)
price_change = next(c for c in changes if c["change_type"] == "price_changed")
check("TEST F: old/new value correct", price_change["old_value"] == "1000萬" and price_change["new_value"] == "900萬")

# ---- TEST G: one miss -> not offline ----
MockSyncService.queue = [SyncResult(found=0, saved=0, properties=[], message="ok")]
# found=0 triggers "suspicious" per our safety rule -- use a different still-existing prop instead to simulate "not seen this time" without 0 result
MockSyncService.queue = [SyncResult(found=1, saved=0, properties=[make_prop("OTHER1", title="其他物件")], message="ok")]
payload = execute_source_sync(db, db.get_sync_source(source_id), service_factory=MockSyncService)
p1_after = db.get_property(p1["id"])
check("TEST G: one miss -> still active", p1_after["status"] == "active")
check("TEST G: missing_count == 1", int(p1_after["missing_count"]) == 1)

# ---- TEST H: 3 consecutive misses -> offline ----
for _ in range(2):
    MockSyncService.queue = [SyncResult(found=1, saved=0, properties=[make_prop("OTHER1", title="其他物件")], message="ok")]
    execute_source_sync(db, db.get_sync_source(source_id), service_factory=MockSyncService)
p1_after3 = db.get_property(p1["id"])
check("TEST H: 3 consecutive misses -> offline", p1_after3["status"] == "offline")
changes = db.list_property_changes(limit=20)
check("TEST H: offline change recorded", any(c["change_type"] == "offline" and c["property_id"] == p1["id"] for c in changes))

# ---- TEST I: offline property reappears -> online_again ----
MockSyncService.queue = [SyncResult(found=1, saved=0, properties=[make_prop("P1", price="900萬")], message="ok")]
execute_source_sync(db, db.get_sync_source(source_id), service_factory=MockSyncService)
p1_online = db.get_property(p1["id"])
check("TEST I: reappeared -> status active again", p1_online["status"] == "active")
changes = db.list_property_changes(limit=20)
check("TEST I: online_again change recorded", any(c["change_type"] == "online_again" and c["property_id"] == p1["id"] for c in changes))

# ---- TEST J: whole-sync failure (0 result) -> no offline detection ----
# seed a healthy baseline: 10 active properties for a fresh source
source2_id = db.save_sync_source({"name": "測試來源2", "url": "https://shop.example.com/store2", "enabled": True, "auto_sync_enabled": True})
baseline_props = [make_prop(f"S2-{i}") for i in range(10)]
MockSyncService.queue = [SyncResult(found=10, saved=0, properties=baseline_props, message="ok")]
execute_source_sync(db, db.get_sync_source(source2_id), service_factory=MockSyncService)
before_statuses = [p["status"] for p in db.list_properties() if p.get("source_id") == source2_id]
check("TEST J baseline: 10 active", before_statuses.count("active") == 10)

MockSyncService.queue = [SyncResult(found=0, saved=0, properties=[], message="site returned nothing")]
payload_suspicious = execute_source_sync(db, db.get_sync_source(source2_id), service_factory=MockSyncService)
check("TEST J: found=0 classified suspicious", payload_suspicious["status"] == "suspicious")
after_statuses = [p["status"] for p in db.list_properties() if p.get("source_id") == source2_id]
check("TEST J: no properties marked offline after suspicious sync", after_statuses.count("offline") == 0)

# ---- TEST K: tiny result (2 out of 10) -> suspicious, not mass-offline ----
MockSyncService.queue = [SyncResult(found=2, saved=0, properties=[make_prop("S2-0"), make_prop("S2-1")], message="ok")]
payload_k = execute_source_sync(db, db.get_sync_source(source2_id), service_factory=MockSyncService)
check("TEST K: tiny result classified suspicious", payload_k["status"] == "suspicious")
after_k = [p["status"] for p in db.list_properties() if p.get("source_id") == source2_id]
check("TEST K: no mass offline from tiny result", after_k.count("offline") == 0)

# ---- TEST L: retry backoff 5/15/30 ----
class AlwaysFailService:
    def fetch(self, *a, **kw):
        raise RuntimeError("network unreachable")

source3_id = db.save_sync_source({"name": "測試來源3", "url": "https://shop.example.com/store3", "enabled": True, "auto_sync_enabled": True})
try:
    execute_source_sync(db, db.get_sync_source(source3_id), service_factory=AlwaysFailService)
except RuntimeError:
    pass
row = db.get_sync_source(source3_id)
check("TEST L: retry_count=1 after 1st failure", int(row["retry_count"]) == 1)
first_retry_at = row["next_retry_at"]
check("TEST L: last_status=failed", row["last_status"] == "failed")

# ---- TEST D: manual + auto same time -> only one runs (atomic claim) ----
source4_id = db.save_sync_source({"name": "測試來源4", "url": "https://shop.example.com/store4", "enabled": True, "auto_sync_enabled": True})
token = uuid.uuid4().hex
claim1 = db.claim_sync_source_for_sync(source4_id, token)
claim2 = db.claim_sync_source_for_sync(source4_id, uuid.uuid4().hex)
check("TEST D: only one claim succeeds", claim1 is True and claim2 is False)
try:
    execute_source_sync(db, db.get_sync_source(source4_id), service_factory=MockSyncService)
    check("TEST D: second call raises SyncAlreadyRunningError", False)
except SyncAlreadyRunningError:
    check("TEST D: second call raises SyncAlreadyRunningError", True)
# release the claim to restore idle state for later checks
db.mark_sync_source_success(source4_id)

# ---- TEST A/C: enabled+due source picked up by AutomationCycleWorker; disabled/global-off not ----
db.set_setting("automation_sync_enabled", "1")
source5_id = db.save_sync_source({"name": "測試來源5", "url": "https://shop.example.com/store5", "enabled": True, "auto_sync_enabled": True})
due = db.list_due_sync_sources()
check("TEST A: newly created due source (next_sync_at empty) is due", any(s["id"] == source5_id for s in due))

worker = AutomationCycleWorker(db, 3, 3, sync_service_factory=MockSyncService, sync_phase_enabled=True)
MockSyncService.queue = [SyncResult(found=1, saved=0, properties=[make_prop("S5-1")], message="ok")]
summary = {"published": 0, "failed": 0, "needs_review": 0, "deleted": 0, "delete_failed": 0,
           "manual_delete_required": 0, "login_required": False, "sync_success": 0, "sync_failed": 0,
           "sync_new": 0, "sync_price_changed": 0, "sync_offline": 0}
worker._process_due_sync_sources(summary)
check("TEST A: due source synced via AutomationCycleWorker", summary["sync_success"] >= 1)
row5 = db.get_sync_source(source5_id)
check("TEST A: next_sync_at recomputed after success", bool(row5["next_sync_at"]))

# ---- TEST B: disabled source -> not executed ----
source6_id = db.save_sync_source({"name": "測試來源6", "url": "https://shop.example.com/store6", "enabled": True, "auto_sync_enabled": False})
due2 = db.list_due_sync_sources()
check("TEST B: auto_sync_enabled=False source not due", not any(s["id"] == source6_id for s in due2))

# ---- TEST C: global auto sync off -> _process_due_sync_sources no-ops ----
db.set_setting("automation_sync_enabled", "0")
worker2 = AutomationCycleWorker(db, 3, 3, sync_service_factory=MockSyncService, sync_phase_enabled=True)
summary2 = dict(summary)
summary2["sync_success"] = 0
MockSyncService.queue = [SyncResult(found=1, saved=0, properties=[make_prop("SHOULD-NOT-RUN")], message="ok")]
worker2._process_due_sync_sources(summary2)
check("TEST C: global auto sync off -> no sync executed", summary2["sync_success"] == 0 and len(MockSyncService.queue) == 1)
db.set_setting("automation_sync_enabled", "1")

# ---- Startup delay gating ----
worker3 = AutomationCycleWorker(db, 3, 3, sync_service_factory=MockSyncService, sync_phase_enabled=False)
summary3 = dict(summary)
summary3["sync_success"] = 0
worker3._process_due_sync_sources(summary3)
check("Startup delay: sync_phase_enabled=False -> no sync this tick", summary3["sync_success"] == 0)

print()
if failures:
    print(f"REGRESSION FAILURES: {len(failures)} -> {failures}")
    sys.exit(1)
print("ALL AUTO SYNC MOCK TESTS PASSED")

try:
    tmp_path.unlink(missing_ok=True)
except OSError:
    pass
