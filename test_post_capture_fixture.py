"""Fixture-based regression test for FacebookService's post-capture logic,
using a REAL (headless) Playwright browser against static HTML built to
mirror Facebook's ACTUAL current structure -- not pure Python mocks, and
not a guessed structure.

2026-09-21 (second rewrite, same day): the first rewrite modeled the
home-feed structure (aria-posinset wrappers with a compact "剛剛"-style
timestamp link). A live, read-only diagnosis against a real already-
published post (schedule_id=7) then showed:
  - the just-published post is not reliably shown on the home feed at
    all (confirmed absent there for ~8 minutes); capture now navigates
    to the account's own profile page first, where it appeared
    immediately.
  - the profile page's post container does NOT carry aria-posinset the
    way the home feed does -- a much larger, non-post-scoped ancestor
    does instead. Container discovery now anchors on the post-actions
    button ("...的這則貼文採取的動作") and climbs until the ancestor's
    rendered text actually contains the (emoji-stripped, truncation-
    safe) content marker.
  - the real post had NO readable timestamp text/link anywhere in its
    container at all, even though Facebook visibly showed "11分鐘" on
    screen. The mandatory "must find a recent-looking timestamp link"
    requirement was replaced with a negative-only staleness check
    (reject only on affirmative "N天/N週/昨天" evidence found anywhere
    in the container; absence of any time signal is neutral, not
    disqualifying).
  - the real permalink was a /photo/?fbid=<digits> link (this account's
    post had one photo), not a /posts/ link -- confirmed live.
  - emoji characters (🏠💰📍) in the content never appeared in Facebook's
    own innerText (rendered as <img>, not text), and the preview
    truncates around 70-79 characters with "……查看更多" -- so the
    content marker used for matching must have emoji stripped and stay
    safely under that length.

Ground truth about Facebook's DOM can still drift over time; this test
guards the *matching/cross-validation logic* against real Playwright
locator/evaluate semantics on a structure verified against the real
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


# 原始文案（含表情符號、多段換行、超過截斷長度）——跟真實 AJCopyEngine
# 產生的文案結構一致，用來驗證「表情符號會被拿掉、超過截斷長度的部分
# 不列入比對」這兩個真實觀察到的行為。
OUR_CONTENT = (
    "如果你正在找龍潭區首購物件，不要只比較總價，格局、坪數與未來使用彈性也很重要。\n\n"
    "🏠【龍潭石門雲享套房】\n💰 售價：496萬\n📍 桃園市龍潭區民有一街\n📐 1房1廳1衛｜19.85坪\n\n"
    "如果你正在準備人生第一間房，這間可以先列入比較。"
)
OWN_NAME = "黃冠嘉"


def composer_html(name: str) -> str:
    return f'<div>{name}，在想些什麼？</div>'


def post_html(
    author: str,
    body_text: str,
    href: str,
    truncated: bool = True,
    include_stale_text: bool = False,
    include_comment: bool = False,
) -> str:
    # 比照真實 Facebook：貼文預覽只顯示一部分文字，且不含表情符號
    # （真實帳號實測表情符號是畫成獨立的 <img>，完全不會進到瀏覽器算
    # 出來的 innerText），後面接「……查看更多」。
    clean_body = FacebookService._EMOJI_PATTERN.sub("", body_text)
    visible_text = clean_body if not truncated else clean_body[:70] + " …… 查看更多"
    stale_html = '<span>3 天</span>' if include_stale_text else ""
    comment_html = ""
    if include_comment:
        comment_html = f"""
        <div role="article" aria-label="某某人的留言4天前">
          <a role="link" href="{href}?comment_id=999" aria-label="2026年9月17日 星期四下午2:00">
            <span>4天</span>
          </a>
        </div>
        """
    # 注意：作者是純粹從「更多選項」按鈕的 aria-label 解析出來的（見
    # _SCAN_CANDIDATES_JS），這裡刻意不放一個文字剛好等於 OWN_NAME 的
    # 額外連結——否則會被 _OWN_PROFILE_URL_FROM_NAV_JS 誤判成「帳號自己
    # 的個人檔案連結」，導致這個 headless fixture 真的嘗試 goto() 到
    # 一個沒有 mock 的網址，把測試內容整個換掉。
    return f"""
    <div>
      <div aria-label="對{author}的這則貼文採取的動作" role="button">...</div>
      <div>{visible_text}</div>
      {stale_html}
      <a role="link" href="{href}">相片連結</a>
      {comment_html}
    </div>
    """


def stories_tray_item_html() -> str:
    # 限時動態列表沒有「這則貼文採取的動作」按鈕，用來確認掃描邏輯
    # 真的不會誤把它當成一篇貼文。
    return '<div><img alt="Facebook"/></div>'


def build_page_html(body_fragments: list[str]) -> str:
    body = "\n".join(body_fragments)
    return f"<html><body>{composer_html(OWN_NAME)}<div id='feed'>{body}</div></body></html>"


service = FacebookService.__new__(FacebookService)

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)

    # ---- TEST 1: truncated preview (past our marker's safe length) + own author +
    # /photo/?fbid= permalink -> captured, alongside a Stories-tray decoy item ----
    page = browser.new_page()
    html = build_page_html([
        stories_tray_item_html(),
        post_html(OWN_NAME, OUR_CONTENT, "https://www.facebook.com/photo/?fbid=28630627439864864&set=a.336927529661567"),
        post_html("完全不相關的作者", "跟這次發布無關的另一篇貼文內容也拉長一點測試", "https://www.facebook.com/other/posts/pfbid0999"),
    ])
    page.set_content(html)
    result = service._capture_published_post(page, OUR_CONTENT, timeout_ms=3000)
    check("TEST 1: truncated preview + own-author post -> post_url captured",
          result.get("post_url", "") == "https://www.facebook.com/photo/?fbid=28630627439864864&set=a.336927529661567")
    check("TEST 1: numeric post_id extracted from photo fbid", result.get("post_id") == "28630627439864864")
    page.close()

    # ---- TEST 2: Stories tray items (no actions button) never match ----
    page = browser.new_page()
    html = build_page_html([stories_tray_item_html(), stories_tray_item_html()])
    page.set_content(html)
    result2 = service._capture_published_post(page, OUR_CONTENT, timeout_ms=3000)
    check("TEST 2: Stories tray (no actions button) never mistaken for a post", result2 == {})
    page.close()

    # ---- TEST 3: no post's content matches -> safety gate, empty (never guesses) ----
    page = browser.new_page()
    html = build_page_html([
        post_html(OWN_NAME, "跟我們這次發布完全無關的貼文內容打字打長一點", "https://www.facebook.com/photo/?fbid=555&set=a.1")
    ])
    page.set_content(html)
    result3 = service._capture_published_post(page, OUR_CONTENT, timeout_ms=3000)
    check("TEST 3: no content match -> returns empty", result3 == {})
    page.close()

    # ---- TEST 4: content matches but an explicit stale-time signal ("3 天") is present
    # in the same container -> rejected (negative-evidence staleness check) ----
    page = browser.new_page()
    html = build_page_html([
        post_html(OWN_NAME, OUR_CONTENT, "https://www.facebook.com/photo/?fbid=666&set=a.2", include_stale_text=True)
    ])
    page.set_content(html)
    result4 = service._capture_published_post(page, OUR_CONTENT, timeout_ms=3000)
    check("TEST 4: explicit stale-time signal ('3 天') -> rejected", result4 == {})
    page.close()

    # ---- TEST 5: content matches, no timestamp text at all anywhere (the real-world case
    # observed live) -> still captured, since absence of a time signal is neutral ----
    page = browser.new_page()
    html = build_page_html([
        post_html(OWN_NAME, OUR_CONTENT, "https://www.facebook.com/photo/?fbid=777&set=a.3")
    ])
    page.set_content(html)
    result5 = service._capture_published_post(page, OUR_CONTENT, timeout_ms=3000)
    check("TEST 5: no timestamp signal at all (real-world case) -> still captured, not blocked",
          result5.get("post_id") == "777")
    page.close()

    # ---- TEST 6: content + recent, but author is NOT the logged-in account -> rejected ----
    page = browser.new_page()
    html = build_page_html([
        post_html("別人的帳號", OUR_CONTENT, "https://www.facebook.com/photo/?fbid=888&set=a.4")
    ])
    page.set_content(html)
    result6 = service._capture_published_post(page, OUR_CONTENT, timeout_ms=3000)
    check("TEST 6: author cross-check rejects a post not authored by the logged-in account", result6 == {})
    page.close()

    # ---- TEST 7: real /posts/pfbid... permalink shape also accepted (not just /photo/) ----
    page = browser.new_page()
    html = build_page_html([
        post_html(OWN_NAME, OUR_CONTENT, "https://www.facebook.com/huang.guan.jia/posts/pfbid02AbC123XyZ")
    ])
    page.set_content(html)
    result7 = service._capture_published_post(page, OUR_CONTENT, timeout_ms=3000)
    check("TEST 7: /posts/pfbid... permalink shape accepted",
          result7.get("post_id") == "pfbid02AbC123XyZ")
    page.close()

    # ---- TEST 8: two distinct own-account posts both match -> ambiguous, refuses ----
    page = browser.new_page()
    html = build_page_html([
        post_html(OWN_NAME, OUR_CONTENT, "https://www.facebook.com/photo/?fbid=111&set=a.aaa"),
        post_html(OWN_NAME, OUR_CONTENT, "https://www.facebook.com/photo/?fbid=222&set=a.bbb"),
    ])
    page.set_content(html)
    result8 = service._capture_published_post(page, OUR_CONTENT, timeout_ms=3000)
    check("TEST 8: two distinct matching candidates -> ambiguous, refuses to guess", result8 == {})
    page.close()

    # ---- TEST 9: content + recent match, but a nested COMMENT with similar content/link
    # must NOT be picked up as if it were the post's own permalink ----
    page = browser.new_page()
    html = build_page_html([
        post_html(OWN_NAME, OUR_CONTENT, "https://www.facebook.com/photo/?fbid=333&set=a.ccc", include_comment=True)
    ])
    page.set_content(html)
    result9 = service._capture_published_post(page, OUR_CONTENT, timeout_ms=3000)
    check("TEST 9: post's own permalink captured, not the nested comment's",
          result9.get("post_url", "") == "https://www.facebook.com/photo/?fbid=333&set=a.ccc")
    page.close()

    browser.close()


print()
if failures:
    print(f"REGRESSION FAILURES: {len(failures)} -> {failures}")
    sys.exit(1)
print("ALL POST CAPTURE FIXTURE TESTS PASSED")
