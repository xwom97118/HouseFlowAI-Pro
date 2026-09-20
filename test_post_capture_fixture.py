"""Fixture-based regression test for FacebookService's post-capture logic,
using a REAL (headless) Playwright browser against static HTML built to
mirror Facebook's ACTUAL current feed structure -- not pure Python mocks,
and not a guessed structure.

2026-09-21: this fixture was rewritten after a live, read-only DOM
inspection against the user's real, logged-in Facebook account
(facebook_browser_profile) via a one-off script (not committed --
scratch/diagnostic only). That inspection disproved the previous
fixture's core assumption: real feed posts do NOT use role="article" at
all (that selector only matches empty loading-state placeholders, and
separately, nested COMMENT containers). The confirmed real structure:
  - each post's reliable outer boundary is a div with an aria-posinset
    attribute that also contains a "..的這則貼文採取的動作" (post actions)
    button -- this combination distinguishes real feed posts from the
    Stories tray, which also uses aria-posinset but lacks that button.
  - the actions button's aria-label reliably names the author:
    "對{author}的這則貼文採取的動作".
  - the real permalink shape seen live was
    https://www.facebook.com/{user}/posts/pfbid... (an alphanumeric
    pfbid token, not a pure-digit story_fbid) or, for photo posts,
    https://www.facebook.com/photo/?fbid=<digits>&set=...
  - a post's own (non-comment) short-lived timestamp text ("剛剛", "5
    分鐘", "3 小時", ...) sits near a clickable ancestor (<a> or
    role="link") whose href is that permalink; a COMMENT's own
    timestamp is wrapped in a role="article" container whose aria-label
    contains "的留言" -- excluded from matching so a comment's permalink
    is never mistaken for the post's own.

Ground truth about Facebook's DOM can still drift over time; this test
guards the *matching/cross-validation logic* against real Playwright
locator/evaluate semantics on a structure verified once against the real
site, not a promise that the exact CSS will never change again.

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
OWN_NAME = "黃冠嘉"


def composer_html(name: str) -> str:
    return f'<div>{name}，在想些什麼？</div>'


def post_html(
    author: str,
    body_text: str,
    timestamp_text: str,
    href: str,
    include_comment: bool = False,
    posinset: int = 1,
) -> str:
    comment_html = ""
    if include_comment:
        comment_html = f"""
        <div role="article" aria-label="某某人的留言4天前">
          <a role="link" href="{href}?comment_id=999" aria-label="2026年9月17日 星期四下午2:00">
            <span>4天</span>
          </a>
        </div>
        """
    return f"""
    <div aria-posinset="{posinset}">
      <div aria-label="對{author}的這則貼文採取的動作" role="button">...</div>
      <a href="https://www.facebook.com/{author}">{author}</a>
      <div>{body_text}</div>
      <a role="link" href="{href}" aria-label="2026年9月21日 星期一下午3:00">
        <span>{timestamp_text}</span>
      </a>
      {comment_html}
    </div>
    """


def stories_tray_item_html(posinset: int) -> str:
    # 限時動態列表也用 aria-posinset，但沒有「這則貼文採取的動作」按鈕
    # -- 用來驗證掃描邏輯真的會排除它，不會誤當成一篇貼文。
    return f'<div aria-posinset="{posinset}"><img alt="Facebook"/></div>'


def build_page_html(body_fragments: list[str]) -> str:
    body = "\n".join(body_fragments)
    return f"<html><body>{composer_html(OWN_NAME)}<div id='feed'>{body}</div></body></html>"


service = FacebookService.__new__(FacebookService)

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)

    # ---- TEST 1: matching content + recent timestamp + own-account author + valid
    # /posts/pfbid... permalink -> captured, alongside a Stories-tray decoy item ----
    page = browser.new_page()
    html = build_page_html([
        stories_tray_item_html(1),
        post_html(
            OWN_NAME,
            OUR_CONTENT,
            "剛剛",
            "https://www.facebook.com/huang.guan.jia/posts/pfbid02AbC123XyZ",
            posinset=2,
        ),
        post_html("完全不相關的作者", "跟這次發布無關的另一篇貼文", "3 小時",
                   "https://www.facebook.com/other/posts/pfbid0999", posinset=3),
    ])
    page.set_content(html)
    result = service._capture_published_post(page, OUR_CONTENT, timeout_ms=3000)
    check("TEST 1: matching + recent + own-author post -> post_url captured",
          result.get("post_url", "") == "https://www.facebook.com/huang.guan.jia/posts/pfbid02AbC123XyZ")
    check("TEST 1: pfbid post_id extracted correctly", result.get("post_id") == "pfbid02AbC123XyZ")
    page.close()

    # ---- TEST 2: Stories tray items (aria-posinset but no actions button) never match ----
    page = browser.new_page()
    html = build_page_html([stories_tray_item_html(1), stories_tray_item_html(2)])
    page.set_content(html)
    result2 = service._capture_published_post(page, OUR_CONTENT, timeout_ms=3000)
    check("TEST 2: Stories tray (no actions button) never mistaken for a post", result2 == {})
    page.close()

    # ---- TEST 3: no post's content matches -> safety gate, empty (never guesses) ----
    page = browser.new_page()
    html = build_page_html([
        post_html(OWN_NAME, "跟我們這次發布完全無關的貼文內容", "剛剛",
                  "https://www.facebook.com/huang.guan.jia/posts/pfbid0555")
    ])
    page.set_content(html)
    result3 = service._capture_published_post(page, OUR_CONTENT, timeout_ms=3000)
    check("TEST 3: no content match -> returns empty", result3 == {})
    page.close()

    # ---- TEST 4: content matches but timestamp is OLD -> rejected by recency cross-check ----
    page = browser.new_page()
    html = build_page_html([
        post_html(OWN_NAME, OUR_CONTENT, "3 天",
                  "https://www.facebook.com/huang.guan.jia/posts/pfbid0666")
    ])
    page.set_content(html)
    result4 = service._capture_published_post(page, OUR_CONTENT, timeout_ms=3000)
    check("TEST 4: content matches but timestamp is old -> rejected", result4 == {})
    page.close()

    # ---- TEST 5: content + recent match, but a nested COMMENT with similar content/timestamp
    # must NOT be picked up as if it were the post's own permalink ----
    page = browser.new_page()
    html = build_page_html([
        post_html(OWN_NAME, OUR_CONTENT, "剛剛",
                  "https://www.facebook.com/huang.guan.jia/posts/pfbid0777",
                  include_comment=True)
    ])
    page.set_content(html)
    result5 = service._capture_published_post(page, OUR_CONTENT, timeout_ms=3000)
    check("TEST 5: post's own permalink captured, not the nested comment's",
          result5.get("post_url", "") == "https://www.facebook.com/huang.guan.jia/posts/pfbid0777")
    page.close()

    # ---- TEST 6: content + recent match, but author is NOT the logged-in account -> rejected ----
    page = browser.new_page()
    html = build_page_html([
        post_html("別人的帳號", OUR_CONTENT, "剛剛",
                  "https://www.facebook.com/someone-else/posts/pfbid0888")
    ])
    page.set_content(html)
    result6 = service._capture_published_post(page, OUR_CONTENT, timeout_ms=3000)
    check("TEST 6: author cross-check rejects a post not authored by the logged-in account", result6 == {})
    page.close()

    # ---- TEST 7: photo-post permalink shape (/photo/?fbid=...) also accepted ----
    page = browser.new_page()
    html = build_page_html([
        post_html(OWN_NAME, OUR_CONTENT, "30 秒",
                  "https://www.facebook.com/photo/?fbid=29339576502295679&set=pcb.123")
    ])
    page.set_content(html)
    result7 = service._capture_published_post(page, OUR_CONTENT, timeout_ms=3000)
    check("TEST 7: /photo/?fbid= permalink shape accepted for photo posts",
          result7.get("post_id") == "29339576502295679")
    page.close()

    # ---- TEST 8: two distinct own-account posts both match -> ambiguous, refuses ----
    page = browser.new_page()
    html = build_page_html([
        post_html(OWN_NAME, OUR_CONTENT, "剛剛",
                  "https://www.facebook.com/huang.guan.jia/posts/pfbidAAA", posinset=2),
        post_html(OWN_NAME, OUR_CONTENT, "剛剛",
                  "https://www.facebook.com/huang.guan.jia/posts/pfbidBBB", posinset=3),
    ])
    page.set_content(html)
    result8 = service._capture_published_post(page, OUR_CONTENT, timeout_ms=3000)
    check("TEST 8: two distinct matching candidates -> ambiguous, refuses to guess", result8 == {})
    page.close()

    browser.close()


print()
if failures:
    print(f"REGRESSION FAILURES: {len(failures)} -> {failures}")
    sys.exit(1)
print("ALL POST CAPTURE FIXTURE TESTS PASSED")
