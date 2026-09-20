from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from playwright.sync_api import (
    BrowserContext,
    Locator,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from app.services import app_paths
from app.services.browser_runtime import verify_bundled_browser_or_raise
from app.services.content_safety import assert_public_content_safe


class FacebookService:
    def __init__(self) -> None:
        self.profile_dir = app_paths.facebook_profile_dir()

    def open_login(self) -> None:
        self.open_target(
            "https://www.facebook.com/"
        )

    def open_target(self, target_url: str) -> None:
        """只開啟指定 Facebook 頁面。"""
        with sync_playwright() as playwright:
            context = self._open_context(playwright)
            page = self._get_page(context)

            page.goto(
                target_url,
                wait_until="domcontentloaded",
                timeout=60_000,
            )

            self._wait_until_browser_closed(
                page,
                context,
            )

    def prepare_posts(
        self,
        target_urls: list[str],
        content: str,
        image_paths: list[str] | None = None,
    ) -> None:
        """
        開啟個人動態或社團，填入文案並上傳圖片。

        不會自動按下「發布」；需要自動發布時請使用 publish_posts()。
        """
        content = content.strip()
        image_paths = image_paths or []

        if not content:
            raise ValueError("貼文內容不可空白。")

        assert_public_content_safe(content)

        if not target_urls:
            raise ValueError("沒有設定發布位置。")

        valid_images = self._get_valid_image_paths(
            image_paths
        )

        with sync_playwright() as playwright:
            context = self._open_context(playwright)

            prepared_count = 0
            failed_targets: list[str] = []
            failure_messages: list[str] = []

            for index, target_url in enumerate(target_urls):
                page = (
                    self._get_page(context)
                    if index == 0
                    else context.new_page()
                )

                try:
                    page.goto(
                        target_url,
                        wait_until="domcontentloaded",
                        timeout=60_000,
                    )

                    page.wait_for_timeout(2500)

                    self._prepare_one_post(
                        page=page,
                        content=content,
                        image_paths=valid_images,
                    )

                    prepared_count += 1

                except Exception as exc:
                    failed_targets.append(target_url)
                    failure_messages.append(
                        f"{target_url}\n{exc}"
                    )

            if prepared_count == 0:
                context.close()

                details = "\n\n".join(
                    failure_messages
                )

                raise RuntimeError(
                    "無法準備 Facebook 貼文。\n\n"
                    "請確認：\n"
                    "1. 已登入 Facebook\n"
                    "2. 該社團允許你發文\n"
                    "3. Facebook 畫面已正常載入\n\n"
                    f"{details}"
                )

            if failed_targets:
                print("以下頁面未能自動填入：")

                for message in failure_messages:
                    print(message)
                    print("-" * 50)

            print(
                f"已準備 {prepared_count} 個發文頁面。"
            )
            print(
                "請逐一檢查文字與圖片，"
                "確認後自行按下 Facebook 的「發布」。"
            )

            first_page = context.pages[0]

            self._wait_until_browser_closed(
                first_page,
                context,
            )

    def publish_posts(
        self,
        target_urls: list[str],
        content: str,
        image_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        逐一開啟發布位置，填入文字與圖片，並自動按下「發布」。

        回傳：
        {
            "success_count": int,
            "failed_count": int,
            "results": [
                {
                    "url": str,
                    "success": bool,
                    "message": str,
                }
            ],
        }
        """
        content = content.strip()
        image_paths = image_paths or []

        if not content:
            raise ValueError("貼文內容不可空白。")

        if not target_urls:
            raise ValueError("沒有設定發布位置。")

        # 發布前的最後一道關卡：內部工程/測試標記絕對不能出現在真正
        # 發布到 Facebook 的公開內容裡。見 content_safety.py 的說明。
        assert_public_content_safe(content)

        valid_images = self._get_valid_image_paths(
            image_paths
        )
        results: list[dict[str, Any]] = []

        with sync_playwright() as playwright:
            context = self._open_context(playwright)
            page = self._get_page(context)

            try:
                for target_url in target_urls:
                    try:
                        page.goto(
                            target_url,
                            wait_until="domcontentloaded",
                            timeout=60_000,
                        )
                        page.wait_for_timeout(2500)

                        self._raise_if_blocked(page)

                        self._prepare_one_post(
                            page=page,
                            content=content,
                            image_paths=valid_images,
                        )

                        self._verify_prepared_post(
                            page=page,
                            content=content,
                            expected_image_count=len(
                                valid_images
                            ),
                        )

                        self._click_publish(page)
                        self._wait_for_publish_completion(
                            page
                        )

                        captured = self._capture_published_post(
                            page, content, timeout_ms=self._CAPTURE_TIMEOUT_MS
                        )

                        results.append(
                            {
                                "url": target_url,
                                "success": True,
                                "message": "發布完成",
                                "post_url": captured.get("post_url", ""),
                                "post_id": captured.get("post_id", ""),
                            }
                        )

                        page.wait_for_timeout(1500)

                    except Exception as exc:
                        results.append(
                            {
                                "url": target_url,
                                "success": False,
                                "message": str(exc),
                            }
                        )

                        # 失敗後嘗試關閉仍開著的貼文視窗，
                        # 避免影響下一個發布位置。
                        self._close_open_dialog(page)
                        page.wait_for_timeout(800)

            finally:
                try:
                    context.close()
                except Exception:
                    pass

        success_count = sum(
            1
            for item in results
            if item["success"]
        )

        return {
            "success_count": success_count,
            "failed_count": len(results) - success_count,
            "results": results,
        }

    def delete_post(
        self, remote_post_url: str, expected_content_prefix: str = ""
    ) -> dict[str, Any]:
        """刪除一篇 HouseFlow 自己發布、且已經有可靠 remote_post_url 的
        貼文。呼叫端（AutomationEngine）必須先確認這個 URL 存在且可靠
        才能呼叫這裡 —— 這個方法本身不做任何「用文案/物件名稱/時間找
        貼文」之類的猜測性比對，只會直接開啟這個貼文自己的網址操作。

        如果呼叫端有提供 expected_content_prefix（該筆 schedule 自己的
        文案開頭），會先確認 permalink 頁面實際顯示的內容真的包含這段
        文字才會繼續操作——避免 permalink 失效／被導向錯誤內容時，
        誤刪到不是本來要刪的貼文。比對不到就直接安全失敗，不會強行刪除。

        回傳：{"success": bool, "message": str}
        """
        if not remote_post_url:
            raise ValueError("缺少 remote_post_url，不能刪除貼文。")

        with sync_playwright() as playwright:
            context = self._open_context(playwright)
            page = self._get_page(context)

            try:
                page.goto(
                    remote_post_url,
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
                page.wait_for_timeout(2000)

                self._raise_if_blocked(page)

                if expected_content_prefix:
                    marker = " ".join(expected_content_prefix.strip().split())[:60]
                    if marker:
                        try:
                            page_text = " ".join(page.inner_text("body", timeout=5_000).split())
                        except Exception:
                            page_text = ""
                        if marker not in page_text:
                            return {
                                "success": False,
                                "message": "安全檢查失敗：這個網址目前顯示的內容跟預期的貼文不符，"
                                "為避免刪錯貼文已中止操作。",
                            }

                menu_button = page.get_by_role(
                    "button",
                    name=re.compile(r"動態消息選項|貼文選項|更多選項|More|Actions for this post"),
                )
                if not self._click_first_visible(menu_button):
                    raise RuntimeError("找不到貼文選項按鈕，無法刪除。")
                page.wait_for_timeout(800)

                delete_action = page.get_by_role(
                    "menuitem",
                    name=re.compile(r"刪除貼文|移到垃圾桶|Delete post|Move to trash"),
                )
                if not self._click_first_visible(delete_action):
                    raise RuntimeError("找不到刪除選項，無法刪除。")
                page.wait_for_timeout(800)

                confirm_button = page.get_by_role(
                    "button",
                    name=re.compile(r"^刪除$|移到垃圾桶|^Delete$|Move to trash"),
                )
                if not self._click_first_visible(confirm_button):
                    raise RuntimeError("找不到刪除確認按鈕，無法刪除。")
                page.wait_for_timeout(1500)

                return {"success": True, "message": "已刪除"}

            except Exception as exc:
                return {"success": False, "message": str(exc)}

            finally:
                try:
                    context.close()
                except Exception:
                    pass

    def _verify_prepared_post(
        self,
        page: Page,
        content: str,
        expected_image_count: int,
    ) -> None:
        dialog = self._get_visible_dialog(page)

        if dialog is None:
            raise RuntimeError(
                "發布前檢查失敗：找不到貼文視窗。"
            )

        editor = self._find_dialog_editor(dialog)

        if editor is None:
            raise RuntimeError(
                "發布前檢查失敗：找不到貼文文字欄位。"
            )

        try:
            current_text = str(
                editor.evaluate(
                    """
                    element => (
                        element.innerText
                        || element.textContent
                        || ''
                    ).trim()
                    """
                )
            )
        except Exception:
            current_text = ""

        first_line = content.splitlines()[0].strip()

        if not current_text:
            raise RuntimeError(
                "發布前檢查失敗：貼文沒有文字。"
            )

        if first_line and first_line not in current_text:
            raise RuntimeError(
                "發布前檢查失敗：貼文文字可能未完整帶入。"
            )

        if expected_image_count > 0:
            self._wait_for_image_upload_ready(
                page=page,
                dialog=dialog,
                expected_image_count=expected_image_count,
            )

    def _wait_for_image_upload_ready(
        self,
        page: Page,
        dialog: Locator,
        expected_image_count: int,
    ) -> None:
        deadline_ms = min(
            90_000,
            max(
                20_000,
                expected_image_count * 5_000,
            ),
        )
        elapsed = 0

        while elapsed < deadline_ms:
            self._raise_if_blocked(page)

            publish_button = self._find_publish_button(
                dialog
            )

            if publish_button is not None:
                try:
                    if publish_button.is_enabled(
                        timeout=500
                    ):
                        return
                except Exception:
                    pass

            page.wait_for_timeout(1000)
            elapsed += 1000

        raise RuntimeError(
            "圖片上傳等待逾時，尚未進入可發布狀態。"
        )

    def _click_publish(self, page: Page) -> None:
        dialog = self._get_visible_dialog(page)

        if dialog is None:
            raise RuntimeError(
                "找不到 Facebook 貼文視窗。"
            )

        publish_button = self._find_publish_button(
            dialog
        )

        if publish_button is None:
            raise RuntimeError(
                "找不到 Facebook 的「發布」按鈕。"
            )

        try:
            publish_button.wait_for(
                state="visible",
                timeout=15_000,
            )
        except PlaywrightTimeoutError as exc:
            raise RuntimeError(
                "Facebook 的「發布」按鈕沒有出現。"
            ) from exc

        deadline_ms = 90_000
        elapsed = 0

        while elapsed < deadline_ms:
            self._raise_if_blocked(page)

            try:
                if publish_button.is_enabled(
                    timeout=500
                ):
                    publish_button.click(
                        timeout=10_000
                    )
                    return
            except Exception:
                pass

            page.wait_for_timeout(1000)
            elapsed += 1000

        raise RuntimeError(
            "Facebook 的「發布」按鈕長時間無法點擊。"
        )

    def _find_publish_button(
        self,
        dialog: Locator,
    ) -> Locator | None:
        names = [
            re.compile(
                r"^發布$|^發佈$|^Post$",
                re.IGNORECASE,
            ),
        ]

        for name in names:
            locator = dialog.get_by_role(
                "button",
                name=name,
            )

            for index in range(
                locator.count() - 1,
                -1,
                -1,
            ):
                item = locator.nth(index)

                try:
                    if item.is_visible(
                        timeout=500
                    ):
                        return item
                except Exception:
                    continue

        # 備援：部分版本的發布按鈕不是標準 button role。
        text_locator = dialog.get_by_text(
            re.compile(
                r"^發布$|^發佈$|^Post$",
                re.IGNORECASE,
            ),
            exact=True,
        )

        for index in range(
            text_locator.count() - 1,
            -1,
            -1,
        ):
            item = text_locator.nth(index)

            try:
                if item.is_visible(timeout=500):
                    return item
            except Exception:
                continue

        return None

    def _wait_for_publish_completion(
        self,
        page: Page,
    ) -> None:
        """
        發布完成的判斷：
        1. 建立貼文 Dialog 消失；或
        2. 頁面出現常見成功訊息。
        """
        success_patterns = [
            re.compile(
                r"貼文已發布|已發佈貼文|"
                r"Your post is now published|"
                r"Your post was published",
                re.IGNORECASE,
            ),
        ]

        elapsed = 0
        timeout_ms = 60_000

        while elapsed < timeout_ms:
            self._raise_if_blocked(page)

            if self._get_visible_dialog(page) is None:
                return

            for pattern in success_patterns:
                candidate = page.get_by_text(
                    pattern,
                    exact=False,
                )

                try:
                    if (
                        candidate.count()
                        and candidate.first.is_visible(
                            timeout=300
                        )
                    ):
                        return
                except Exception:
                    continue

            page.wait_for_timeout(1000)
            elapsed += 1000

        raise RuntimeError(
            "已按下發布，但無法確認貼文是否完成。"
        )

    # Poll 到最長 90 秒、每 3 秒重讀一次 DOM（2026-09-21 真實 DOM 檢查後
    # 依使用者指示改為合理 polling，而非固定等 20 秒；找到唯一可靠候選
    # 就立刻回傳，不會傻等到 timeout）。
    _CAPTURE_TIMEOUT_MS = 90_000
    _CAPTURE_POLL_INTERVAL_MS = 3_000

    # 2026-09-21 對著真實登入的 Facebook 帳號（facebook_browser_profile）
    # 做過唯讀 DOM 檢查後確認：目前繁中介面的動態消息貼文，最外層「不」
    # 使用 role="article"（那個 selector 只會抓到空的、還在 "載入中……"
    # 的 loading-state 佔位元素，或是展開留言時、留言本身用的容器）。
    # 每篇貼文真正可靠的邊界是帶 aria-posinset 屬性、且內部找得到
    # 「對＿的這則貼文採取的動作」（貼文自己的「更多選項」選單按鈕）
    # 的那個 wrapper——這個組合同時也能排除頁面最上方限時動態列表
    # （同樣有 aria-posinset，但沒有這顆按鈕）。
    _PERMALINK_SHAPE_PATTERN = re.compile(
        r"/posts/|/videos/|story_fbid=|permalink\.php|/photo(?:\.php|/)"
    )
    # 貼文永久連結的 ID 現在多半是 pfbid 開頭的英數字 token（例如
    # .../posts/pfbid02t7umeRc7HyxPh6...），不是只有數字，所以這裡除了
    # 舊版純數字樣式，也要接受 pfbid 樣式；抓不到 ID 不影響安全性，
    # post_url 本身才是刪文流程實際要用的欄位。
    _POST_ID_PATTERN = re.compile(
        r"(?:story_fbid=|/posts/|/videos/|[?&]fbid=)(pfbid[A-Za-z0-9]+|\d+)"
    )

    _OWN_NAME_FROM_COMPOSER_JS = r"""
        () => {
            const re = /^(.+?)，在想些什麼？$/;
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            let node;
            while ((node = walker.nextNode())) {
                const txt = (node.textContent || '').trim();
                const m = txt.match(re);
                if (m) return m[1];
            }
            return null;
        }
    """

    # 掃描目前 DOM 裡所有「看起來像真正貼文」的 aria-posinset wrapper，
    # 回傳每篇的：作者（從更多選項按鈕的 aria-label 解析）、內容是否
    # 比對到 marker、以及所有「非留言」時間戳記連結（可見文字符合
    # 剛剛／N秒／N分鐘／N小時／N天／昨天樣式，且其 permalink 形狀的
    # href）。留言自己的時間戳記會被包在 role="article" 且 aria-label
    # 是「＿的留言＿前」樣式的容器裡，這裡會排除掉，避免誤把留言的
    # permalink 當成貼文本身的。
    _SCAN_CANDIDATES_JS = r"""
        (marker) => {
            const AUTHOR_RE = /^對(.+)的這則貼文採取的動作$/;
            const COMPACT_TIME_RE = /^(剛剛|(\d+)\s*(秒|分鐘|小時|天|週)|昨天)$/;
            const RECENT_RE = /^(剛剛|(\d+)\s*(秒|分鐘|小時))/;

            function isInsideComment(el) {
                let cur = el;
                let hops = 0;
                while (cur && hops < 12) {
                    if (cur.getAttribute && cur.getAttribute('role') === 'article') {
                        const label = cur.getAttribute('aria-label') || '';
                        if (label.includes('的留言')) return true;
                    }
                    cur = cur.parentElement;
                    hops += 1;
                }
                return false;
            }

            const wrappers = Array.from(document.querySelectorAll('[aria-posinset]'));
            const results = [];

            for (const wrapper of wrappers) {
                const moreBtn = wrapper.querySelector('[aria-label*="這則貼文採取的動作"]');
                if (!moreBtn) continue;

                const moreLabel = moreBtn.getAttribute('aria-label') || '';
                const authorMatch = moreLabel.match(AUTHOR_RE);
                const author = authorMatch ? authorMatch[1] : null;

                const wrapperText = (wrapper.innerText || '').replace(/\s+/g, ' ').trim();
                const contentMatch = wrapperText.includes(marker);

                const shortTextEls = Array.from(wrapper.querySelectorAll('*')).filter(el => {
                    if (el.children.length !== 0) return false;
                    const txt = (el.textContent || '').trim();
                    return txt.length > 0 && txt.length <= 6 && COMPACT_TIME_RE.test(txt);
                });

                const timeCandidates = [];
                for (const t of shortTextEls) {
                    if (isInsideComment(t)) continue;
                    const compactText = t.textContent.trim();
                    let clickable = t;
                    let hops = 0;
                    while (clickable && hops < 8) {
                        if (clickable.tagName === 'A' || clickable.getAttribute('role') === 'link') break;
                        clickable = clickable.parentElement;
                        hops += 1;
                    }
                    if (!clickable || (clickable.tagName !== 'A' && clickable.getAttribute('role') !== 'link')) continue;
                    const href = clickable.getAttribute('href');
                    if (!href) continue;
                    timeCandidates.push({
                        compactText,
                        isRecent: RECENT_RE.test(compactText),
                        href,
                        ariaLabel: clickable.getAttribute('aria-label') || '',
                    });
                }

                results.push({
                    ariaPosinset: wrapper.getAttribute('aria-posinset'),
                    author,
                    contentMatch,
                    timeCandidates,
                });
            }

            return results;
        }
    """

    def _capture_published_post(
        self,
        page: Page,
        content: str,
        timeout_ms: int | None = None,
    ) -> dict[str, str]:
        """發布成功、貼文視窗關閉之後，嘗試從目前這個已登入的 Facebook
        session 讀取剛剛那篇貼文的 permalink，讓 AutomationEngine 可以
        真正記錄 post_url/post_id，之後才有辦法安全地自動刪文。

        絕對不是「Feed 最上面那篇就是剛才發的」這種盲目假設，而是每一輪
        polling 都要求同時成立：
        1. 內容比對——候選貼文的可見文字包含這次發布內容一段夠長、
           有辨識度的開頭。
        2. 時間交叉驗證——候選貼文自己（不是留言）的時間戳記文字要
           看起來像是「剛剛／幾秒／幾分鐘／幾小時」，不是「幾天」
           「昨天」之類明顯較舊的貼文。
        3. permalink 格式驗證——時間戳記連結的 href 要像真的貼文／
           相片永久連結。
        4. 作者交叉驗證（附加訊號，非必要條件）——如果讀得到目前登入
           帳號的真實顯示名稱，且這篇候選貼文的作者跟它不同，就直接
           排除這個候選；讀不到就不套用這一條，不影響前三條的判定。

        任何一步不確定、或同時有超過一篇候選都通過驗證（無法唯一判定
        是哪一篇）——就直接回傳空字典，呼叫端維持既有安全機制（post_url
        留空 -> 需要人工刪除），絕對不會用猜的方式硬填一個 identifier。

        2026-09-21 對著真實登入的帳號做過唯讀 DOM 檢查，確認了這裡用的
        selector（aria-posinset 容器邊界、更多選項按鈕的作者名稱、
        /posts/pfbid... 永久連結樣式）都是目前繁中介面實際存在的結構，
        取代了先前那版完全建立在 role="article"（實際上抓不到任何貼文
        內容）之上的舊邏輯。無法 100% 確認的部分（例如貼文自己的時間
        戳記連結是否在每一種貼文版型下都用完全一樣的方式呈現）仍然
        沒有絕對把握，找不到符合條件的唯一候選時一律回傳空字典。
        """
        effective_timeout_ms = timeout_ms if timeout_ms is not None else self._CAPTURE_TIMEOUT_MS

        marker = " ".join(content.strip().split())[:80]
        if len(marker) < 10:
            return {}

        try:
            own_name = page.evaluate(self._OWN_NAME_FROM_COMPOSER_JS)
        except Exception:
            own_name = None

        elapsed = 0
        while elapsed < effective_timeout_ms:
            result = self._scan_and_extract(page, marker, own_name)
            if result:
                return result

            page.wait_for_timeout(self._CAPTURE_POLL_INTERVAL_MS)
            elapsed += self._CAPTURE_POLL_INTERVAL_MS

        return {}

    def _scan_and_extract(
        self, page: Page, marker: str, own_name: str | None
    ) -> dict[str, str]:
        try:
            candidates = page.evaluate(self._SCAN_CANDIDATES_JS, marker)
        except Exception:
            return {}

        strong_matches: list[dict[str, str]] = []

        for candidate in candidates or []:
            if not candidate.get("contentMatch"):
                continue
            author = candidate.get("author")
            if own_name and author and author != own_name:
                continue

            for time_candidate in candidate.get("timeCandidates") or []:
                if not time_candidate.get("isRecent"):
                    continue
                href = time_candidate.get("href") or ""
                if not href:
                    continue
                post_url = href if href.startswith("http") else f"https://www.facebook.com{href}"
                if not self._PERMALINK_SHAPE_PATTERN.search(post_url):
                    continue

                post_id = ""
                id_match = self._POST_ID_PATTERN.search(post_url)
                if id_match:
                    post_id = id_match.group(1)

                strong_matches.append({"post_url": post_url, "post_id": post_id})

        # 同一輪掃描裡只要出現一個以上不同的候選 permalink，代表無法
        # 唯一判定是哪一篇，安全起見一律不採信、回傳空字典。
        unique_urls = {m["post_url"] for m in strong_matches}
        if len(unique_urls) == 1:
            return strong_matches[0]

        return {}

    def _raise_if_blocked(
        self,
        page: Page,
    ) -> None:
        patterns = [
            re.compile(
                r"安全驗證|確認你的身分|"
                r"帳號暫時受限|操作遭封鎖|"
                r"Security check|Confirm your identity|"
                r"temporarily blocked|Action blocked",
                re.IGNORECASE,
            ),
        ]

        for pattern in patterns:
            locator = page.get_by_text(
                pattern,
                exact=False,
            )

            try:
                if (
                    locator.count()
                    and locator.first.is_visible(
                        timeout=300
                    )
                ):
                    raise RuntimeError(
                        "Facebook 要求安全驗證或限制操作，"
                        "已停止自動發布。"
                    )
            except RuntimeError:
                raise
            except Exception:
                continue

    def _close_open_dialog(
        self,
        page: Page,
    ) -> None:
        dialog = self._get_visible_dialog(page)

        if dialog is None:
            return

        close_patterns = [
            re.compile(
                r"關閉|Close",
                re.IGNORECASE,
            ),
        ]

        for pattern in close_patterns:
            locator = dialog.get_by_role(
                "button",
                name=pattern,
            )

            if self._click_first_visible(locator):
                page.wait_for_timeout(500)
                return

        try:
            page.keyboard.press("Escape")
        except Exception:
            pass

    def _prepare_one_post(
        self,
        page: Page,
        content: str,
        image_paths: list[str],
    ) -> None:
        # 一律先開啟真正的 Facebook 貼文視窗，
        # 避免誤把文字輸入到留言框。
        self._open_composer(page)
        page.wait_for_timeout(1200)

        dialog = self._get_visible_dialog(page)

        if dialog is None:
            raise RuntimeError(
                "已點擊發文入口，但找不到 Facebook 貼文視窗。"
            )

        editor = self._find_dialog_editor(dialog)

        if editor is None:
            raise RuntimeError(
                "已開啟 Facebook 貼文視窗，但找不到 Lexical 貼文輸入框。"
            )

        self._type_content(
            page,
            editor,
            content,
        )

        if image_paths:
            self._upload_images(
                page,
                image_paths,
            )

        page.bring_to_front()

    def _open_composer(self, page: Page) -> None:
        # 如果貼文視窗已經開啟，就不要重複點。
        if self._get_visible_dialog(page) is not None:
            return

        patterns = [
            re.compile(
                r"在想些什麼|你在想什麼|What's on your mind",
                re.IGNORECASE,
            ),
            re.compile(
                r"留個言吧|說點什麼|寫點什麼|"
                r"建立公開貼文|建立貼文|"
                r"Write something|Create post",
                re.IGNORECASE,
            ),
        ]

        for pattern in patterns:
            candidates = [
                page.get_by_role(
                    "button",
                    name=pattern,
                ),
                page.get_by_text(
                    pattern,
                    exact=False,
                ),
            ]

            for candidate in candidates:
                if self._click_first_visible(candidate):
                    page.wait_for_timeout(1000)

                    if self._get_visible_dialog(page) is not None:
                        return

        # 新版社團有時發文入口本身不是 button。
        candidates = page.locator(
            "div[role='textbox'], "
            "div[contenteditable='true']"
        )

        for index in range(candidates.count()):
            item = candidates.nth(index)

            try:
                box = item.bounding_box()

                if (
                    item.is_visible(timeout=500)
                    and box
                    and box["y"] < 750
                ):
                    item.click(
                        force=True,
                        timeout=3000,
                    )
                    page.wait_for_timeout(1000)

                    if self._get_visible_dialog(page) is not None:
                        return
            except Exception:
                continue

        raise RuntimeError(
            "找不到 Facebook 的發文入口。"
        )

    def _get_visible_dialog(
        self,
        page: Page,
    ) -> Locator | None:
        dialogs = page.locator("div[role='dialog']")

        # 第一優先：真正包含 Lexical Editor 的 Dialog
        for index in range(dialogs.count() - 1, -1, -1):
            dialog = dialogs.nth(index)

            try:
                if not dialog.is_visible(timeout=500):
                    continue

                editor = dialog.locator(
                    "[data-lexical-editor='true']"
                )

                if editor.count():
                    return dialog

            except Exception:
                continue

        # 第二優先：包含 contenteditable 的 Dialog
        for index in range(dialogs.count() - 1, -1, -1):
            dialog = dialogs.nth(index)

            try:
                if not dialog.is_visible(timeout=500):
                    continue

                editor = dialog.locator(
                    "[contenteditable='true']"
                )

                if editor.count():
                    return dialog

            except Exception:
                continue

        return None

    def _find_dialog_editor(
        self,
        dialog: Locator,
    ) -> Locator | None:

        selectors = [

            "[data-lexical-editor='true']",

            "div[data-lexical-editor='true'][role='textbox']",

            "[contenteditable='true'][role='textbox']",

            "[contenteditable='true']",

        ]

        for selector in selectors:

            locator = dialog.locator(selector)

            for i in range(locator.count()):

                item = locator.nth(i)

                try:

                    if item.is_visible(timeout=500):

                        return item

                except Exception:

                    pass

        return None

    def _type_content(
        self,
        page: Page,
        editor: Locator,
        content: str,
    ) -> None:
        editor.scroll_into_view_if_needed()
        editor.click(
            force=True,
            timeout=10_000,
        )
        page.wait_for_timeout(400)

        try:
            editor.focus()
        except Exception:
            pass

        page.wait_for_timeout(300)

        try:
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
        except Exception:
            pass

        page.wait_for_timeout(200)

        # Lexical Editor 使用 insert_text 最穩定。
        page.keyboard.insert_text(content)
        page.wait_for_timeout(800)

        current_text = ""

        try:
            current_text = str(
                editor.evaluate(
                    """
                    element => (
                        element.innerText
                        || element.textContent
                        || ''
                    ).trim()
                    """
                )
            )
        except Exception:
            pass

        if not current_text:
            editor.click(force=True)
            page.keyboard.type(
                content,
                delay=8,
            )
            page.wait_for_timeout(800)

            try:
                current_text = str(
                    editor.evaluate(
                        """
                        element => (
                            element.innerText
                            || element.textContent
                            || ''
                        ).trim()
                        """
                    )
                )
            except Exception:
                pass

        if not current_text:
            raise RuntimeError(
                "已找到 Facebook Lexical 編輯器，但文字未能寫入。"
            )

    def _upload_images(
        self,
        page: Page,
        image_paths: list[str],
    ) -> None:
        if not image_paths:
            return

        if self._try_file_inputs(
            page,
            image_paths,
        ):
            return

        photo_labels = [
            "相片／影片",
            "相片/影片",
            "相片或影片",
            "Photo/video",
            "Photo or video",
        ]

        for label in photo_labels:
            candidates = [
                page.get_by_role(
                    "button",
                    name=label,
                    exact=False,
                ),
                page.get_by_text(
                    label,
                    exact=False,
                ),
            ]

            for candidate in candidates:
                if not self._click_first_visible(candidate):
                    continue

                page.wait_for_timeout(1000)

                if self._try_file_inputs(
                    page,
                    image_paths,
                ):
                    return

        raise RuntimeError(
            "文字已填入，但找不到 Facebook 圖片上傳欄位。"
        )

    def _try_file_inputs(
        self,
        page: Page,
        image_paths: list[str],
    ) -> bool:
        selectors = [
            "div[role='dialog'] input[type='file'][accept*='image']",
            "div[role='dialog'] input[type='file']",
            "input[type='file'][accept*='image']",
            "input[type='file']",
        ]

        for selector in selectors:
            inputs = page.locator(selector)

            for index in range(inputs.count() - 1, -1, -1):
                file_input = inputs.nth(index)

                try:
                    file_input.set_input_files(
                        image_paths,
                        timeout=8_000,
                    )

                    page.wait_for_timeout(
                        self._image_wait_time(
                            len(image_paths)
                        )
                    )

                    return True

                except Exception:
                    continue

        return False

    @staticmethod
    def _get_valid_image_paths(
        image_paths: list[str],
    ) -> list[str]:
        valid_paths: list[str] = []

        for image_path in image_paths:
            path = Path(image_path).expanduser()

            if not path.is_file():
                continue

            if path.suffix.lower() not in {
                ".jpg",
                ".jpeg",
                ".png",
                ".webp",
            }:
                continue

            valid_paths.append(
                str(path.resolve())
            )

        return valid_paths

    @staticmethod
    def _image_wait_time(
        image_count: int,
    ) -> int:
        # 最少等候 4 秒，多張照片增加等待時間。
        return max(
            4_000,
            min(20_000, image_count * 2_000),
        )

    @staticmethod
    def _click_first_visible(
        locator: Locator,
    ) -> bool:
        count = locator.count()

        for index in range(count):
            item = locator.nth(index)

            try:
                if item.is_visible(timeout=1000):
                    item.click(timeout=5000)
                    return True
            except Exception:
                continue

        return False

    @staticmethod
    def _get_page(
        context: BrowserContext,
    ) -> Page:
        return (
            context.pages[0]
            if context.pages
            else context.new_page()
        )

    @staticmethod
    def _wait_until_browser_closed(
        page: Page,
        context: BrowserContext,
    ) -> None:
        try:
            # 最長保留 30 分鐘。
            # 通常完成檢查後直接關閉 Chromium 即可。
            page.wait_for_timeout(
                30 * 60 * 1000
            )
        except Exception:
            pass
        finally:
            try:
                context.close()
            except Exception:
                pass

    def _open_context(
        self,
        playwright: Playwright,
    ) -> BrowserContext:
        # 防呆檢查：確認隨附的 Chromium 真的存在，避免拋出很難懂的
        # [WinError 2] 系統找不到指定的檔案（見 browser_runtime.py 的說明）。
        verify_bundled_browser_or_raise()

        context = (
            playwright.chromium
            .launch_persistent_context(
                user_data_dir=str(
                    self.profile_dir.resolve()
                ),
                headless=False,
                viewport={
                    "width": 1400,
                    "height": 900,
                },
            )
        )

        context.set_default_timeout(10_000)

        return context