from __future__ import annotations

import re
import unicodedata
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
        self,
        remote_post_url: str,
        expected_content_prefix: str = "",
        expected_post_id: str = "",
    ) -> dict[str, Any]:
        """刪除一篇 HouseFlow 自己發布、且已經有可靠 remote_post_url 的
        貼文。呼叫端（AutomationEngine）必須先確認這個 URL 存在且可靠
        才能呼叫這裡 —— 這個方法本身不做任何「用文案/物件名稱/時間找
        貼文」之類的猜測性比對，只會直接開啟這個貼文自己的網址操作。

        刪除前的身分驗證（任何一項不通過就直接安全失敗，不會強行刪除）：
        A. URL identity——導覽完成後實際落在的網址，如果呼叫端有給
           expected_post_id 就要求解析出的 post_id 完全相符；沒有給
           post_id 的話，退一步比較正規化後的網址（拿掉 Facebook 自己
           加的追蹤參數）是不是同一篇貼文（見 _permalink_group_key）。
        B. content fingerprint——如果呼叫端有提供 expected_content_prefix
           （該筆 schedule 自己的文案），用跟 capture_published_post()
           完全同一套規則（_build_fingerprint/_fingerprint_matches_text）
           確認頁面實際顯示的內容真的符合，不是各自維護一份不一致的
           比對邏輯。

        2026-09-21：先前版本這裡自己另外算了一份 marker（沒有拿掉表情
        符號），跟 capture_published_post() 修過的版本不一致，導致明明
        capture 抓得到的貼文，delete_post() 自己的安全檢查卻誤判內容
        不符、擋下正確的刪除操作（schedule id=7 的第一輪真實刪除測試
        就是被這個 bug 擋下的）。這一版改成兩邊共用同一份 fingerprint
        邏輯，不會再各自為政。

        找「更多選項」按鈕時要求畫面上「剛好只有一個」符合的候選才會
        繼續——同一次對著 /photo/ 永久連結頁面的真實診斷發現，那種
        頁面上還會有很多其他人「留言」自己的「更多關於＿的選項」按鈕
        （不是「貼文採取的動作」這個措辭，不會誤觸），但為了保險，
        還是明確檢查數量剛好是 1，不是盲目挑「畫面上第一個」。

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

                # --- A. URL identity ---
                actual_url = page.url
                id_match = self._POST_ID_PATTERN.search(actual_url)
                actual_post_id = id_match.group(1) if id_match else ""
                if expected_post_id:
                    if actual_post_id != expected_post_id:
                        return {
                            "success": False,
                            "message": (
                                f"安全檢查失敗：目前頁面解析出的 post_id"
                                f"（{actual_post_id or '無法讀取'}）跟預期的"
                                f"post_id（{expected_post_id}）不符，"
                                "為避免刪錯貼文已中止操作。"
                            ),
                        }
                elif self._permalink_group_key(actual_url) != self._permalink_group_key(remote_post_url):
                    return {
                        "success": False,
                        "message": "安全檢查失敗：導覽後的網址跟預期的 post_url 不是同一篇貼文，"
                        "為避免刪錯貼文已中止操作。",
                    }

                # --- B. content fingerprint ---
                if expected_content_prefix:
                    fingerprint = self._build_fingerprint(expected_content_prefix)
                    if fingerprint["marker"]:
                        try:
                            page_text = page.inner_text("body", timeout=5_000)
                        except Exception:
                            page_text = ""
                        if not self._fingerprint_matches_text(fingerprint, page_text):
                            return {
                                "success": False,
                                "message": "安全檢查失敗：這個網址目前顯示的內容跟預期的貼文不符，"
                                "為避免刪錯貼文已中止操作。",
                            }

                menu_button = page.locator('[aria-label*="貼文採取的動作"]')
                menu_count = menu_button.count()
                if menu_count == 0:
                    raise RuntimeError("找不到貼文選項按鈕，無法刪除。")
                if menu_count > 1:
                    raise RuntimeError(
                        f"畫面上找到 {menu_count} 個可能的貼文選項按鈕，無法唯一判定要點哪一個，"
                        "為避免刪錯貼文已中止操作。"
                    )
                if not self._click_first_visible(menu_button):
                    raise RuntimeError("找不到貼文選項按鈕，無法刪除。")
                page.wait_for_timeout(800)

                opened_menus = page.locator('[role="menu"]')
                menu_open_count = opened_menus.count()
                if menu_open_count != 1:
                    raise RuntimeError(
                        f"點擊貼文選項後畫面上出現 {menu_open_count} 個選單，"
                        "無法確認要在哪一個裡面找「刪除貼文」，已中止操作。"
                    )
                opened_menu = opened_menus.first

                delete_action = opened_menu.get_by_role(
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

    # 2026-09-21 對著「schedule id=7 真實發布成功、但抓不到 permalink」
    # 這篇真實存在的貼文做過唯讀 DOM 診斷後，確認了上一版（2026-09-21
    # 稍早）的兩個假設都不成立：
    # 1. 剛發布的貼文不保證會馬上出現在動態消息首頁——同一篇貼文在
    #    首頁等了將近 8 分鐘都沒出現，但在帳號自己的「個人檔案／貼文」
    #    頁面上立刻就看得到（screenshot 證實）。
    # 2. aria-posinset 不是「一個 wrapper = 一篇貼文」的可靠邊界——這
    #    只在動態消息首頁成立；在個人檔案頁面，貼文本身的容器根本沒有
    #    aria-posinset 屬性（那個屬性出現在更高、範圍大很多的祖先上，
    #    不對應單一貼文）。
    # 3. 貼文自己的時間戳記文字（「剛剛」「N分鐘」）不保證存在於可讀取
    #    的 DOM 裡——這篇真實貼文的容器內完全沒有任何 <time>/<abbr>、
    #    也沒有任何連結帶著這種可見文字或 aria-label，即使畫面上明明
    #    顯示著「11分鐘」。
    #
    # 因此改成：唯一可靠、兩種頁面都驗證過存在的錨點是「更多選項」
    # 按鈕本身（aria-label 為「對＿的這則貼文採取的動作」），直接以
    # 它為起點往上找「文字夠長」的最小容器當作貼文邊界，不再依賴
    # aria-posinset。時間窗口驗證也不再要求 Facebook 必須顯示「剛剛／
    # N分鐘」這段文字（已證實常常不存在）——改成用「我們自己知道剛按
    # 下發布、只在有限的 polling 視窗內搜尋」作為時間佐證；但如果容器
    # 內剛好找得到「N天／N週／昨天」這種明顯較舊的文字，仍然視為負向
    # 訊號直接排除，避免誤認到同一物件之前貼過的舊貼文。
    _PERMALINK_SHAPE_PATTERN = re.compile(
        r"/posts/|/videos/|story_fbid=|permalink\.php|/photo(?:\.php|/)"
    )
    # 比 _PERMALINK_SHAPE_PATTERN 更嚴格：不含 /photo/，用來判斷「這個
    # 候選是明確的貼文網址，還是只是相片網址」，同一群組裡優先保留前者。
    _PERMALINK_IS_POST_SHAPE = re.compile(
        r"/posts/|/videos/|story_fbid=|permalink\.php"
    )
    # 貼文永久連結的 ID 現在多半是 pfbid 開頭的英數字 token（例如
    # .../posts/pfbid02t7umeRc7HyxPh6...），不是只有數字，所以這裡除了
    # 舊版純數字樣式，也要接受 pfbid 樣式；抓不到 ID 不影響安全性，
    # post_url 本身才是刪文流程實際要用的欄位（見下方 STEP 6：post_id
    # 是 optional，post_url 才是 required）。
    _POST_ID_PATTERN = re.compile(
        r"(?:story_fbid=|/posts/|/videos/|[?&]fbid=)(pfbid[A-Za-z0-9]+|\d+)"
    )

    # 2026-09-21 對著 schedule id=7 這篇真實貼文實測發現：貼文預覽文字
    # 裡的表情符號（🏠💰📍等）完全沒有進到瀏覽器算出來的 innerText（研判
    # 是畫成獨立的 <img>，不算文字內容），如果 marker 裡含有表情符號，
    # 光是這一點就會讓內容比對永遠比不到，先把它們拿掉再比對。
    _EMOJI_PATTERN = re.compile(
        "["
        "\U0001F300-\U0001FAFF"
        "\U00002600-\U000027BF"
        "\U0001F1E6-\U0001F1FF"
        "\U00002190-\U000021FF"
        "\U00002B00-\U00002BFF"
        "]+",
        flags=re.UNICODE,
    )
    # 同一次實測也發現：動態消息／個人檔案上的貼文預覽會用「……查看
    # 更多」截斷過長內容，這篇貼文（去掉表情符號後）在第 70～79 字之間
    # 被截斷；用 60 字當 marker 長度，在截斷點之前留有安全餘裕，同時
    # 仍然足夠有辨識度（涵蓋不只一句話）。
    _CONTENT_MARKER_LENGTH = 60

    # 2026-09-21：capture_published_post() 與 delete_post() 原本各自維護
    # 一份自己的內容比對邏輯，兩邊不一致——delete_post() 那份沒有跟著
    # 更新去掉表情符號，導致明明是同一篇、capture 抓得到的貼文，
    # delete_post() 自己的安全檢查卻誤判不符，擋下了正確的刪除操作。
    # 這裡改成兩邊共用同一套 fingerprint 邏輯，不是「固定取前 60 字」，
    # 而是額外抽出售價、房屋名稱這種更有辨識度的 token，一起要求比對
    # 到——避免只看一段文字前綴，被截斷或格式微調就整個比對失敗。
    _PRICE_TOKEN_PATTERN = re.compile(r"[\d,]+\s*萬")
    _TITLE_TOKEN_PATTERN = re.compile(r"【([^】]{2,30})】")

    def _normalize_text(self, text: str) -> str:
        """兩邊共用的正規化規則：NFKC 處理全形／半形字元與相容標點，
        拿掉表情符號（已證實不會進到 Facebook 算出來的頁面文字），
        並把所有連續空白（含換行、Facebook DOM 拆字產生的空白）收斂
        成單一半形空白。"""
        text = unicodedata.normalize("NFKC", text)
        text = self._EMOJI_PATTERN.sub("", text)
        return " ".join(text.split())

    def _build_fingerprint(self, content: str) -> dict[str, str]:
        """從一段文案（schedule 自己的 copy_text）算出用來辨識這篇貼文
        的 fingerprint：內容開頭的 marker，加上（如果找得到）售價、
        房屋名稱這兩個更有辨識度的 token。capture_published_post() 跟
        delete_post() 都呼叫這裡，確保兩邊用的是同一套規則。"""
        normalized = self._normalize_text(content)
        marker = normalized[: self._CONTENT_MARKER_LENGTH]
        price_match = self._PRICE_TOKEN_PATTERN.search(normalized)
        title_match = self._TITLE_TOKEN_PATTERN.search(normalized)
        return {
            "marker": marker if len(marker) >= 10 else "",
            "price_token": price_match.group(0) if price_match else "",
            "title_token": title_match.group(1) if title_match else "",
        }

    def _fingerprint_matches_text(self, fingerprint: dict[str, str], page_text: str) -> bool:
        """檢查一段頁面文字是否符合 fingerprint——marker 是必要條件，
        售價／房屋名稱 token（如果 fingerprint 裡有）也都要比對到，
        任何一項不符就視為不是同一篇貼文。"""
        marker = fingerprint.get("marker", "")
        if not marker:
            return False
        normalized_page = self._normalize_text(page_text)
        if marker not in normalized_page:
            return False
        price_token = fingerprint.get("price_token", "")
        if price_token and price_token not in normalized_page:
            return False
        title_token = fingerprint.get("title_token", "")
        if title_token and title_token not in normalized_page:
            return False
        return True

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

    # 用「登入帳號本人的顯示名稱」找左側導覽列裡指向自己個人檔案的
    # 連結，讀出 href——不是硬編碼特定帳號，任何房仲使用 HouseFlow
    # 都適用，因為名字是從 _OWN_NAME_FROM_COMPOSER_JS 動態讀出來的。
    _OWN_PROFILE_URL_FROM_NAV_JS = r"""
        (ownName) => {
            if (!ownName) return null;
            const links = Array.from(document.querySelectorAll('a[href]'));
            for (const a of links) {
                const label = a.getAttribute('aria-label') || '';
                const text = (a.textContent || '').trim();
                if (label === ownName || text === ownName) {
                    return a.getAttribute('href');
                }
            }
            return null;
        }
    """

    # 掃描目前 DOM 裡所有「更多選項」按鈕（貼文自己專屬的操作選單，
    # 排除留言自己的留言操作選單），往上找最小的、內容夠長的共同容器
    # 當作這篇貼文的邊界，回傳每篇的作者、內容是否比對到 marker、
    # 容器內是否有「明顯較舊」的負向時間訊號、以及容器內所有看起來
    # 像貼文/相片永久連結的 href（不再要求一定要跟某個時間戳記連結
    # 綁在一起才算數——已證實這種綁定在部分頁面根本不存在）。
    #
    # 2026-09-21：selector 從「這則貼文採取的動作」放寬成「貼文採取的
    # 動作」——對著 schedule id=7 真實的 /photo/ 永久連結頁面實測發現，
    # 那個頁面貼文自己的按鈕 aria-label 是「可對此貼文採取的動作」
    # （沒有「這則」二字），跟動態消息／個人檔案頁面用的「對＿的這則
    # 貼文採取的動作」是不同措辭，但共同尾巴都是「貼文採取的動作」。
    _SCAN_CANDIDATES_JS = r"""
        (fingerprint) => {
            const { marker, priceToken, titleToken } = fingerprint;
            const AUTHOR_RE = /^對(.+)的這則貼文採取的動作$/;
            const COMPACT_TIME_RE = /^(剛剛|(\d+)\s*(秒|分鐘|小時|天|週)|昨天)$/;
            const RECENT_RE = /^(剛剛|(\d+)\s*(秒|分鐘|小時))/;
            const PERMALINK_RE = /\/posts\/|\/videos\/|story_fbid=|permalink\.php|\/photo(?:\.php|\/)/;

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

            const moreBtns = Array.from(
                document.querySelectorAll('[aria-label*="貼文採取的動作"]')
            );
            const seenContainers = new Set();
            const results = [];

            for (const moreBtn of moreBtns) {
                if (isInsideComment(moreBtn)) continue;

                // 不再用「文字長度 >= 門檻值」判斷有沒有爬到貼文邊界——
                // 已證實按鈕附近常常先遇到一堆與內容無關的圖示 alt text
                // （例如大量 alt="Facebook" 的裝飾用圖示），文字長度很快
                // 就超過任何合理門檻，卻完全還沒包含到貼文本文。改成
                // 直接往上爬，爬到「這一層的文字真的包含 marker」才停，
                // 這樣找到的一定是同時涵蓋按鈕與內容、且盡量小的容器。
                // NFKC 正規化跟 Python 那邊的 _normalize_text() 對齊
                // （全形／半形數字、標點、空白統一），不然 Python 建出來的
                // marker/priceToken/titleToken 含有 NFKC 轉換後的半形
                // 標點，這裡如果只做空白收斂、不做 NFKC，兩邊會永遠對不
                // 起來——JS 字串原生支援 .normalize('NFKC')，跟 Python
                // unicodedata.normalize('NFKC', ...) 是同一套 Unicode
                // 正規化演算法。
                let container = moreBtn;
                let hops = 0;
                let matched = false;
                while (container && hops < 20) {
                    const text = (container.innerText || '').normalize('NFKC').replace(/\s+/g, ' ').trim();
                    if (text.includes(marker)) { matched = true; break; }
                    container = container.parentElement;
                    hops += 1;
                }
                if (!matched || !container) continue;
                if (seenContainers.has(container)) continue;
                seenContainers.add(container);

                // fingerprint 裡的售價／房屋名稱 token（如果有）也要在同一個
                // 容器內找到，多一層交叉驗證，不是只靠內容前綴。
                const containerFullText = (container.innerText || '').normalize('NFKC').replace(/\s+/g, ' ').trim();
                if (priceToken && !containerFullText.includes(priceToken)) continue;
                if (titleToken && !containerFullText.includes(titleToken)) continue;

                const moreLabel = moreBtn.getAttribute('aria-label') || '';
                const authorMatch = moreLabel.match(AUTHOR_RE);
                const author = authorMatch ? authorMatch[1] : null;

                // 容器內可能剛好包住展開的留言（留言有自己的時間戳記／
                // 連結），這裡兩個收集都要排除留言範圍內的元素，不然
                // 留言自己的「N天前」或連結會被誤判成貼文本身的訊號。
                const shortTexts = Array.from(container.querySelectorAll('*'))
                    .filter(el => el.children.length === 0 && !isInsideComment(el))
                    .map(el => (el.textContent || '').trim())
                    .filter(t => t.length > 0 && t.length <= 6 && COMPACT_TIME_RE.test(t));
                const hasStaleSignal = shortTexts.some(t => !RECENT_RE.test(t));

                const hrefs = Array.from(container.querySelectorAll('a[href]'))
                    .filter(a => !isInsideComment(a))
                    .map(a => a.getAttribute('href'))
                    .filter(h => h && PERMALINK_RE.test(h));

                results.push({ author, hasStaleSignal, hrefs });
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
        2. 時間窗口——不再要求 Facebook 一定要顯示「剛剛／N分鐘」這段
           文字（已證實常常不存在），改成「我們自己只在剛按下發布後
           的有限 polling 視窗內搜尋」作為時間佐證；但如果容器內剛好
           找到「N天／N週／昨天」這種明顯較舊的文字，仍視為負向訊號
           直接排除，避免誤判成同一物件之前貼過的舊貼文。
        3. permalink 格式驗證——貼文容器內要找到看起來像真的貼文／
           相片永久連結（/posts/、/videos/、story_fbid=、
           permalink.php、/photo/ 其中一種），且同一篇貼文對應的所有
           候選網址（例如多張相片各自的 /photo/ 連結）唯一收斂成一個
           判定結果。
        4. 作者交叉驗證（附加訊號，非必要條件）——如果讀得到目前登入
           帳號的真實顯示名稱，且這篇候選貼文的作者跟它不同，就直接
           排除這個候選；讀不到就不套用這一條，不影響前三條的判定。

        任何一步不確定、或同時有超過一篇候選都通過驗證（無法唯一判定
        是哪一篇）——就直接回傳空字典，呼叫端維持既有安全機制（post_url
        留空 -> 需要人工刪除），絕對不會用猜的方式硬填一個 identifier。

        用來比對的 fingerprint（見 _build_fingerprint()）會先拿掉表情
        符號（🏠💰📍等）再截短到 _CONTENT_MARKER_LENGTH——同一次真實
        診斷發現表情符號不會進到 Facebook 算出來的 innerText（研判被
        畫成獨立的 <img>），而且貼文預覽有「……查看更多」的截斷長度
        限制，marker 太長、或含有表情符號，都會讓內容比對永遠比不到，
        跟容器選對不對完全無關。這套 fingerprint 邏輯跟 delete_post()
        共用同一份（_build_fingerprint/_fingerprint_matches_text），
        不會再各自維護一份不一致的比對規則。

        post_url 是必要欄位，post_id 是 optional——Facebook 現在的
        permalink 常用 pfbid 這種不透明英數字 token，不一定能可靠取得
        傳統數字 post_id，但只要 post_url 唯一且經過驗證，刪文流程就
        可以直接用它定位，不會因為抓不到 post_id 就判定整個 capture
        失敗。

        2026-09-21：先對著一篇真實已發布、但用舊版邏輯抓不到 permalink
        的貼文做了唯讀 DOM 診斷，發現舊版建立在「動態消息首頁會馬上
        顯示剛發的貼文」「aria-posinset 等於一篇貼文的邊界」「貼文一定
        有可讀取的剛剛/N分鐘文字」這三個假設，在這篇真實貼文上全部不
        成立——首頁等了 8 分鐘沒出現，貼文實際出現在帳號自己的個人
        檔案頁面，且該頁面的貼文容器沒有 aria-posinset、也完全沒有
        任何時間戳記文字或連結。這一版改用「更多選項按鈕」當唯一穩定
        錨點、改成優先導覽到帳號自己的個人檔案頁面尋找，並把「時間
        窗口」驗證從「讀取 Facebook 顯示的相對時間文字」改成「我們自己
        的 polling 時間範圍 + 負向時間訊號排除」，已經直接對著這篇真實
        貼文驗證過可以成功抓到 post_url（見 test_post_capture.py /
        test_post_capture_fixture.py 的對應案例）。
        """
        effective_timeout_ms = timeout_ms if timeout_ms is not None else self._CAPTURE_TIMEOUT_MS

        fingerprint = self._build_fingerprint(content)
        if not fingerprint["marker"]:
            return {}

        try:
            own_name = page.evaluate(self._OWN_NAME_FROM_COMPOSER_JS)
        except Exception:
            own_name = None

        # 優先導覽到帳號自己的個人檔案頁面——已證實剛發布的貼文會立刻
        # 出現在那裡，動態消息首頁不一定會（2026-09-21 真實測試曾經
        # 等了 8 分鐘都沒出現在首頁）。找不到個人檔案連結、或導覽失敗，
        # 就留在原本頁面繼續掃描，不會讓整個捕捉流程因此中止。
        if own_name:
            try:
                profile_href = page.evaluate(self._OWN_PROFILE_URL_FROM_NAV_JS, own_name)
            except Exception:
                profile_href = None
            if profile_href:
                profile_url = (
                    profile_href
                    if profile_href.startswith("http")
                    else f"https://www.facebook.com{profile_href}"
                )
                try:
                    page.goto(profile_url, wait_until="domcontentloaded", timeout=15_000)
                    page.wait_for_timeout(3000)
                except Exception:
                    pass

        elapsed = 0
        while elapsed < effective_timeout_ms:
            result = self._scan_and_extract(page, fingerprint, own_name)
            if result:
                return result

            page.wait_for_timeout(self._CAPTURE_POLL_INTERVAL_MS)
            elapsed += self._CAPTURE_POLL_INTERVAL_MS

        return {}

    def _permalink_group_key(self, post_url: str) -> str:
        """把同一篇貼文的多個候選網址（例如多張相片各自的 /photo/
        連結、或同一個連結重複出現但追蹤參數不同）歸成同一組，
        判斷「唯一候選」時才不會被雜訊誤判成多篇。"""
        if "/photo" in post_url:
            match = re.search(r"[?&]set=([^&]+)", post_url)
            if match:
                return f"photo-set:{match.group(1)}"
        # 拿掉 Facebook 自己加的追蹤參數（__cft__/__tn__），只留下真正
        # 用來定位貼文的路徑，避免同一篇貼文因為追蹤參數不同就被誤判
        # 成兩個不同候選。
        base = post_url.split("&__cft__")[0].split("?__cft__")[0]
        base = base.split("&__tn__")[0].split("?__tn__")[0]
        return base

    def _scan_and_extract(
        self, page: Page, fingerprint: dict[str, str], own_name: str | None
    ) -> dict[str, str]:
        try:
            candidates = page.evaluate(
                self._SCAN_CANDIDATES_JS,
                {
                    "marker": fingerprint.get("marker", ""),
                    "priceToken": fingerprint.get("price_token", ""),
                    "titleToken": fingerprint.get("title_token", ""),
                },
            )
        except Exception:
            return {}

        strong_matches: list[dict[str, str]] = []

        for candidate in candidates or []:
            if candidate.get("hasStaleSignal"):
                continue
            author = candidate.get("author")
            if own_name and author and author != own_name:
                continue

            groups: dict[str, str] = {}
            for href in candidate.get("hrefs") or []:
                post_url = href if href.startswith("http") else f"https://www.facebook.com{href}"
                if not self._PERMALINK_SHAPE_PATTERN.search(post_url):
                    continue
                key = self._permalink_group_key(post_url)
                if key not in groups:
                    groups[key] = post_url
                elif self._PERMALINK_IS_POST_SHAPE.search(post_url) and not self._PERMALINK_IS_POST_SHAPE.search(
                    groups[key]
                ):
                    # 同一群組內，優先保留明確的貼文網址而不是相片網址。
                    groups[key] = post_url

            if len(groups) != 1:
                continue

            post_url = next(iter(groups.values()))
            post_id = ""
            id_match = self._POST_ID_PATTERN.search(post_url)
            if id_match:
                post_id = id_match.group(1)

            strong_matches.append({"post_url": post_url, "post_id": post_id})

        # 同一輪掃描裡只要出現一個以上不同的候選貼文，代表無法唯一
        # 判定是哪一篇，安全起見一律不採信、回傳空字典。
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