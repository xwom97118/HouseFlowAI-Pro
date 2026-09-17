from __future__ import annotations

import hashlib
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urljoin, urlparse

import requests
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

from app.services import app_paths
from app.services.http_client import build_session


@dataclass
class SyncResult:
    found: int
    saved: int
    properties: list[dict]
    message: str
    failed_pages: list[int] = field(default_factory=list)
    duration_seconds: int = 0
    cancelled: bool = False

    @property
    def had_failures(self) -> bool:
        return bool(self.failed_pages) or self.cancelled



class YungchingSyncService:
    """從永慶／台慶店頭列表頁擷取物件資料及物件照片。"""

    MAX_IMAGES_PER_PROPERTY = 20
    PROPERTY_WORKERS = 8

    def __init__(self) -> None:
        self._thread_local = threading.local()
        self.session = self._create_session()

        # property_images_dir() 已經會自動建立資料夾。
        app_paths.property_images_dir()

    def _create_session(self) -> requests.Session:
        # 與 universal_import_service 共用同一套 certifi CA /
        # RelaxedTLSAdapter / retry 設定（見 http_client.py），
        # 這裡沿用原本已經驗證成功的 pool size 與 retry 參數。
        return build_session(
            pool_connections=40,
            pool_maxsize=40,
            retry_total=3,
            backoff_factor=0.6,
        )

    def _get_session(self) -> requests.Session:
        session = getattr(
            self._thread_local,
            "session",
            None,
        )

        if session is None:
            session = self._create_session()
            self._thread_local.session = session

        return session

    def _get_html_fast(
        self,
        url: str,
        timeout: int = 30,
    ) -> str:
        """先用 requests；只有失敗時才啟動 Playwright。"""
        try:
            response = self._get_session().get(url, timeout=timeout)
            response.raise_for_status()
            response.encoding = (
                response.apparent_encoding
                or response.encoding
                or "utf-8"
            )
            return response.text
        except Exception:
            return self._get_html_playwright(url)

    @staticmethod
    def _get_html_playwright(url: str) -> str:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    ignore_https_errors=True,
                    locale="zh-TW",
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/150.0 Safari/537.36"
                    ),
                )
                page = context.new_page()
                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
                try:
                    page.wait_for_load_state("networkidle", timeout=8_000)
                except Exception:
                    page.wait_for_timeout(1200)
                return page.content()
            finally:
                browser.close()

    def fetch(
        self,
        source_url: str,
        progress_callback: Callable[[dict], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> SyncResult:
        started_at = time.perf_counter()
        source_url = source_url.strip()

        if not source_url.startswith(("http://", "https://")):
            raise ValueError(
                "網址格式不正確，必須以 http:// 或 https:// 開頭。"
            )

        first_html = self._get_html_fast(source_url)

        first_soup = BeautifulSoup(
            first_html,
            "lxml",
        )

        total_pages = self._detect_total_pages(
            first_soup,
            source_url,
        )

        self._notify(
            progress_callback,
            stage="pages",
            current=0,
            total=total_pages,
            message=f"偵測到 {total_pages} 頁，開始讀取列表。",
        )

        all_properties: list[dict] = []
        seen: set[str] = set()
        failed_pages: list[int] = []

        cancelled = False

        for page_number in range(1, total_pages + 1):
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                break

            self._notify(
                progress_callback,
                stage="pages",
                current=page_number,
                total=total_pages,
                message=f"正在讀取第 {page_number}/{total_pages} 頁。",
            )

            try:
                if page_number == 1:
                    page_url = source_url
                    soup = first_soup
                else:
                    page_url = self._build_page_url(
                        source_url,
                        page_number,
                    )

                    html = self._get_html_fast(page_url)

                    soup = BeautifulSoup(
                        html,
                        "lxml",
                    )

                page_properties = self._parse_list_page(
                    soup,
                    page_url,
                )

                for property_data in page_properties:
                    unique_key = (
                        str(
                            property_data.get(
                                "external_id",
                                "",
                            )
                        ).strip()
                        or str(
                            property_data.get(
                                "url",
                                "",
                            )
                        ).strip()
                    )

                    if not unique_key:
                        continue

                    if unique_key in seen:
                        continue

                    seen.add(unique_key)
                    all_properties.append(
                        property_data
                    )

            except Exception:
                failed_pages.append(page_number)

        downloaded_total = 0
        failed_image_properties = 0
        failed_detail_properties = 0

        total_properties = len(all_properties)
        completed_count = 0

        if cancelled:
            all_properties = []
            total_properties = 0

        with ThreadPoolExecutor(
            max_workers=self.PROPERTY_WORKERS
        ) as executor:
            future_map = {
                executor.submit(
                    self._enrich_property,
                    property_data,
                    index,
                ): index
                for index, property_data in enumerate(
                    all_properties,
                    start=1,
                )
            }

            for future in as_completed(future_map):
                index = future_map[future]

                try:
                    result = future.result()
                except Exception as exc:
                    result = {
                        "index": index,
                        "image_count": 0,
                        "detail_failed": True,
                        "image_failed": True,
                        "error": str(exc),
                    }

                completed_count += 1
                downloaded_total += int(
                    result.get("image_count", 0)
                )

                if result.get("detail_failed"):
                    failed_detail_properties += 1

                if result.get("image_failed"):
                    failed_image_properties += 1

                title = str(
                    all_properties[index - 1].get(
                        "title",
                        "",
                    )
                ).strip()

                self._notify(
                    progress_callback,
                    stage="properties",
                    current=completed_count,
                    total=total_properties,
                    message=(
                        f"已完成 {completed_count}/{total_properties} 筆："
                        f"{title or '未命名物件'}"
                    ),
                )

        elapsed_seconds = int(
            time.perf_counter() - started_at
        )
        elapsed_text = self._format_elapsed(
            elapsed_seconds
        )

        message_parts = [
            f"共讀取 {total_pages} 頁",
            f"找到 {len(all_properties)} 筆物件",
            f"同步 {downloaded_total} 張照片",
            f"耗時 {elapsed_text}",
        ]

        if failed_pages:
            message_parts.append(
                "失敗頁面："
                + "、".join(
                    str(page)
                    for page in failed_pages
                )
            )

        if failed_detail_properties:
            message_parts.append(
                f"{failed_detail_properties} 筆詳細資料補抓失敗"
            )

        if failed_image_properties:
            message_parts.append(
                f"{failed_image_properties} 筆照片同步失敗"
            )

        if cancelled:
            message_parts.append("同步已由使用者取消")

        return SyncResult(
            found=len(all_properties),
            saved=0,
            properties=all_properties,
            message="，".join(message_parts) + "。",
            failed_pages=failed_pages,
            duration_seconds=elapsed_seconds,
            cancelled=cancelled,
        )

    def _detect_total_pages(
        self,
        soup: BeautifulSoup,
        source_url: str,
    ) -> int:
        page_numbers = [1]

        for link in soup.find_all("a", href=True):
            href = str(
                link.get("href", "")
            ).strip()

            full_url = urljoin(
                source_url,
                href,
            )

            match = re.search(
                r"[?&]pg=(\d+)",
                full_url,
                flags=re.IGNORECASE,
            )

            if not match:
                continue

            try:
                page_numbers.append(
                    int(match.group(1))
                )
            except ValueError:
                continue

        return max(page_numbers)

    @staticmethod
    def _build_page_url(
        source_url: str,
        page_number: int,
    ) -> str:
        if re.search(
            r"([?&])pg=\d+",
            source_url,
            flags=re.IGNORECASE,
        ):
            return re.sub(
                r"([?&])pg=\d+",
                rf"\g<1>pg={page_number}",
                source_url,
                count=1,
                flags=re.IGNORECASE,
            )

        separator = (
            "&"
            if "?" in source_url
            else "?"
        )

        return (
            f"{source_url}"
            f"{separator}pg={page_number}"
        )

    def _parse_list_page(
        self,
        soup: BeautifulSoup,
        source_url: str,
    ) -> list[dict]:
        results: list[dict] = []
        seen: set[str] = set()

        for link in soup.find_all("a", href=True):
            href = str(link.get("href", "")).strip()
            full_url = urljoin(source_url, href)

            if not self._is_property_url(full_url):
                continue

            link_text = self._clean_text(
                link.get_text(" ", strip=True)
            )
            container_text = self._find_property_container_text(
                link
            )

            combined = self._clean_text(
                f"{link_text} {container_text}"
            )
            external_id = self._extract_external_id(
                combined,
                full_url,
            )

            unique_key = external_id or full_url

            if unique_key in seen:
                continue

            title, address = self._extract_title_and_address(
                link_text,
                container_text,
            )

            if not title:
                continue

            seen.add(unique_key)

            results.append(
                {
                    "external_id": external_id,
                    "title": title,
                    "address": address,
                    "price": self._extract_price(combined),
                    "layout": self._extract_layout(combined),
                    "size": self._extract_size(combined),
                    "url": full_url,
                    "status": "active",
                    "source_site": "yungching",
                }
            )

        return results

    def _enrich_property(
        self,
        property_data: dict,
        index: int,
    ) -> dict:
        property_url = str(
            property_data.get(
                "url",
                "",
            )
        ).strip()

        detail_failed = False
        image_failed = False

        # 只有缺少重要欄位時才進詳細頁補抓。
        needs_detail = any(
            not str(
                property_data.get(field, "")
            ).strip()
            for field in (
                "price",
                "layout",
                "size",
            )
        )

        if needs_detail and property_url:
            try:
                detail_data = self._fetch_property_details(
                    property_url
                )

                for key in (
                    "price",
                    "layout",
                    "size",
                    "property_type",
                    "community",
                    "features",
                ):
                    value = detail_data.get(key)

                    if value and (
                        key not in property_data
                        or not property_data.get(key)
                    ):
                        property_data[key] = value

            except Exception as exc:
                property_data["detail_error"] = str(exc)
                detail_failed = True

        try:
            image_urls = self._fetch_property_image_urls(
                property_url
            )

            image_paths = self._download_property_images(
                property_data=property_data,
                image_urls=image_urls,
            )

            property_data["image_urls"] = image_urls
            property_data["image_paths"] = image_paths
            property_data["image_count"] = len(
                image_paths
            )

        except Exception as exc:
            property_data["image_urls"] = []
            property_data["image_paths"] = []
            property_data["image_count"] = 0
            property_data["image_error"] = str(exc)
            image_failed = True

        property_data["sync_position"] = index

        return {
            "index": index,
            "image_count": int(
                property_data.get(
                    "image_count",
                    0,
                )
            ),
            "detail_failed": detail_failed,
            "image_failed": image_failed,
        }

    def _fetch_property_details(
        self,
        property_url: str,
    ) -> dict:
        if not property_url:
            return {}

        html = self._get_html_fast(property_url)

        soup = BeautifulSoup(
            html,
            "lxml",
        )
        text = self._clean_text(
            soup.get_text(
                " ",
                strip=True,
            )
        )

        title = ""
        title_tag = soup.find("h1")

        if title_tag:
            title = self._clean_text(
                title_tag.get_text(
                    " ",
                    strip=True,
                )
            )

        combined = self._clean_text(
            f"{title} {text}"
        )

        return {
            "price": self._extract_detail_price(combined),
            "layout": self._extract_layout(combined),
            "size": self._extract_size(combined),
            "property_type": self._detect_property_type(
                combined
            ),
            "community": self._extract_community(
                soup,
                combined,
            ),
            "features": self._extract_features(
                combined
            ),
        }

    def _extract_detail_price(
        self,
        text: str,
    ) -> str:
        labelled_patterns = (
            r"(?:總價|售價|開價|價格)"
            r"\s*[:：]?\s*"
            r"(\d+(?:\.\d+)?\s*億"
            r"(?:\s*[\d,]+(?:\.\d+)?\s*萬)?)",
            r"(?:總價|售價|開價|價格)"
            r"\s*[:：]?\s*"
            r"([\d,]+(?:\.\d+)?)\s*萬"
            r"(?!\s*(?:/|／)\s*坪)",
        )

        for pattern in labelled_patterns:
            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if not match:
                continue

            value = self._clean_text(
                match.group(1)
            ).replace(" ", "")

            if "億" in value:
                return value

            return f"{value}萬"

        return self._extract_price(text)

    @staticmethod
    def _detect_property_type(
        text: str,
    ) -> str:
        mappings = (
            ("土地", ("農地", "建地", "工業地", "土地", "田", "旱")),
            ("店面", ("店面", "店住")),
            ("廠房", ("廠房", "工業廠房", "倉庫")),
            ("別墅", ("別墅",)),
            ("透天", ("透天",)),
            ("電梯大樓", ("大樓", "電梯大樓")),
            ("華廈", ("華廈",)),
            ("公寓", ("公寓",)),
            ("套房", ("套房",)),
        )

        for name, keywords in mappings:
            if any(
                keyword in text
                for keyword in keywords
            ):
                return name

        return "住宅"

    @staticmethod
    def _extract_community(
        soup: BeautifulSoup,
        text: str,
    ) -> str:
        labels = (
            "社區",
            "社區名稱",
            "大樓名稱",
        )

        for label in labels:
            pattern = re.compile(
                rf"{label}\s*[:：]?\s*"
                r"([^\s｜|，,]{2,30})"
            )
            match = pattern.search(text)

            if match:
                return match.group(1).strip()

        for element in soup.select(
            "[class*='community'], "
            "[id*='community']"
        ):
            value = re.sub(
                r"\s+",
                " ",
                element.get_text(
                    " ",
                    strip=True,
                ),
            ).strip()

            if 2 <= len(value) <= 40:
                return value

        return ""

    @staticmethod
    def _extract_features(
        text: str,
    ) -> list[str]:
        feature_map = (
            ("平面車位", ("平面車位", "坡道平面")),
            ("雙車位", ("雙車位", "兩個車位", "2車位")),
            ("景觀", ("景觀", "視野", "高樓層")),
            ("邊間", ("邊間", "三面採光")),
            ("採光佳", ("採光佳", "採光好", "明亮")),
            ("近交流道", ("交流道",)),
            ("近學區", ("學區", "國小", "國中")),
            ("近龍科", ("龍科", "龍潭科學園區")),
            ("低總價", ("低總價", "首購")),
            ("庭院", ("庭院", "花園")),
            ("電梯", ("電梯",)),
        )

        features: list[str] = []

        for name, keywords in feature_map:
            if any(
                keyword in text
                for keyword in keywords
            ):
                features.append(name)

        return features[:8]

    @staticmethod
    def _notify(
        callback: Callable[[dict], None] | None,
        *,
        stage: str,
        current: int,
        total: int,
        message: str,
    ) -> None:
        if callback is None:
            return

        try:
            callback(
                {
                    "stage": stage,
                    "current": current,
                    "total": total,
                    "message": message,
                }
            )
        except Exception:
            pass

    @staticmethod
    def _format_elapsed(
        seconds: int,
    ) -> str:
        minutes, remaining = divmod(
            max(0, seconds),
            60,
        )

        if minutes:
            return f"{minutes}分{remaining}秒"

        return f"{remaining}秒"

    def _fetch_property_detail_price(
        self,
        property_url: str,
    ) -> str:
        return str(
            self._fetch_property_details(
                property_url
            ).get("price", "")
        )

    def _fetch_property_image_urls(
        self,
        property_url: str,
    ) -> list[str]:
        if not property_url:
            return []

        html = self._get_html_fast(property_url)

        soup = BeautifulSoup(
            html,
            "lxml",
        )

        candidates: list[str] = []

        # 1. Open Graph 主圖。
        for meta in soup.select(
            "meta[property='og:image'], "
            "meta[name='twitter:image'], "
            "meta[property='twitter:image']"
        ):
            value = str(
                meta.get("content", "")
            ).strip()

            if value:
                candidates.append(
                    urljoin(property_url, value)
                )

        # 2. 頁面圖片與 lazy-load 圖片。
        image_attributes = (
            "src",
            "data-src",
            "data-original",
            "data-lazy-src",
            "data-image",
            "data-url",
        )

        for image in soup.find_all("img"):
            for attribute in image_attributes:
                value = str(
                    image.get(attribute, "")
                ).strip()

                if value:
                    candidates.append(
                        urljoin(property_url, value)
                    )

            srcset = str(
                image.get("srcset", "")
            ).strip()

            if srcset:
                for item in srcset.split(","):
                    value = item.strip().split(" ")[0]

                    if value:
                        candidates.append(
                            urljoin(property_url, value)
                        )

        # 3. 從頁面 script / JSON 中擷取圖片網址。

        url_patterns = (
            r'https?:\\?/\\?/[^"\'\s<>]+?\.(?:jpg|jpeg|png|webp)'
            r'(?:\\?[^"\'\s<>]*)?',
            r'["\'](?:imageUrl|imageURL|photoUrl|photoURL|url)["\']'
            r'\s*:\s*["\']([^"\']+)["\']',
        )

        for pattern in url_patterns:
            for match in re.findall(
                pattern,
                html,
                flags=re.IGNORECASE,
            ):
                value = (
                    match
                    if isinstance(match, str)
                    else match[0]
                )

                value = (
                    value.replace("\\/", "/")
                    .replace("\\u0026", "&")
                )

                candidates.append(
                    urljoin(property_url, value)
                )

        normalized: list[str] = []
        seen: set[str] = set()

        for candidate in candidates:
            url = self._normalize_image_url(candidate)

            if not url:
                continue

            if url in seen:
                continue

            if not self._looks_like_property_image(url):
                continue

            seen.add(url)
            normalized.append(url)

            if len(normalized) >= self.MAX_IMAGES_PER_PROPERTY:
                break

        return normalized

    def _download_property_images(
        self,
        property_data: dict,
        image_urls: list[str],
    ) -> list[str]:
        if not image_urls:
            return []

        external_id = str(
            property_data.get("external_id", "")
        ).strip()

        property_url = str(
            property_data.get("url", "")
        ).strip()

        folder_name = (
            self._safe_folder_name(external_id)
            if external_id
            else hashlib.sha1(
                property_url.encode("utf-8")
            ).hexdigest()[:16]
        )

        target_dir = app_paths.property_images_dir() / folder_name
        target_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        downloaded_paths: list[str] = []

        for index, image_url in enumerate(
            image_urls,
            start=1,
        ):
            try:
                extension = self._guess_extension(
                    image_url
                )
                target_path = (
                    target_dir
                    / f"{index:02d}{extension}"
                )

                if (
                    target_path.exists()
                    and target_path.stat().st_size > 5_000
                ):
                    downloaded_paths.append(
                        str(target_path.resolve())
                    )
                    continue

                response = self._get_session().get(
                    image_url,
                    timeout=30,
                    stream=True,
                    headers={
                        "Referer": property_url,
                    },
                )
                response.raise_for_status()

                content_type = str(
                    response.headers.get(
                        "Content-Type",
                        "",
                    )
                ).lower()

                if "image" not in content_type:
                    continue

                content = response.content

                # 過小通常是 icon、logo 或追蹤圖。
                if len(content) < 5_000:
                    continue

                target_path.write_bytes(content)
                downloaded_paths.append(
                    str(target_path.resolve())
                )

            except Exception:
                continue

        return downloaded_paths

    @staticmethod
    def _normalize_image_url(url: str) -> str:
        url = (url or "").strip()

        if not url:
            return ""

        url = (
            url.replace("\\/", "/")
            .replace("&amp;", "&")
        )

        if url.startswith("//"):
            url = "https:" + url

        if not url.startswith(("http://", "https://")):
            return ""

        return url

    @staticmethod
    def _looks_like_property_image(url: str) -> bool:
        lowered = url.lower()

        excluded_words = (
            "logo",
            "icon",
            "avatar",
            "profile",
            "sprite",
            "favicon",
            "loading",
            "blank",
            "transparent",
            "qrcode",
            "qr-code",
            "member",
            "agent",
            "broker",
            "facebook",
            "line",
        )

        if any(word in lowered for word in excluded_words):
            return False

        parsed = urlparse(url)
        path = parsed.path.lower()

        image_extension = re.search(
            r"\.(jpg|jpeg|png|webp)$",
            path,
            flags=re.IGNORECASE,
        )

        image_hint = any(
            word in lowered
            for word in (
                "house",
                "photo",
                "image",
                "object",
                "estate",
                "property",
                "sale",
                "buy",
            )
        )

        return bool(image_extension or image_hint)

    @staticmethod
    def _guess_extension(url: str) -> str:
        path = urlparse(url).path.lower()

        for extension in (
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
        ):
            if path.endswith(extension):
                return extension

        return ".jpg"

    @staticmethod
    def _safe_folder_name(value: str) -> str:
        cleaned = re.sub(
            r"[^A-Za-z0-9_-]+",
            "_",
            value.strip(),
        )
        return cleaned or "property"

    @staticmethod
    def _is_property_url(url: str) -> bool:
        lowered = url.lower()

        if "buy.yungching.com.tw" not in lowered:
            return False

        excluded = (
            "/list/",
            "/region/",
            "/community/",
            "/school/",
            "/map/",
        )

        return not any(
            item in lowered
            for item in excluded
        )

    def _find_property_container_text(self, link) -> str:
        current = link

        for _ in range(7):
            current = getattr(
                current,
                "parent",
                None,
            )

            if current is None:
                break

            text = self._clean_text(
                current.get_text(
                    " ",
                    strip=True,
                )
            )

            if (
                40 <= len(text) <= 2500
                and re.search(
                    r"[A-Z]{2}\d{7}",
                    text,
                )
                and (
                    "萬" in text
                    or "坪" in text
                )
            ):
                return text

        return self._clean_text(
            link.parent.get_text(
                " ",
                strip=True,
            )
        )

    def _extract_title_and_address(
        self,
        link_text: str,
        container_text: str,
    ) -> tuple[str, str]:
        text = link_text or container_text

        city_pattern = re.compile(
            r"(臺北市|台北市|新北市|桃園市|新竹市|新竹縣|"
            r"苗栗縣|臺中市|台中市|彰化縣|南投縣|"
            r"嘉義市|嘉義縣|臺南市|台南市|高雄市|屏東縣)"
        )

        match = city_pattern.search(text)

        if match:
            title = text[: match.start()].strip(
                " -｜│　"
            )
            address_part = text[
                match.start():
            ]

            address_end_patterns = [
                r"[A-Z]{2}\d{7}",
                r"\d+(?:\.\d+)?年",
                r"\d[\d,]*\s*萬",
            ]

            end_position = len(address_part)

            for pattern in address_end_patterns:
                end_match = re.search(
                    pattern,
                    address_part,
                )

                if end_match:
                    end_position = min(
                        end_position,
                        end_match.start(),
                    )

            address = address_part[
                :end_position
            ].strip(" -｜│　")

            return (
                self._shorten(title, 100),
                self._shorten(address, 150),
            )

        external_match = re.search(
            r"[A-Z]{2}\d{7}",
            text,
        )

        if external_match:
            title = text[
                :external_match.start()
            ].strip(" -｜│　")
        else:
            title = text[:100].strip(
                " -｜│　"
            )

        return self._shorten(title, 100), ""

    @staticmethod
    def _extract_external_id(
        text: str,
        url: str,
    ) -> str:
        match = re.search(
            r"\b[A-Z]{2}\d{7}\b",
            text,
        )

        if match:
            return match.group(0)

        url_match = re.search(
            r"\b[A-Z]{2}\d{7}\b",
            url.upper(),
        )

        return (
            url_match.group(0)
            if url_match
            else ""
        )

    @staticmethod
    def _extract_price(text: str) -> str:
        """
        從列表文字抓目前總價。

        支援：
        - 1,580 萬
        - 1 億 2,800 萬
        - 原價 999 萬、目前 990 萬（取最後一個）
        並排除「萬／坪」單價。
        """
        normalized = re.sub(
            r"\s+",
            " ",
            text or "",
        ).strip()

        candidates: list[tuple[int, str]] = []

        # 億 + 萬格式。
        billion_pattern = re.compile(
            r"(\d+(?:\.\d+)?)\s*億"
            r"(?:\s*([\d,]+(?:\.\d+)?)\s*萬)?"
        )

        occupied_ranges: list[tuple[int, int]] = []

        for match in billion_pattern.finditer(normalized):
            billion = match.group(1)
            ten_thousand = match.group(2)

            value = f"{billion}億"

            if ten_thousand:
                value += f"{ten_thousand}萬"

            candidates.append(
                (
                    match.start(),
                    value,
                )
            )
            occupied_ranges.append(
                (
                    match.start(),
                    match.end(),
                )
            )

        # 一般「萬」格式，排除每坪單價。
        ten_thousand_pattern = re.compile(
            r"([\d,]+(?:\.\d+)?)\s*萬"
            r"(?!\s*(?:/|／)\s*坪)"
        )

        for match in ten_thousand_pattern.finditer(
            normalized
        ):
            if any(
                start <= match.start() < end
                for start, end in occupied_ranges
            ):
                continue

            candidates.append(
                (
                    match.start(),
                    f"{match.group(1)}萬",
                )
            )

        if not candidates:
            return ""

        # 列表若同時有原價與新價，後面的通常是目前售價。
        candidates.sort(
            key=lambda item: item[0]
        )

        return candidates[-1][1]

    @staticmethod
    def _extract_layout(text: str) -> str:
        patterns = (
            r"(\d+\s*\+\s*\d+\s*房"
            r"(?:\s*\d+\s*廳)?"
            r"(?:\s*\d+\s*衛)?)",
            r"(\d+\s*房(?:\(室\))?"
            r"(?:\s*\d+\s*廳)?"
            r"(?:\s*\d+\s*衛)?)",
            r"(開放(?:式)?格局)",
            r"(套房)",
        )

        for pattern in patterns:
            match = re.search(
                pattern,
                text,
            )

            if match:
                return (
                    match.group(1)
                    .replace(" ", "")
                    .replace("(室)", "")
                )

        return ""

    @staticmethod
    def _extract_size(text: str) -> str:
        patterns = (
            r"(?:建物總坪數|建物坪數|權狀坪數|建物)"
            r"\s*[:：]?\s*([\d.]+)\s*坪",
            r"總建坪\s*[:：]?\s*([\d.]+)\s*坪",
            r"主\+陽\s*[:：]?\s*([\d.]+)\s*坪",
            r"主建物\s*[:：]?\s*([\d.]+)\s*坪",
            r"主\s*[:：]?\s*([\d.]+)\s*坪",
        )

        for pattern in patterns:
            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if match:
                return f"{match.group(1)}坪"

        return ""

    @staticmethod
    def _clean_text(value: str) -> str:
        return re.sub(
            r"\s+",
            " ",
            value or "",
        ).strip()

    @staticmethod
    def _shorten(
        value: str,
        maximum: int,
    ) -> str:
        value = value.strip()

        return (
            value
            if len(value) <= maximum
            else value[:maximum].strip()
        )