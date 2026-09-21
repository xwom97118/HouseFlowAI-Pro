"""Regression tests for the 2026-09-21 Schedule UX/performance refactor
(Property Center "安排發文", QuickScheduleDialog, Schedule Center
primary+more action redesign, humanized status labels, async thumbnail
loading).

Uses a temporary, throwaway SQLite database (never the production DB) --
per explicit instruction, this round's UI/DB testing must not write to
production, and never publishes to or deletes from real Facebook (no
FacebookService/Playwright call is exercised anywhere in this file).

Direct execution: python test_schedule_ux.py
"""
from __future__ import annotations

import sys
import tempfile
import uuid
from pathlib import Path
from unittest import mock

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from app.services.database import Database
from app.pages.properties import PropertiesPage, _schedule_status_cell
from app.pages.schedule import ScheduleCenterPage, STATUS_LABELS, DELETE_STATUS_LABELS, TABS
from app.widgets.quick_schedule_dialog import QuickScheduleDialog

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        failures.append(name)


def make_temp_db() -> Database:
    path = Path(tempfile.gettempdir()) / f"houseflow_ux_test_{uuid.uuid4().hex}.db"
    return Database(path=path)


def seed_property(db: Database, image_dir: Path, title="測試物件", price="500萬") -> int:
    image_dir.mkdir(parents=True, exist_ok=True)
    image_path = image_dir / "01.jpg"
    if not image_path.exists():
        # 最小的合法 1x1 JPEG（base64），避免用假造的檔頭讓 libpng/libjpeg
        # 一直重試解碼失敗、拖慢測試——這裡只是要有一個真的能被
        # QImage 成功解出來的檔案，內容本身不重要。
        import base64
        tiny_jpeg = base64.b64decode(
            "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAMCAgICAgMCAgIDAwMDBAYEBAQEBAgGBgUGCQgKCgkI"
            "CQkKDA8MCgsOCwkJDRENDg8QEBEQCgwSExIQEw8QEBD/2wBDAQMDAwQDBAgEBAgQCwkLEBAQEBAQ"
            "EBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBD/wAARCAABAAEDASIA"
            "AhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAj/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEB"
            "AQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCdABmX"
            "/9k="
        )
        image_path.write_bytes(tiny_jpeg)

    db.set_setting("brokerage_name", "測試經紀業")
    db.set_setting("salesperson_license", "測試字號001")
    db.set_setting("broker_license", "測試字號002")

    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO properties(title, address, price, layout, size, url, status, image_paths, image_count) "
            "VALUES (?, ?, ?, ?, ?, ?, 'active', ?, 1)",
            (title, "測試地址一段一號", price, "3房2廳2衛", "30坪", "https://example.com/x", str(image_path)),
        )
        return int(cur.lastrowid)


db = make_temp_db()
tmp_image_dir = Path(tempfile.gettempdir()) / f"houseflow_ux_images_{uuid.uuid4().hex}"
property_id = seed_property(db, tmp_image_dir)

# ======================================================================
# QuickScheduleDialog
# ======================================================================

dialog = QuickScheduleDialog(db, property_id)
check("QuickScheduleDialog: content auto-loaded from property + profile", bool(dialog.content_editor.toPlainText().strip()))
check("QuickScheduleDialog: content includes property title", "測試物件" in dialog.content_editor.toPlainText())
check("QuickScheduleDialog: content includes compliance footer", "測試經紀業" in dialog.content_editor.toPlainText())
check("QuickScheduleDialog: image preview populated", dialog.preview_list.count() == 1)
check("QuickScheduleDialog: image defaults to checked", dialog.preview_list.item(0).checkState().value != 0)
check("QuickScheduleDialog: char count label updates", dialog.char_count_label.text().endswith("字") and dialog.char_count_label.text() != "0 字")
# dialog 從未 .show()/.exec()，isVisible() 對還沒上螢幕的 widget 一律是
# False（跟 ancestor 是否顯示有關），改用 isHidden() 檢查我們自己呼叫
# setVisible() 設定的旗標本身，不受「這個視窗有沒有被顯示過」影響。
check("QuickScheduleDialog: defaults to '排程發布' with time picker visible", not dialog.time_picker.isHidden() and not dialog.publish_now_radio.isChecked())

dialog.publish_now_radio.setChecked(True)
check("QuickScheduleDialog: switching to '立即發布' hides time picker + relabels save button", dialog.time_picker.isHidden() and dialog.save_button.text() == "立即發布")
dialog.publish_later_radio.setChecked(True)
check("QuickScheduleDialog: switching back shows time picker + relabels save button", not dialog.time_picker.isHidden() and dialog.save_button.text() == "儲存排程")

# ---- Auto-delete preset + persistence ----
check("QuickScheduleDialog: delete preset uses the requested 1/3/7/14/30 day options",
      [d for _r, d in dialog.delete_rule.radios if d is not None] == [1, 3, 7, 14, 30])
for radio, days in dialog.delete_rule.radios:
    if days == 7:
        radio.setChecked(True)
        break
check("QuickScheduleDialog: delete preview label updates when a preset is chosen", "預計刪除時間" in dialog.delete_preview_label.text())

before_count = len(db.list_schedules())
dialog._save()
after_count = len(db.list_schedules())
check("QuickScheduleDialog._save(): creates exactly one schedule row", after_count - before_count == 1)
check("QuickScheduleDialog._save(): dialog accepted (result() == Accepted)", dialog.result() == 1)

created = db.get_schedule(dialog.created_schedule_id)
check("Schedule creation: status='scheduled' (bypasses pending_review for the quick path)", created["status"] == "scheduled")
check("Schedule creation: property_id correct", created["property_id"] == property_id)
check("Schedule creation: images list saved (checked image included)", str(tmp_image_dir / "01.jpg") in str(created["images"]))
check("Auto-delete setting persistence: delete_after_days=7 saved on the row", int(created["delete_after_days"]) == 7)
check("Schedule creation: target_label defaults to Facebook 個人動態", created["target_label"] == "Facebook 個人動態")

# ---- Content-safety gate enforced inside the dialog (defense in depth) ----
# _save() shows a blocking QMessageBox.critical() on rejection (correct
# production UX -- the user needs to see why saving failed), which would
# hang this headless test waiting for a click that never comes. Patch it
# out for just this one call; production behavior is untouched.
dialog2 = QuickScheduleDialog(db, property_id)
dialog2.content_editor.setPlainText("【HouseFlow 自動排程測試】這篇不該被允許儲存")
before_count2 = len(db.list_schedules())
with mock.patch("app.widgets.quick_schedule_dialog.QMessageBox.critical") as mock_critical:
    dialog2._save()
after_count2 = len(db.list_schedules())
check("QuickScheduleDialog: content-safety gate blocks internal markers before any DB write",
      after_count2 == before_count2)
check("QuickScheduleDialog: content-safety rejection shown to the user (not silently swallowed)", mock_critical.called)
check("QuickScheduleDialog: rejected save does not accept the dialog", dialog2.result() != 1)

# ---- Unchecked images are excluded ----
dialog3 = QuickScheduleDialog(db, property_id)
dialog3.preview_list.item(0).setCheckState(dialog3.preview_list.item(0).checkState().__class__(0))
dialog3._save()
created3 = db.get_schedule(dialog3.created_schedule_id)
check("QuickScheduleDialog: unchecking an image excludes it from the saved schedule", created3["images"] == "")

# ---- Immediate publish path never touches FacebookService/Playwright ----
dialog4 = QuickScheduleDialog(db, property_id)
dialog4.publish_now_radio.setChecked(True)
dialog4._save()
check("QuickScheduleDialog: '立即發布' sets trigger_immediate_publish flag for the caller (page) to act on", dialog4.trigger_immediate_publish is True)
created4 = db.get_schedule(dialog4.created_schedule_id)
check("QuickScheduleDialog: '立即發布' still creates status='scheduled' (AutomationEngine/manual trigger picks it up, dialog itself never calls FacebookService)", created4["status"] == "scheduled")


# ======================================================================
# Property Center: status badge computation + wiring
# ======================================================================

check("_schedule_status_cell(None) -> 未排程", _schedule_status_cell(None)[0] == "未排程")
check("_schedule_status_cell(scheduled) -> 已排程 badge", "已排程" in _schedule_status_cell({"status": "scheduled", "scheduled_at": "2026-09-22 18:00:00"})[0])
check("_schedule_status_cell(published, no pending delete) -> 已發布 badge", "已發布" in _schedule_status_cell({"status": "published", "published_at": "2026-09-22 18:00:00", "delete_status": "not_scheduled"})[0])
published_with_delete = _schedule_status_cell({"status": "published", "published_at": "2026-09-22 18:00:00", "delete_status": "pending", "delete_at": "2026-09-29 18:00:00"})[0]
check("_schedule_status_cell(published + pending delete) -> includes 🗑 delete marker", "🗑" in published_with_delete)
check("_schedule_status_cell(failed) -> 發布失敗 badge", "發布失敗" in _schedule_status_cell({"status": "failed"})[0])

properties_page = PropertiesPage(db, lambda pid: None, lambda: None, go_schedule=lambda: None)
properties_page.refresh()
check("PropertiesPage: table has 12 columns (added 排程狀態)", properties_page.table.columnCount() == 12)
row_idx = next(i for i, r in enumerate(properties_page.rows) if r["id"] == property_id)
check("PropertiesPage: newly-created property row shows 已排程 in schedule-status column", "已排程" in properties_page.table.item(row_idx, 11).text())

# ---- partial refresh: doesn't rebuild the whole table, only the affected cell ----
# latest_schedule_by_property() 定義上就是「最新一筆」，這裡要標記成
# published 的必須是目前這個物件 id 最大的那筆（dialog4 建立的），不是
# 較早建立、id 較小的 dialog 那筆，否則「最新」永遠不會是它。
db.mark_schedule_published(dialog4.created_schedule_id, post_url="", post_id="")
before_row_count = properties_page.table.rowCount()
properties_page._refresh_schedule_status_for_property(property_id)
check("Partial refresh: row count unchanged (no full table rebuild)", properties_page.table.rowCount() == before_row_count)
check("Partial refresh: schedule-status cell reflects the new status", "已發布" in properties_page.table.item(row_idx, 11).text())


# ======================================================================
# Schedule Center: tabs, primary+more action plan, humanized labels
# ======================================================================

check("Schedule Center: TABS includes the requested 全部/待發布/已發布/待刪除/已完成/失敗 set",
      {"全部", "待發布", "已發布", "待刪除", "已完成", "失敗"}.issubset({t[0] for t in TABS}))

check("Status labels: scheduled -> 等待發布 (not raw 'scheduled')", STATUS_LABELS["scheduled"] == "等待發布")
check("Status labels: needs_review -> 需要確認", STATUS_LABELS["needs_review"] == "需要確認")
check("Delete-status labels: pending -> 等待刪除", DELETE_STATUS_LABELS["pending"] == "等待刪除")
check("Delete-status labels: manual_required -> 需要確認", DELETE_STATUS_LABELS["manual_required"] == "需要確認")
check("Delete-status labels: delete_failed -> 刪除失敗", DELETE_STATUS_LABELS["delete_failed"] == "刪除失敗")

schedule_page = ScheduleCenterPage(db, lambda: None)

def action_plan_for(status, **extra):
    row = {"status": status, "post_url": "", "delete_status": "not_scheduled", **extra}
    return schedule_page._build_action_plan(row)

primary, more = action_plan_for("scheduled")
check("Action plan: 待發布 (scheduled) -> exactly 1 primary + more menu (not 12 buttons)", primary[0] == "modify_time" and len(more) >= 1)

primary, more = action_plan_for("published", post_url="https://example.com/post")
check("Action plan: 已發布 with post_url -> primary is 查看貼文", primary == ("open_post", "查看貼文"))

primary, more = action_plan_for("published", post_url="https://example.com/post", delete_status="pending")
more_keys = [k for k, _label in more]
check("Action plan: 已發布 + 待刪除 -> more menu offers 取消自動刪除/立即刪除貼文", "cancel_delete" in more_keys and "delete_post" in more_keys)

primary, more = action_plan_for("failed")
check("Action plan: 失敗 -> primary is 查看原因 (not blank/raw status)", primary == ("show_reason", "查看原因"))

primary, more = action_plan_for("pending_review")
check("Action plan: 待檢核 -> primary is 核准", primary == ("approve", "核准"))

# 搜尋框存在，且是 list_schedules 的 search 參數（不是額外自己實作一套過濾）
check("Schedule Center: search box exists", hasattr(schedule_page, "search"))

# 每個 action key 在 _action_handlers 裡都對應得到一個真的方法（不會點了選單項目卻沒反應）
all_keys = {k for _label_ignored in TABS for k in []}  # placeholder, real check below
missing_handlers = []
for status in ("draft", "pending_review", "scheduled", "publishing", "published", "failed", "needs_review", "cancelled"):
    primary, more = action_plan_for(status, post_url="https://example.com/post", delete_status="pending")
    for key, _label in [primary, *more]:
        if key not in schedule_page._action_handlers:
            missing_handlers.append((status, key))
check("Action plan: every action key returned by _build_action_plan has a real handler wired up", not missing_handlers)


print()
if failures:
    print(f"REGRESSION FAILURES: {len(failures)} -> {failures}")
    sys.exit(1)
print("ALL SCHEDULE UX REGRESSION TESTS PASSED")
