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

                        results.append(
                            {
                                "url": target_url,
                                "success": True,
                                "message": "發布完成",
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

    def delete_post(self, remote_post_url: str) -> dict[str, Any]:
        """刪除一篇 HouseFlow 自己發布、且已經有可靠 remote_post_url 的
        貼文。呼叫端（AutomationEngine）必須先確認這個 URL 存在且可靠
        才能呼叫這裡 —— 這個方法本身不做任何「用文案/物件名稱/時間找
        貼文」之類的猜測性比對，只會直接開啟這個貼文自己的網址操作。

        目前沒有任何發布流程會回傳可靠的 remote_post_url（見
        publish_posts() 的說明），所以這個方法目前實際上不會被正式
        呼叫到；先建好架構與安全介面，selector 是參考現有
        _click_publish 等方法推測的合理操作流程，還沒有機會對真正的
        Facebook 介面驗證過，正式使用前需要真人在允許的範圍內測試。

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