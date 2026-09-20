"""Fixture-based regression test for FacebookService's post-capture logic,
using a REAL (headless) Playwright browser against static HTML that
approximates Facebook's feed structure -- not pure Python mocks. This
exercises the actual Playwright role/locator semantics my selectors rely
on, which a MagicMock-based test cannot verify.

Ground truth about real Facebook's current DOM is still unknown (no
access to it from this environment) -- these fixtures model a *plausible*
structure (role="article" posts, each with reaction/comment/share links
plus one timestamp link carrying the permalink href) so the matching
logic itself (content match + recency cross-validation + permalink shape
validation) is verified against real browser semantics. If Facebook's
actual markup differs, live validation is still required -- this test
guards the *logic*, not Facebook's specific selectors.

Direct execution: python test_post_capture_fixture.py
"""
from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

from app.services.facebook_service import FacebookService

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        failures.append(name)


OUR_CONTENT = "石門水庫第一排湖景度假別墅，桃園市龍潭區民強街，總價490萬，1房1廳1衛，適合首購族與小家庭。"


def article_html(text: str, timestamp_text: str, href: str) -> str:
    return f"""
    <div role="article" style="border:1px solid #ccc; margin:8px; padding:8px;">
      <p>{text}</p>
      <div class="actions">
        <a role="link" href="#like">讚</a>
        <a role="link" href="#comment">留言</a>
        <a role="link" href="#share">分享</a>
        <a role="link" href="{href}">{timestamp_text}</a>
      </div>
    </div>
    """


def build_page_html(articles_html: list[str]) -> str:
    body = "\n".join(articles_html)
    return f"<html><body><div id='feed'>{body}</div></body></html>"


service = FacebookService.__new__(FacebookService)

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)

    # ---- TEST 1: matching content + recent timestamp + valid permalink href -> captured ----
    page = browser.new_page()
    html = build_page_html([
        article_html(OUR_CONTENT, "剛剛", "https://www.facebook.com/story.php?story_fbid=111222333&id=999"),
        article_html("完全不相關的另一篇貼文", "3 小時", "https://www.facebook.com/story.php?story_fbid=444&id=999"),
    ])
    page.set_content(html)
    result = service._capture_published_post(page, OUR_CONTENT, timeout_ms=3000)
    check("TEST 1: matching + recent article -> post_url captured", result.get("post_url", "").startswith("https://www.facebook.com/story.php"))
    check("TEST 1: post_id extracted correctly", result.get("post_id") == "111222333")
    page.close()

    # ---- TEST 2: no article matches our content -> safety gate, empty ----
    page = browser.new_page()
    html = build_page_html([
        article_html("跟我們這次發布完全無關的貼文內容", "剛剛", "https://www.facebook.com/story.php?story_fbid=555&id=999"),
    ])
    page.set_content(html)
    result2 = service._capture_published_post(page, OUR_CONTENT, timeout_ms=3000)
    check("TEST 2: no content match -> returns empty (never guesses)", result2 == {})
    page.close()

    # ---- TEST 3: content matches but timestamp is OLD (not recent) -> rejected by cross-validation ----
    page = browser.new_page()
    html = build_page_html([
        article_html(OUR_CONTENT, "3 天", "https://www.facebook.com/story.php?story_fbid=666&id=999"),
    ])
    page.set_content(html)
    result3 = service._capture_published_post(page, OUR_CONTENT, timeout_ms=3000)
    check("TEST 3: content matches but timestamp is old -> rejected (recency cross-check works)", result3 == {})
    page.close()

    # ---- TEST 4: content matches + recent, but href doesn't look like a real post permalink ----
    page = browser.new_page()
    html = build_page_html([
        article_html(OUR_CONTENT, "剛剛", "https://www.facebook.com/profile.php?id=123456"),
    ])
    page.set_content(html)
    result4 = service._capture_published_post(page, OUR_CONTENT, timeout_ms=3000)
    check("TEST 4: non-permalink-shaped href rejected", result4 == {})
    page.close()

    # ---- TEST 5: correct article is NOT the first one (must scan multiple candidates) ----
    page = browser.new_page()
    html = build_page_html([
        article_html("排在最上面但不是我們要找的舊貼文", "2 小時", "https://www.facebook.com/story.php?story_fbid=777&id=999"),
        article_html(OUR_CONTENT, "30 秒", "https://www.facebook.com/story.php?story_fbid=888999000&id=999"),
    ])
    page.set_content(html)
    result5 = service._capture_published_post(page, OUR_CONTENT, timeout_ms=3000)
    check("TEST 5: correct article found even when not first in feed", result5.get("post_id") == "888999000")
    page.close()

    browser.close()


print()
if failures:
    print(f"REGRESSION FAILURES: {len(failures)} -> {failures}")
    sys.exit(1)
print("ALL POST CAPTURE FIXTURE TESTS PASSED")
