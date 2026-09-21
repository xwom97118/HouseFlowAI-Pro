"""Regression test for real Facebook permalink/post-ID capture, added so
auto-delete can finally target a verified post instead of always falling
back to manual_required.

2026-09-21 (second rewrite, same day): after a real, read-only DOM
diagnosis against a genuine already-published post (schedule_id=7, see
git history) showed the FIRST rewrite's assumptions still didn't match
reality:
  - the just-published post is not reliably shown on the home feed at
    all (confirmed absent there for ~8 minutes); it does appear
    immediately on the account's own profile page, so capture now
    navigates there first;
  - aria-posinset does not bound "one post" on the profile page the way
    it does on the home feed, so container discovery now anchors on the
    post-actions button ("...的這則貼文採取的動作") and climbs until the
    ancestor's rendered text actually CONTAINS the content marker,
    instead of a blind text-length threshold;
  - the post's own timestamp text ("剛剛"/"N分鐘") is often not present
    in the DOM as a readable link at all, so the mandatory recency
    cross-check was replaced with our own bounded polling window plus a
    negative-only staleness check (reject only on affirmative "N天/N週/
    昨天" evidence, never require positive "recent" evidence);
  - the content marker itself must have emoji characters stripped (they
    don't survive into Facebook's own innerText) and be short enough to
    survive the "……查看更多" preview truncation (~70-79 chars observed;
    _CONTENT_MARKER_LENGTH=60 leaves margin).

_SCAN_CANDIDATES_JS's return shape changed accordingly: each candidate
is now {author, hasStaleSignal, hrefs} (no more ariaPosinset/
contentMatch/timeCandidates -- content matching is now baked into
container discovery itself, so every returned candidate already matched
content).

Covers: match+capture, author mismatch, unknown-author fail-open, no
qualifying href, non-permalink shape, too-short marker, explicit
stale-signal rejection, ambiguous multi-candidate refusal, /photo/?fbid=
shape, multi-photo-same-post grouping (not falsely ambiguous), and
delete_post()'s existing content-mismatch safety gate.

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


def make_page(candidates: list[dict], own_name: str | None = "黃冠嘉"):
    """page.evaluate() 是新版 _capture_published_post() 會呼叫到的三種
    Playwright API 之一：依實際傳入的 JS 常數字串分派對應的假回傳值
    （不是單純照呼叫順序排隊，因為呼叫順序會依 own_name 是否存在而
    改變）——比對抓不到帳號自己個人檔案連結（profile_href=None，模擬
    「找不到就留在原本頁面」的正常 fallback），只測 _SCAN_CANDIDATES_JS
    這一輪掃到的候選清單。"""
    page = mock.MagicMock()

    def evaluate_side_effect(js, *_args, **_kwargs):
        if js == FacebookService._OWN_NAME_FROM_COMPOSER_JS:
            return own_name
        if js == FacebookService._OWN_PROFILE_URL_FROM_NAV_JS:
            return None
        if js == FacebookService._SCAN_CANDIDATES_JS:
            return candidates
        return None

    page.evaluate.side_effect = evaluate_side_effect
    page.wait_for_timeout.return_value = None
    page.goto.return_value = None
    return page


def candidate(
    author: str | None = "黃冠嘉",
    hrefs: list[str] | None = None,
    has_stale_signal: bool = False,
) -> dict:
    if hrefs is None:
        hrefs = [
            "https://www.facebook.com/wang.siou.cin/posts/pfbid02t7umeRc7HyxPh6q3uZP2Mrb9dzGi6R9nrkugMvQoiUzKgZA98JzGHGbNR9zbD5j9l"
        ]
    return {"author": author, "hasStaleSignal": has_stale_signal, "hrefs": hrefs}


service = FacebookService.__new__(FacebookService)  # skip __init__ (just resolves profile dir)
content = "【HouseFlow 自動排程測試】\n\n這是一段測試用的貼文內容，足夠長，可以拿來做內容比對驗證用途。"

# ---- TEST 1: valid /posts/pfbid... permalink, matching author -> captured correctly ----
page = make_page([candidate()])
result = service._capture_published_post(page, content, timeout_ms=1000)
check(
    "TEST 1: matching author + valid href -> post_url captured",
    result.get("post_url", "").startswith("https://www.facebook.com/wang.siou.cin/posts/"),
)
check("TEST 1: pfbid post_id extracted (alphanumeric, not just digits)", result.get("post_id") == "pfbid02t7umeRc7HyxPh6q3uZP2Mrb9dzGi6R9nrkugMvQoiUzKgZA98JzGHGbNR9zbD5j9l")

# ---- TEST 2: no candidates at all (button/content never matched) -> safety gate, empty ----
page2 = make_page([])
result2 = service._capture_published_post(page2, content, timeout_ms=1000)
check("TEST 2: no candidates -> returns empty (does not guess)", result2 == {})

# ---- TEST 3: candidate has no qualifying href -> empty dict ----
page3 = make_page([candidate(hrefs=[])])
result3 = service._capture_published_post(page3, content, timeout_ms=1000)
check("TEST 3: candidate with no hrefs -> returns empty", result3 == {})

# ---- TEST 4: href found but doesn't look like a real permalink -> rejected ----
page4 = make_page([candidate(hrefs=["https://www.facebook.com/profile.php?id=12345"])])
result4 = service._capture_published_post(page4, content, timeout_ms=1000)
check("TEST 4: non-permalink-shaped href rejected, not treated as a post URL", result4 == {})

# ---- TEST 5: too-short/empty content marker -> refuses immediately (never match on nothing) ----
page5 = make_page([])
result5 = service._capture_published_post(page5, "hi", timeout_ms=1000)
check("TEST 5: too-short content -> refuses to even search", result5 == {})

# ---- TEST 6: explicit stale signal ("3 天" etc. found in container) -> rejected ----
page6 = make_page([candidate(has_stale_signal=True)])
result6 = service._capture_published_post(page6, content, timeout_ms=1000)
check("TEST 6: explicit stale-time signal in container -> rejected", result6 == {})

# ---- TEST 7: author cross-check -- candidate authored by someone else than the logged-in
#      account is rejected even though the permalink looks right ----
page7 = make_page([candidate(author="別人的帳號")])
result7 = service._capture_published_post(page7, content, timeout_ms=1000)
check("TEST 7: author mismatch (not the logged-in account's own post) -> rejected", result7 == {})

# ---- TEST 8: author unknown (own_name could not be determined) -> author check does not
#      block an otherwise-valid candidate (fails open on this one additional signal only) ----
page8 = make_page([candidate(author="某人")], own_name=None)
result8 = service._capture_published_post(page8, content, timeout_ms=1000)
check("TEST 8: unknown own account name -> author check does not block a valid candidate", bool(result8.get("post_url")))

# ---- TEST 9: two distinct posts both pass -> ambiguous, refuses rather than picking one ----
cand_a = candidate(hrefs=["https://www.facebook.com/user/posts/pfbidAAA"])
cand_b = candidate(hrefs=["https://www.facebook.com/user/posts/pfbidBBB"])
page9 = make_page([cand_a, cand_b])
result9 = service._capture_published_post(page9, content, timeout_ms=1000)
check("TEST 9: multiple distinct candidates -> ambiguous, refuses to guess", result9 == {})

# ---- TEST 10: photo-post permalink shape (/photo/?fbid=...) also accepted ----
page10 = make_page([candidate(hrefs=["https://www.facebook.com/photo/?fbid=29339576502295679&set=pcb.29339582195628443"])])
result10 = service._capture_published_post(page10, content, timeout_ms=1000)
check("TEST 10: /photo/?fbid= permalink shape accepted", result10.get("post_id") == "29339576502295679")

# ---- TEST 11: multiple /photo/ hrefs from the SAME post (different images, same "set=")
#      must NOT be treated as ambiguous -- they're the same underlying post ----
page11 = make_page([candidate(hrefs=[
    "https://www.facebook.com/photo/?fbid=111&set=a.999&__cft__[0]=AAA",
    "https://www.facebook.com/photo/?fbid=222&set=a.999&__cft__[0]=BBB",
])])
result11 = service._capture_published_post(page11, content, timeout_ms=1000)
check("TEST 11: multiple photo hrefs from the same post (same set=) -> not falsely ambiguous", bool(result11.get("post_url")))


# ---- TEST 12: delete_post() safety gate -- content mismatch must abort before any delete click ----
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
    result12 = service.delete_post(
        "https://www.facebook.com/story.php?story_fbid=1&id=2",
        expected_content_prefix="【HouseFlow 自動排程測試】這是本來要刪除的那篇貼文開頭",
    )
check("TEST 12: content mismatch on delete target -> refuses, success=False", result12.get("success") is False)
check("TEST 12: refusal message names the safety reason", "刪錯" in result12.get("message", "") or "不符" in result12.get("message", ""))
check("TEST 12: menu button was never touched (delete never attempted)", not fake_page.get_by_role.called)


print()
if failures:
    print(f"REGRESSION FAILURES: {len(failures)} -> {failures}")
    sys.exit(1)
print("ALL POST CAPTURE / DELETE SAFETY TESTS PASSED")
