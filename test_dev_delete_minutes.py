"""Regression test for the DEV-ONLY minute-granularity delete window
(schedules.delete_after_minutes), added to support short-interval
acceptance testing (e.g. "delete 5 minutes after publish") without ever
touching the global 15-day production default or forcing a fake
sub-1-day value into the integer delete_after_days column.

Not exposed in any production UI -- only reachable by passing
delete_after_minutes directly to Database.create_schedule().

Direct execution: python test_dev_delete_minutes.py
"""
from __future__ import annotations

import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from app.services.database import Database, LOCAL_TIME_FORMAT

tmp_path = Path(tempfile.gettempdir()) / f"houseflow_test_dev_delete_{uuid.uuid4().hex}.db"
db = Database(tmp_path)

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        failures.append(name)


with db.connect() as conn:
    pid = int(conn.execute("INSERT INTO properties(title) VALUES ('test')").lastrowid)

# ---- delete_after_minutes takes priority over delete_after_days ----
sid = db.create_schedule({
    "property_id": pid, "target": "https://www.facebook.com/", "target_label": "個人動態",
    "copy_text": "x", "scheduled_at": "2099-01-01 00:00:00", "status": "scheduled",
    "delete_after_days": 15, "delete_after_minutes": 5,
})
db.mark_schedule_published(sid)
row = db.get_schedule(sid)
check("delete_status is pending", row["delete_status"] == "pending")
check("delete_at is set", bool(row["delete_at"]))

published_at = datetime.strptime(row["published_at"], LOCAL_TIME_FORMAT)
delete_at = datetime.strptime(row["delete_at"], LOCAL_TIME_FORMAT)
delta_minutes = (delete_at - published_at).total_seconds() / 60
check(f"delete_at is ~5 minutes after published_at (got {delta_minutes:.1f}min, not 15 days)", abs(delta_minutes - 5) < 0.1)

# ---- global default setting untouched by this per-schedule override ----
check("global automation_default_delete_days setting untouched (still 15)", db.get_setting("automation_default_delete_days", "15") == "15")

# ---- normal schedules (no delete_after_minutes) behave exactly as before ----
sid2 = db.create_schedule({
    "property_id": pid, "target": "https://www.facebook.com/", "target_label": "個人動態",
    "copy_text": "y", "scheduled_at": "2099-01-01 00:00:00", "status": "scheduled",
    "delete_after_days": 15,
})
db.mark_schedule_published(sid2)
row2 = db.get_schedule(sid2)
published_at2 = datetime.strptime(row2["published_at"], LOCAL_TIME_FORMAT)
delete_at2 = datetime.strptime(row2["delete_at"], LOCAL_TIME_FORMAT)
delta_days = (delete_at2 - published_at2).total_seconds() / 86400
check(f"normal schedule still uses whole-day delete_after_days (got {delta_days:.2f} days)", abs(delta_days - 15) < 0.01)

print()
if failures:
    print(f"REGRESSION FAILURES: {len(failures)} -> {failures}")
    sys.exit(1)
print("ALL DEV DELETE MINUTES TESTS PASSED")

try:
    tmp_path.unlink(missing_ok=True)
except OSError:
    pass
