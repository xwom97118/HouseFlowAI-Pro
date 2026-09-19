"""Regression test for the 2026-09-19 incident: a deploy operation deleted
the bundled Chromium (_internal/pw-browsers) out from under a still-running
HouseFlow 3.3.1, so all 3 real scheduled Facebook publish attempts (18:00,
18:05, 18:35) failed with a bare, undiagnosable "[WinError 2] 系統找不到
指定的檔案。" because Playwright tried to launch a chrome.exe that no
longer existed on disk.

This verifies the fix: app.services.browser_runtime.verify_bundled_browser_or_raise()
(called from FacebookService._open_context() before any Playwright launch)
detects a missing bundled browser and raises a clear, actionable
BundledBrowserMissingError instead of letting a cryptic OS-level error
bubble up. Must stay green permanently.

Direct execution: python test_browser_preflight.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import mock

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        failures.append(name)


from app.services import browser_runtime


# ---- dev mode (not frozen): must be a no-op regardless of pw-browsers state ----
with mock.patch.object(browser_runtime.sys, "frozen", False, create=True):
    try:
        browser_runtime.verify_bundled_browser_or_raise()
        check("dev mode: no-op even with no bundled browser", True)
    except Exception as exc:
        check(f"dev mode: no-op even with no bundled browser (raised {exc!r})", False)


# ---- frozen + bundled browser present: must pass silently ----
with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    chrome_dir = tmp_path / "pw-browsers" / "chromium-1234" / "chrome-win64"
    chrome_dir.mkdir(parents=True)
    (chrome_dir / "chrome.exe").write_bytes(b"fake")

    with mock.patch.object(browser_runtime.sys, "frozen", True, create=True), \
         mock.patch.object(browser_runtime, "_app_base_dir", return_value=tmp_path):
        try:
            browser_runtime.verify_bundled_browser_or_raise()
            check("frozen + browser present: passes silently", True)
        except Exception as exc:
            check(f"frozen + browser present: passes silently (raised {exc!r})", False)


# ---- frozen + bundled browser MISSING (exact incident scenario): must raise a clear error ----
with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    # pw-browsers deliberately not created -- simulates it having been deleted
    # out from under a running instance, exactly like 2026-09-19.

    with mock.patch.object(browser_runtime.sys, "frozen", True, create=True), \
         mock.patch.object(browser_runtime, "_app_base_dir", return_value=tmp_path):
        try:
            browser_runtime.verify_bundled_browser_or_raise()
            check("frozen + browser missing: raises BundledBrowserMissingError", False)
        except browser_runtime.BundledBrowserMissingError as exc:
            message = str(exc)
            check("frozen + browser missing: raises BundledBrowserMissingError", True)
            check("error message names the expected path (actionable, not a bare WinError)", "pw-browsers" in message)
            check("error message tells the user what to do", "重新部署" in message or "重新安裝" in message)
        except Exception as exc:
            check(f"frozen + browser missing: raised wrong exception type {type(exc).__name__}", False)


# ---- FacebookService._open_context() actually calls the preflight check ----
from app.services.facebook_service import FacebookService

with mock.patch.object(browser_runtime.sys, "frozen", True, create=True), \
     mock.patch.object(browser_runtime, "_app_base_dir", return_value=Path(tempfile.mkdtemp())):
    service = FacebookService()
    try:
        service._open_context(playwright=None)  # should never reach playwright.chromium.launch_*
        check("FacebookService._open_context() calls the preflight check before launching", False)
    except browser_runtime.BundledBrowserMissingError:
        check("FacebookService._open_context() calls the preflight check before launching", True)
    except Exception as exc:
        check(f"FacebookService._open_context() raised unexpected {type(exc).__name__} instead of preflight error", False)


print()
if failures:
    print(f"REGRESSION FAILURES: {len(failures)} -> {failures}")
    sys.exit(1)
print("ALL BROWSER PREFLIGHT REGRESSION TESTS PASSED")
