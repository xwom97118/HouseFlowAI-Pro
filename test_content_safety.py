"""Regression test for the Facebook public-content safety gate
(app/services/content_safety.py), added after an internal test marker
("【HouseFlow 自動排程測試】") leaked into real, live Facebook posts during
2026-09-20 acceptance testing. From now on, FacebookService.publish_posts()
and prepare_posts() refuse (raise InternalMarkerDetectedError) rather than
send any content containing an internal engineering/test marker to
Facebook - regardless of who or what constructed the schedule.

Direct execution: python test_content_safety.py
"""
from __future__ import annotations

import sys
from unittest import mock

from app.services.content_safety import (
    InternalMarkerDetectedError,
    assert_public_content_safe,
    find_internal_marker,
)
from app.services.facebook_service import FacebookService

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        failures.append(name)


# ---- normal real estate copy must pass through untouched ----
normal_copy = (
    "石門水庫第一排湖景度假別墅\n桃園市龍潭區民強街\n490萬｜1房1廳1衛｜14.51坪\n\n"
    "經紀業：洺城開發企業社\n營業員：（108）登字第352260號\n經紀人：（113）南市字第01004號"
)
check("normal copy: find_internal_marker returns None", find_internal_marker(normal_copy) is None)
try:
    assert_public_content_safe(normal_copy)
    check("normal copy: assert_public_content_safe does not raise", True)
except InternalMarkerDetectedError:
    check("normal copy: assert_public_content_safe does not raise", False)

# ---- every banned marker in the user's exact list must be caught ----
banned_examples = [
    "【HouseFlow 自動排程測試】這是文案",
    "HouseFlow Test 版本",
    "This is an Automation Test post",
    "Auto Publish check",
    "自動發布測試中",
    "自動排程測試用",
    "自動排程",
    "機器人測試貼文",
    "this is a BOT posting",
    "DEV TEST content",
    "QA TEST run",
    "Schedule ID: 5",
    "Property ID 119",
    "Debug info here",
    "Test Post number 3",
    "Delete Test in 5 minutes",
]
for sample in banned_examples:
    marker = find_internal_marker(sample)
    check(f"banned marker detected in: {sample[:30]!r}", marker is not None)

# ---- case-insensitive matching for English tokens ----
check("case-insensitive: lowercase 'bot' detected", find_internal_marker("this is a bot test") is not None)
check("case-insensitive: 'debug' detected regardless of case", find_internal_marker("DEBUG output here") is not None)

# ---- FacebookService.publish_posts() must refuse before touching Playwright ----
service = FacebookService.__new__(FacebookService)
with mock.patch("app.services.facebook_service.sync_playwright") as mock_sp:
    try:
        service.publish_posts(
            ["https://www.facebook.com/"],
            "【HouseFlow 自動排程測試】這篇不該被允許發布",
            [],
        )
        check("publish_posts() refuses content with internal marker", False)
    except InternalMarkerDetectedError:
        check("publish_posts() refuses content with internal marker", True)
    check("publish_posts() never touched Playwright when refused", not mock_sp.called)

# ---- prepare_posts() must also refuse ----
with mock.patch("app.services.facebook_service.sync_playwright") as mock_sp2:
    try:
        service.prepare_posts(["https://www.facebook.com/"], "Schedule ID 42 test content", [])
        check("prepare_posts() refuses content with internal marker", False)
    except InternalMarkerDetectedError:
        check("prepare_posts() refuses content with internal marker", True)
    check("prepare_posts() never touched Playwright when refused", not mock_sp2.called)

print()
if failures:
    print(f"REGRESSION FAILURES: {len(failures)} -> {failures}")
    sys.exit(1)
print("ALL CONTENT SAFETY TESTS PASSED")
