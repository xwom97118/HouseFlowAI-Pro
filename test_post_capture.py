"""Regression test for real Facebook permalink/post-ID capture, added so
auto-delete can finally target a verified post instead of always falling
back to manual_required.

2026-09-21: rewritten after a real, read-only DOM inspection against the
user's actual logged-in Facebook account (facebook_browser_profile)
showed the previous implementation's core assumption (role="article"
identifies a feed post) was wrong -- that selector only matches empty
loading-state placeholders and, separately, nested COMMENT containers,
never real top-level posts. _capture_published_post() now scans
[aria-posinset] wrappers via a single page.evaluate() call, so these
tests mock page.evaluate()'s return value directly instead of chaining
Locator mocks.

Covers the explicit safety requirements: never guess, verify posted
content + recency + permalink shape before trusting a candidate, cross-
check authorship when the logged-in account's name is known, refuse when
multiple candidates match, and delete_post() must refuse to proceed if
the loaded page's content doesn't match what's expected.

Direct execution: python test_post_capture.py
"""
from __future__ import annotations

import sys
from unittest import mock

from app.services.facebook_service import FacebookService

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        failures.append(name)


def make_page(candidates: list[dict], own_name: str | None = None):
    """page.evaluate() 是 _capture_published_post() 唯一會呼叫的
    Playwright API：第一次呼叫回傳目前登入帳號名稱（給作者交叉驗證
    用），之後每一輪 polling 都回傳這一輪掃到的候選貼文清單。"""
    page = mock.MagicMock()
    call_results = [own_name, *([candidates] * 5)]
    page.evaluate.side_effect = lambda *_args, **_kwargs: call_results.pop(0) if call_results else candidates
    page.wait_for_timeout.return_value = None
    return page


def candidate(
    content_match: bool = True,
    author: str | None = "黃冠嘉",
    href: str = "https://www.facebook.com/wang.siou.cin/posts/pfbid02t7umeRc7HyxPh6q3uZP2Mrb9dzGi6R9nrkugMvQoiUzKgZA98JzGHGbNR9zbD5j9l",
    is_recent: bool = True,
) -> dict:
    return {
        "ariaPosinset": "1",
        "author": author,
        "contentMatch": content_match,
        "timeCandidates": [
            {
                "compactText": "剛剛",
                "isRecent": is_recent,
                "href": href,
                "ariaLabel": "2026年9月21日 星期一下午3:00",
            }
        ]
        if href
        else [],
    }


service = FacebookService.__new__(FacebookService)  # skip __init__ (just resolves profile dir)
content = "【HouseFlow 自動排程測試】\n\n這是一段測試用的貼文內容，足夠長，可以拿來做內容比對驗證用途。"

# ---- TEST 1: content matches, recent, valid /posts/pfbid... permalink -> captured correctly ----
page = make_page([candidate()], own_name="黃冠嘉")
result = service._capture_published_post(page, content, timeout_ms=1000)
check(
    "TEST 1: matching content + recent + valid href -> post_url captured",
    result.get("post_url", "").startswith("https://www.facebook.com/wang.siou.cin/posts/"),
)
check("TEST 1: pfbid post_id extracted (alphanumeric, not just digits)", result.get("post_id") == "pfbid02t7umeRc7HyxPh6q3uZP2Mrb9dzGi6R9nrkugMvQoiUzKgZA98JzGHGbNR9zbD5j9l")

# ---- TEST 2: no candidate's content matches -> safety gate, empty dict (never guess) ----
page2 = make_page([candidate(content_match=False)], own_name="黃冠嘉")
result2 = service._capture_published_post(page2, content, timeout_ms=1000)
check("TEST 2: no content match -> returns empty (does not guess)", result2 == {})

# ---- TEST 3: content matches but no recent timestamp link found -> empty dict ----
page3 = make_page([candidate(href="")], own_name="黃冠嘉")
result3 = service._capture_published_post(page3, content, timeout_ms=1000)
check("TEST 3: content matches but no timestamp/href candidate -> returns empty", result3 == {})

# ---- TEST 4: href found but doesn't look like a real permalink -> rejected ----
page4 = make_page(
    [candidate(href="https://www.facebook.com/profile.php?id=12345")], own_name="黃冠嘉"
)
result4 = service._capture_published_post(page4, content, timeout_ms=1000)
check("TEST 4: non-permalink-shaped href rejected, not treated as a post URL", result4 == {})

# ---- TEST 5: too-short/empty content marker -> refuses immediately (never match on nothing) ----
page5 = make_page([], own_name="黃冠嘉")
result5 = service._capture_published_post(page5, "hi", timeout_ms=1000)
check("TEST 5: too-short content -> refuses to even search", result5 == {})

# ---- TEST 6: content matches + valid href, but timestamp is NOT recent (e.g. "3 天") -> rejected ----
page6 = make_page([candidate(is_recent=False)], own_name="黃冠嘉")
result6 = service._capture_published_post(page6, content, timeout_ms=1000)
check("TEST 6: content matches but timestamp is old -> rejected (recency cross-check works)", result6 == {})

# ---- TEST 7: author cross-check -- candidate authored by someone else than the logged-in
#      account is rejected even though content/recency/permalink all look right ----
page7 = make_page([candidate(author="別人的帳號")], own_name="黃冠嘉")
result7 = service._capture_published_post(page7, content, timeout_ms=1000)
check("TEST 7: author mismatch (not the logged-in account's own post) -> rejected", result7 == {})

# ---- TEST 8: author unknown (own_name could not be determined) -> author check does not
#      block an otherwise-valid candidate (fails open on this one additional signal only) ----
page8 = make_page([candidate(author="某人")], own_name=None)
result8 = service._capture_published_post(page8, content, timeout_ms=1000)
check("TEST 8: unknown own account name -> author check does not block a valid candidate", bool(result8.get("post_url")))

# ---- TEST 9: two distinct posts both pass -> ambiguous, refuses rather than picking one ----
cand_a = candidate(href="https://www.facebook.com/user/posts/pfbidAAA")
cand_b = candidate(href="https://www.facebook.com/user/posts/pfbidBBB")
page9 = make_page([cand_a, cand_b], own_name="黃冠嘉")
result9 = service._capture_published_post(page9, content, timeout_ms=1000)
check("TEST 9: multiple distinct candidates -> ambiguous, refuses to guess", result9 == {})

# ---- TEST 10: photo-post permalink shape (/photo/?fbid=...) also accepted ----
page10 = make_page(
    [candidate(href="https://www.facebook.com/photo/?fbid=29339576502295679&set=pcb.29339582195628443")],
    own_name="黃冠嘉",
)
result10 = service._capture_published_post(page10, content, timeout_ms=1000)
check("TEST 10: /photo/?fbid= permalink shape accepted", result10.get("post_id") == "29339576502295679")


# ---- TEST 11: delete_post() safety gate -- content mismatch must abort before any delete click ----
def build_fake_playwright_context(page_body_text: str):
    fake_page = mock.MagicMock()
    fake_page.inner_text.return_value = page_body_text
    fake_context = mock.MagicMock()
    fake_context.close.return_value = None
    return fake_page, fake_context


fake_page, fake_context = build_fake_playwright_context("這篇貼文的內容跟我們預期的完全不一樣")
with mock.patch("app.services.facebook_service.sync_playwright") as mock_sp, \
     mock.patch.object(FacebookService, "_open_context", return_value=fake_context), \
     mock.patch.object(FacebookService, "_get_page", return_value=fake_page), \
     mock.patch.object(FacebookService, "_raise_if_blocked", return_value=None), \
     mock.patch("app.services.facebook_service.verify_bundled_browser_or_raise", return_value=None):
    mock_sp.return_value.__enter__.return_value = mock.MagicMock()
    mock_sp.return_value.__exit__.return_value = False
    result11 = service.delete_post(
        "https://www.facebook.com/story.php?story_fbid=1&id=2",
        expected_content_prefix="【HouseFlow 自動排程測試】這是本來要刪除的那篇貼文開頭",
    )
check("TEST 11: content mismatch on delete target -> refuses, success=False", result11.get("success") is False)
check("TEST 11: refusal message names the safety reason", "刪錯" in result11.get("message", "") or "不符" in result11.get("message", ""))
check("TEST 11: menu button was never touched (delete never attempted)", not fake_page.get_by_role.called)


print()
if failures:
    print(f"REGRESSION FAILURES: {len(failures)} -> {failures}")
    sys.exit(1)
print("ALL POST CAPTURE / DELETE SAFETY TESTS PASSED")
