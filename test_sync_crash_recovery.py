"""Regression test for the 2026-09-19 sync-crash-recovery gap: verifying
the app during a build/deploy check killed HouseFlow mid-sync, leaving
sync_sources.sync_status='syncing' and a sync_runs row stuck at
status='running' forever (list_due_sync_sources() only ever picks up
sync_status='idle', so that source would never auto-sync again).

Covers:
- TEST A: a source stuck in syncing past the stale threshold gets
  recovered (sync_run -> cancelled, source -> idle) and becomes due again.
- TEST B: a source still within the stale threshold (genuinely mid-sync)
  must NOT be touched by recovery.
- TEST C: same scenario as A framed as "taskkill then app restart" -
  the source never stays stuck in syncing permanently.
- TEST D: the same source cannot have two syncs claimed concurrently.

Direct execution: python test_sync_crash_recovery.py
"""
from __future__ import annotations

import sys
import tempfile
import uuid
from pathlib import Path

from app.services.database import Database, local_str_plus
from app.services.automation_engine import AutomationCycleWorker, STALE_SYNCING_MINUTES

tmp_path = Path(tempfile.gettempdir()) / f"houseflow_test_sync_recovery_{uuid.uuid4().hex}.db"
db = Database(tmp_path)

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        failures.append(name)


def make_source(name: str) -> int:
    return db.save_sync_source({
        "name": name, "url": f"https://shop.example.com/{name}",
        "enabled": True, "auto_sync_enabled": True, "sync_interval_minutes": 60,
    })


# ---- TEST A: stale syncing source gets recovered ----
source_a = make_source("storeA")
token = uuid.uuid4().hex
claimed = db.claim_sync_source_for_sync(source_a, token)
check("TEST A setup: claim succeeds", claimed)
run_id = db.create_sync_run(source_a, "https://shop.example.com/storeA")
# Simulate the process being killed mid-sync: back-date syncing_started_at
# past the stale threshold (as if the claim happened a while ago and the
# process never came back to release it).
with db.connect() as conn:
    stale_time = local_str_plus(None, minutes=-(STALE_SYNCING_MINUTES + 5))
    conn.execute("UPDATE sync_sources SET syncing_started_at=? WHERE id=?", (stale_time, source_a))

worker = AutomationCycleWorker(db, 3, 3)
summary = {"sync_recovered": 0}
worker._recover_stale_syncing(summary)

check("TEST A: stale source recovered (sync_recovered incremented)", summary["sync_recovered"] == 1)
source_after = db.get_sync_source(source_a)
check("TEST A: sync_status back to idle", source_after["sync_status"] == "idle")
check("TEST A: execution_token cleared", source_after["execution_token"] == "")
check("TEST A: syncing_started_at cleared", source_after["syncing_started_at"] == "")

run_after = None
with db.connect() as conn:
    row = conn.execute("SELECT * FROM sync_runs WHERE id=?", (run_id,)).fetchone()
    run_after = dict(row)
check("TEST A: orphaned sync_run marked cancelled, not success", run_after["status"] == "cancelled")
check("TEST A: sync_run has finished_at set", bool(run_after["finished_at"]))
check("TEST A: sync_run has interruption diagnostic message", "Interrupted" in run_after["error_message"])

# ---- TEST C: after recovery, source is due again (not permanently stuck) ----
due = db.list_due_sync_sources()
check("TEST C: recovered source is due again (not stuck in syncing forever)", any(s["id"] == source_a for s in due))

# ---- TEST B: a genuinely still-running sync must NOT be touched ----
source_b = make_source("storeB")
token_b = uuid.uuid4().hex
db.claim_sync_source_for_sync(source_b, token_b)
run_id_b = db.create_sync_run(source_b, "https://shop.example.com/storeB")
# syncing_started_at is "now" (set by claim) -- well within the stale window.

worker2 = AutomationCycleWorker(db, 3, 3)
summary2 = {"sync_recovered": 0}
worker2._recover_stale_syncing(summary2)

check("TEST B: actively-syncing source untouched by recovery", summary2["sync_recovered"] == 0)
source_b_after = db.get_sync_source(source_b)
check("TEST B: sync_status still syncing (not reset)", source_b_after["sync_status"] == "syncing")
with db.connect() as conn:
    run_b = dict(conn.execute("SELECT * FROM sync_runs WHERE id=?", (run_id_b,)).fetchone())
check("TEST B: sync_run still running (not falsely cancelled)", run_b["status"] == "running")

# cleanup source_b's still-claimed state so it doesn't leak into other checks
db.mark_sync_source_success(source_b)

# ---- TEST D: same source cannot have two syncs claimed concurrently ----
source_d = make_source("storeD")
claim1 = db.claim_sync_source_for_sync(source_d, uuid.uuid4().hex)
claim2 = db.claim_sync_source_for_sync(source_d, uuid.uuid4().hex)
check("TEST D: only one concurrent claim succeeds for the same source", claim1 is True and claim2 is False)
db.mark_sync_source_success(source_d)

print()
if failures:
    print(f"REGRESSION FAILURES: {len(failures)} -> {failures}")
    sys.exit(1)
print("ALL SYNC CRASH RECOVERY TESTS PASSED")

try:
    tmp_path.unlink(missing_ok=True)
except OSError:
    pass
