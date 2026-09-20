"""Regression test for real Facebook permalink/post-ID capture, added so
auto-delete can finally target a verified post instead of always falling
back to manual_required.

Covers the explicit safety requirements: never guess, verify posted
content before trusting a candidate post, never fabricate a post_id, and
delete_post() must refuse to proceed if the loaded page's content doesn't
match what's expected -- no "newest post = ours" shortcuts anywhere.

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


def make_article_mock(text: str, href: str | None, timestamp_text: str = "剛剛"):
    """Builds a mock [role='article'] locator whose get_by_role() branches
    on whether a `name` filter was passed, matching the two distinct calls
    the real _capture_published_post() makes:
      - get_by_role("link")               -> _article_looks_recent()'s scan
      - get_by_role("link", name=pattern) -> _extract_permalink_from_article()
    `timestamp_text` controls what the recency scan "reads" off the link
    (default "剛剛" = looks recent; pass something like "3 天" to simulate
    an old post that should fail the recency cross-check).
    """
    article = mock.MagicMock()
    article.inner_text.return_value = text

    timestamp_link = mock.MagicMock()
    timestamp_link.get_attribute.return_value = href
    timestamp_link.wait_for.return_value = None
    timestamp_locator = mock.MagicMock()
    timestamp_locator.first = timestamp_link

    recency_link = mock.MagicMock()
    recency_link.inner_text.return_value = timestamp_text
    recency_links_locator = mock.MagicMock()
    recency_links_locator.count.return_value = 1
    recency_links_locator.nth.side_effect = lambda i: recency_link

    def get_by_role(role, name=None):
        return timestamp_locator if name is not None else recency_links_locator

    article.get_by_role.side_effect = get_by_role
    return article


def make_page_with_articles(article_mocks: list):
    page = mock.MagicMock()
    articles_locator = mock.MagicMock()
    articles_locator.count.return_value = len(article_mocks)
    articles_locator.nth.side_effect = lambda i: article_mocks[i]
    page.locator.return_value = articles_locator
    page.wait_for_timeout.return_value = None
    return page


service = FacebookService.__new__(FacebookService)  # skip __init__ (just resolves profile dir)
content = "【HouseFlow 自動排程測試】\n\n這是一段測試用的貼文內容，足夠長，可以拿來做內容比對驗證用途。"

# ---- TEST 1: content matches, valid permalink href -> captured correctly ----
article = make_article_mock(content, "https://www.facebook.com/story.php?story_fbid=1234567890&id=999")
page = make_page_with_articles([article])
result = service._capture_published_post(page, content, timeout_ms=1000)
check("TEST 1: matching content + valid href -> post_url captured", result.get("post_url", "").startswith("https://www.facebook.com/story.php"))
check("TEST 1: post_id extracted from story_fbid", result.get("post_id") == "1234567890")

# ---- TEST 2: no article matches content -> safety gate, empty dict (never guess) ----
article_wrong = make_article_mock("完全不相關的貼文內容", "https://www.facebook.com/story.php?story_fbid=999&id=1")
page2 = make_page_with_articles([article_wrong])
result2 = service._capture_published_post(page2, content, timeout_ms=1000)
check("TEST 2: no content match -> returns empty (does not guess)", result2 == {})

# ---- TEST 3: content matches but no timestamp link found -> empty dict ----
article3 = make_article_mock(content, None)
page3 = make_page_with_articles([article3])
result3 = service._capture_published_post(page3, content, timeout_ms=1000)
check("TEST 3: content matches but href missing -> returns empty", result3 == {})

# ---- TEST 4: href found but doesn't look like a real post permalink -> rejected ----
article4 = make_article_mock(content, "https://www.facebook.com/profile.php?id=12345")
page4 = make_page_with_articles([article4])
result4 = service._capture_published_post(page4, content, timeout_ms=1000)
check("TEST 4: non-permalink-shaped href rejected, not treated as a post URL", result4 == {})

# ---- TEST 5: too-short/empty content marker -> refuses immediately (never match on nothing) ----
page5 = make_page_with_articles([])
result5 = service._capture_published_post(page5, "hi", timeout_ms=1000)
check("TEST 5: too-short content -> refuses to even search", result5 == {})

# ---- TEST 5B: content matches + valid href, but timestamp looks OLD -> recency cross-check rejects ----
article_old = make_article_mock(
    content,
    "https://www.facebook.com/story.php?story_fbid=1234567890&id=999",
    timestamp_text="3 天",
)
page5b = make_page_with_articles([article_old])
result5b = service._capture_published_post(page5b, content, timeout_ms=1000)
check("TEST 5B: content matches but timestamp is old -> rejected (recency cross-check works)", result5b == {})


# ---- TEST 6: delete_post() safety gate -- content mismatch must abort before any delete click ----
def build_fake_playwright_context(page_body_text: str):
    fake_page = mock.MagicMock()
    fake_page.inner_text.return_value = page_body_text
    fake_context = mock.MagicMock()
    fake_context.close.return_value = None
    fake_playwright_cm = mock.MagicMock()
    fake_playwright_cm.__enter__.return_value = mock.MagicMock()
    fake_playwright_cm.__exit__.return_value = False
    return fake_page, fake_context


fake_page, fake_context = build_fake_playwright_context("這篇貼文的內容跟我們預期的完全不一樣")
with mock.patch("app.services.facebook_service.sync_playwright") as mock_sp, \
     mock.patch.object(FacebookService, "_open_context", return_value=fake_context), \
     mock.patch.object(FacebookService, "_get_page", return_value=fake_page), \
     mock.patch.object(FacebookService, "_raise_if_blocked", return_value=None), \
     mock.patch("app.services.facebook_service.verify_bundled_browser_or_raise", return_value=None):
    mock_sp.return_value.__enter__.return_value = mock.MagicMock()
    mock_sp.return_value.__exit__.return_value = False
    result6 = service.delete_post(
        "https://www.facebook.com/story.php?story_fbid=1&id=2",
        expected_content_prefix="【HouseFlow 自動排程測試】這是本來要刪除的那篇貼文開頭",
    )
check("TEST 6: content mismatch on delete target -> refuses, success=False", result6.get("success") is False)
check("TEST 6: refusal message names the safety reason", "刪錯" in result6.get("message", "") or "不符" in result6.get("message", ""))
check("TEST 6: menu button was never touched (delete never attempted)", not fake_page.get_by_role.called)


print()
if failures:
    print(f"REGRESSION FAILURES: {len(failures)} -> {failures}")
    sys.exit(1)
print("ALL POST CAPTURE / DELETE SAFETY TESTS PASSED")
