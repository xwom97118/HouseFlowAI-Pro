from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.services.http_client import build_session, fetch_html_playwright


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROPERTY_IMAGE_ROOT = PROJECT_ROOT / "data" / "property_images"


@dataclass
class UniversalImportResult:
    property_data: dict[str, Any]
    source_name: str
    message: str


class UniversalPropertyImportService:
    """
    萬用單一物件網址匯入器。

    優先讀取：
    1. JSON-LD / schema.org
    2. Open Graph / Meta
    3. 常見房仲頁面文字
    4. 通用正規表示式備援

    支援任何公開可讀的 HTTP/HTTPS 單一物件頁；
    若網站完全由 JavaScript 動態載入或有登入/防爬限制，
    可能只能抓到部分欄位。
    """

    MAX_IMAGES = 20

    def __init__(self) -> None:
        PROPERTY_IMAGE_ROOT.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.session = self._create_session()

    def import_url(
        self,
        url: str,
        progress_callback: Callable[[dict], None] | None = None,
    ) -> UniversalImportResult:
        url = url.strip()

        if not url.startswith(("http://", "https://")):
            raise ValueError(
                "網址格式不正確，必須以 http:// 或 https:// 開頭。"
            )

        self._notify(progress_callback, "fetch", "正在讀取物件頁面…")

        html, used_playwright = self._fetch_html(url)

        self._notify(progress_callback, "parse", "正在解析物件資料…")
        property_data, source_name, found_fields = self._parse_property(
            html=html,
            url=url,
        )

        if found_fields <= 1 and not used_playwright:
            # requests 抓到的頁面資料太少，通常代表該站靠 JavaScript
            # 動態載入內容；改用 HouseFlow 隨附的 Chromium 重新渲染一次。
            self._notify(progress_callback, "fetch", "頁面資料不足，改用內建瀏覽器重新讀取…")
            html = fetch_html_playwright(url)
            used_playwright = True
            self._notify(progress_callback, "parse", "正在解析物件資料…")
            property_data, source_name, found_fields = self._parse_property(
                html=html,
                url=url,
            )

        if found_fields <= 1:
            raise RuntimeError(
                "網址可以開啟，但頁面可辨識的物件資料太少。"
                "該網站可能使用動態載入、登入限制或防爬機制。"
            )

        self._notify(progress_callback, "images", "正在下載照片…")
        image_paths = self._download_images(
            property_data=property_data,
            image_urls=property_data.get("image_urls", []),
        )
        property_data["image_paths"] = image_paths
        property_data["image_count"] = len(image_paths)

        self._notify(progress_callback, "done", "匯入完成")

        return UniversalImportResult(
            property_data=property_data,
            source_name=source_name,
            message=(
                f"已從「{source_name}」讀取單一物件："
                f"{property_data['title']}，"
                f"下載 {len(image_paths)} 張照片。"
                + ("（使用內建瀏覽器渲染）" if used_playwright else "")
            ),
        )

    def _fetch_html(self, url: str) -> tuple[str, bool]:
        """優先用 requests 快速抓取；連線／SSL／逾時失敗時，改用
        HouseFlow 隨附的 Chromium（browser_runtime.py）重新渲染頁面。
        回傳 (html, used_playwright)。
        """
        try:
            response = self.session.get(url, timeout=45)
            response.raise_for_status()
            response.encoding = (
                response.apparent_encoding
                or response.encoding
                or "utf-8"
            )
            return response.text, False
        except requests.exceptions.RequestException:
            return fetch_html_playwright(url), True

    @staticmethod
    def _notify(
        callback: Callable[[dict], None] | None,
        stage: str,
        message: str,
    ) -> None:
        if callback is None:
            return
        try:
            callback({"stage": stage, "message": message})
        except Exception:
            pass

    def _parse_property(
        self,
        html: str,
        url: str,
    ) -> tuple[dict[str, Any], str, int]:
        soup = BeautifulSoup(
            html,
            "lxml",
        )
        page_text = self._clean_text(
            soup.get_text(
                " ",
                strip=True,
            )
        )

        source_name = self._detect_source(url)

        json_ld_items = self._read_json_ld(soup)
        json_ld_text = self._clean_text(
            json.dumps(
                json_ld_items,
                ensure_ascii=False,
            )
        )
        combined = self._clean_text(
            f"{page_text} {json_ld_text}"
        )

        title = self._extract_title(
            soup=soup,
            json_ld_items=json_ld_items,
            page_text=page_text,
        )
        price = self._extract_price(
            soup=soup,
            json_ld_items=json_ld_items,
            text=combined,
        )
        address = self._extract_address(
            soup=soup,
            json_ld_items=json_ld_items,
            text=combined,
        )
        layout = self._extract_layout(combined)
        size = self._extract_size(combined)
        external_id = self._extract_external_id(
            url=url,
            text=combined,
        )
        property_type = self._detect_property_type(
            f"{title} {combined}"
        )
        community = self._extract_community(
            combined
        )
        features = self._extract_features(
            combined
        )
        image_urls = self._extract_images(
            soup=soup,
            json_ld_items=json_ld_items,
            base_url=url,
            html=html,
        )

        property_data: dict[str, Any] = {
            "external_id": external_id,
            "title": title or "未命名物件",
            "address": address,
            "price": price,
            "layout": layout,
            "size": size,
            "url": url,
            "status": "active",
            "source_url": url,
            "source_name": source_name,
            "property_type": property_type,
            "community": community,
            "features": features,
            "image_urls": image_urls,
        }

        found_fields = sum(
            bool(property_data.get(key))
            for key in (
                "title",
                "price",
                "address",
                "layout",
                "size",
            )
        )

        return property_data, source_name, found_fields

    def _create_session(
        self,
    ) -> requests.Session:
        # 與 sync_service（整店同步）共用同一套 certifi CA /
        # RelaxedTLSAdapter / retry 設定（見 http_client.py），
        # 解決 Python 3.14 對缺少 Subject Key Identifier 憑證鏈的
        # strict X509 檢查（例如 buy.yungching.com.tw 單一物件頁）。
        return build_session(
            pool_connections=20,
            pool_maxsize=20,
            retry_total=4,
            backoff_factor=0.8,
            extra_headers={"Connection": "keep-alive"},
        )

    @staticmethod
    def _detect_source(
        url: str,
    ) -> str:
        host = urlparse(url).netloc.lower()

        mappings = (
            (
                "永慶／台慶",
                (
                    "yungching.com.tw",
                    "shop.yungching.com.tw",
                ),
            ),
            ("信義房屋", ("sinyi.com.tw",)),
            (
                "住商不動產",
                (
                    "hbhousing.com.tw",
                    "houseweb.com.tw",
                ),
            ),
            (
                "台灣房屋",
                (
                    "twhg.com.tw",
                    "taiwanhouse.com.tw",
                ),
            ),
            (
                "中信房屋",
                (
                    "cthouse.com.tw",
                    "century21.com.tw",
                ),
            ),
            ("591", ("591.com.tw",)),
            ("樂屋網", ("rakuya.com.tw",)),
        )

        for name, domains in mappings:
            if any(
                domain in host
                for domain in domains
            ):
                return name

        return host or "其他網站"

    @staticmethod
    def _read_json_ld(
        soup: BeautifulSoup,
    ) -> list[Any]:
        items: list[Any] = []

        for script in soup.select(
            "script[type='application/ld+json']"
        ):
            raw = script.string or script.get_text(
                strip=True
            )

            if not raw:
                continue

            try:
                data = json.loads(raw)
            except Exception:
                continue

            if isinstance(data, list):
                items.extend(data)
            else:
                items.append(data)

        return items

    def _extract_title(
        self,
        *,
        soup: BeautifulSoup,
        json_ld_items: list[Any],
        page_text: str,
    ) -> str:
        for item in self._walk_json(
            json_ld_items
        ):
            if not isinstance(item, dict):
                continue

            value = item.get("name")
            item_type = str(
                item.get("@type", "")
            ).lower()

            if (
                value
                and any(
                    word in item_type
                    for word in (
                        "product",
                        "offer",
                        "residence",
                        "house",
                        "apartment",
                        "realestate",
                    )
                )
            ):
                return self._shorten(
                    self._clean_text(
                        str(value)
                    ),
                    120,
                )

        selectors = (
            "meta[property='og:title']",
            "meta[name='twitter:title']",
            "h1",
            "[class*='title'] h1",
            "[class*='title']",
        )

        for selector in selectors:
            element = soup.select_one(
                selector
            )

            if element is None:
                continue

            value = (
                element.get("content")
                if element.name == "meta"
                else element.get_text(
                    " ",
                    strip=True,
                )
            )

            value = self._clean_text(
                str(value or "")
            )

            if 3 <= len(value) <= 160:
                return self._shorten(
                    value,
                    120,
                )

        return self._shorten(
            page_text,
            120,
        )

    def _extract_price(
        self,
        *,
        soup: BeautifulSoup,
        json_ld_items: list[Any],
        text: str,
    ) -> str:
        for item in self._walk_json(
            json_ld_items
        ):
            if not isinstance(item, dict):
                continue

            price = item.get("price")
            currency = str(
                item.get("priceCurrency", "")
            ).upper()

            if price is None:
                offers = item.get("offers")

                if isinstance(offers, dict):
                    price = offers.get("price")
                    currency = str(
                        offers.get(
                            "priceCurrency",
                            currency,
                        )
                    ).upper()

            if price is not None:
                try:
                    number = float(
                        str(price).replace(",", "")
                    )
                except ValueError:
                    continue

                if currency in {
                    "TWD",
                    "NTD",
                    "NT$",
                    "",
                }:
                    # 房仲 JSON-LD 有時以元、有時以萬元表示。
                    if number >= 100_000:
                        return (
                            f"{number / 10_000:,.0f}萬"
                        )

                    return f"{number:,.0f}萬"

        meta_selectors = (
            "meta[property='product:price:amount']",
            "meta[itemprop='price']",
        )

        for selector in meta_selectors:
            element = soup.select_one(
                selector
            )

            if element is None:
                continue

            value = str(
                element.get("content", "")
            )

            try:
                number = float(
                    value.replace(",", "")
                )
            except ValueError:
                continue

            if number >= 100_000:
                number /= 10_000

            return f"{number:,.0f}萬"

        labelled_patterns = (
            r"(?:總價|售價|開價|價格)"
            r"\s*[:：]?\s*"
            r"(\d+(?:\.\d+)?)\s*億"
            r"(?:\s*([\d,]+(?:\.\d+)?)\s*萬)?",
            r"(?:總價|售價|開價|價格)"
            r"\s*[:：]?\s*"
            r"([\d,]+(?:\.\d+)?)\s*萬"
            r"(?!\s*(?:/|／)\s*坪)",
        )

        for index, pattern in enumerate(
            labelled_patterns
        ):
            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if not match:
                continue

            if index == 0:
                value = f"{match.group(1)}億"

                if match.group(2):
                    value += (
                        f"{match.group(2)}萬"
                    )

                return value

            return f"{match.group(1)}萬"

        candidates = re.findall(
            r"([\d,]+(?:\.\d+)?)\s*萬"
            r"(?!\s*(?:/|／)\s*坪)",
            text,
        )

        return (
            f"{candidates[0]}萬"
            if candidates
            else ""
        )

    def _extract_address(
        self,
        *,
        soup: BeautifulSoup,
        json_ld_items: list[Any],
        text: str,
    ) -> str:
        for item in self._walk_json(
            json_ld_items
        ):
            if not isinstance(item, dict):
                continue

            address = item.get("address")

            if isinstance(address, str):
                value = self._clean_text(
                    address
                )

                if value:
                    return self._shorten(
                        value,
                        160,
                    )

            if isinstance(address, dict):
                parts = [
                    address.get("addressRegion"),
                    address.get("addressLocality"),
                    address.get("streetAddress"),
                ]
                value = self._clean_text(
                    " ".join(
                        str(part or "")
                        for part in parts
                    )
                )

                if value:
                    return self._shorten(
                        value,
                        160,
                    )

        selectors = (
            "[itemprop='address']",
            "[class*='address']",
            "[class*='location']",
        )

        for selector in selectors:
            for element in soup.select(
                selector
            )[:10]:
                value = self._clean_text(
                    element.get_text(
                        " ",
                        strip=True,
                    )
                )

                if self._looks_like_address(
                    value
                ):
                    return self._shorten(
                        value,
                        160,
                    )

        address_pattern = re.compile(
            r"(?:臺北市|台北市|新北市|桃園市|"
            r"新竹市|新竹縣|苗栗縣|臺中市|台中市|"
            r"彰化縣|南投縣|嘉義市|嘉義縣|"
            r"臺南市|台南市|高雄市|屏東縣|宜蘭縣|"
            r"花蓮縣|臺東縣|台東縣)"
            r".{0,45}?"
            r"(?:區|鄉|鎮|市)"
            r".{0,45}?"
            r"(?:路|街|巷|弄|段|號)"
        )
        match = address_pattern.search(
            text
        )

        return (
            self._shorten(
                match.group(0),
                160,
            )
            if match
            else ""
        )

    @staticmethod
    def _extract_layout(
        text: str,
    ) -> str:
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
    def _extract_size(
        text: str,
    ) -> str:
        patterns = (
            r"(?:建物總坪數|建物坪數|權狀坪數|建坪|建物)"
            r"\s*[:：]?\s*([\d.]+)\s*坪",
            r"(?:總坪數|坪數)"
            r"\s*[:：]?\s*([\d.]+)\s*坪",
            r"主\+陽\s*[:：]?\s*([\d.]+)\s*坪",
            r"主建物\s*[:：]?\s*([\d.]+)\s*坪",
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
    def _extract_external_id(
        *,
        url: str,
        text: str,
    ) -> str:
        patterns = (
            r"\b[A-Z]{1,4}\d{5,12}\b",
            r"(?:物件編號|案件編號|案號|編號)"
            r"\s*[:：]?\s*([A-Za-z0-9_-]{5,30})",
        )

        for pattern in patterns:
            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if match:
                return (
                    match.group(1)
                    if match.lastindex
                    else match.group(0)
                ).upper()

        path_id = re.search(
            r"([A-Za-z0-9_-]{6,30})/?$",
            urlparse(url).path,
        )

        if path_id:
            return path_id.group(1).upper()

        return hashlib.sha1(
            url.encode("utf-8")
        ).hexdigest()[:16].upper()

    @staticmethod
    def _detect_property_type(
        text: str,
    ) -> str:
        mappings = (
            (
                "土地",
                (
                    "農地",
                    "建地",
                    "工業地",
                    "土地",
                    "田",
                    "旱",
                ),
            ),
            (
                "店面",
                (
                    "店面",
                    "店住",
                    "商辦",
                    "辦公",
                ),
            ),
            (
                "廠房",
                (
                    "廠房",
                    "倉庫",
                ),
            ),
            ("別墅", ("別墅",)),
            ("透天", ("透天",)),
            (
                "電梯大樓",
                (
                    "電梯大樓",
                    "大樓",
                ),
            ),
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
        text: str,
    ) -> str:
        patterns = (
            r"(?:社區名稱|社區|建案名稱)"
            r"\s*[:：]?\s*"
            r"([^\s｜|，,]{2,40})",
        )

        for pattern in patterns:
            match = re.search(
                pattern,
                text,
            )

            if match:
                return match.group(1).strip()

        return ""

    @staticmethod
    def _extract_features(
        text: str,
    ) -> list[str]:
        mappings = (
            (
                "平面車位",
                (
                    "平面車位",
                    "坡道平面",
                ),
            ),
            (
                "雙車位",
                (
                    "雙車位",
                    "兩個車位",
                    "2車位",
                ),
            ),
            (
                "景觀",
                (
                    "景觀",
                    "視野",
                    "高樓層",
                ),
            ),
            (
                "邊間",
                (
                    "邊間",
                    "三面採光",
                ),
            ),
            (
                "採光佳",
                (
                    "採光佳",
                    "採光好",
                    "明亮",
                ),
            ),
            (
                "近交流道",
                ("交流道",),
            ),
            (
                "近學區",
                (
                    "學區",
                    "國小",
                    "國中",
                ),
            ),
            (
                "近科學園區",
                (
                    "科學園區",
                    "龍科",
                    "竹科",
                ),
            ),
            (
                "庭院",
                (
                    "庭院",
                    "花園",
                ),
            ),
            (
                "電梯",
                ("電梯",),
            ),
            (
                "裝潢",
                (
                    "裝潢",
                    "全新整理",
                ),
            ),
        )

        features: list[str] = []

        for label, keywords in mappings:
            if any(
                keyword in text
                for keyword in keywords
            ):
                features.append(label)

        return features[:8]

    def _extract_images(
        self,
        *,
        soup: BeautifulSoup,
        json_ld_items: list[Any],
        base_url: str,
        html: str,
    ) -> list[str]:
        candidates: list[str] = []

        for item in self._walk_json(
            json_ld_items
        ):
            if not isinstance(item, dict):
                continue

            for key in (
                "image",
                "images",
                "photo",
                "photos",
                "contentUrl",
                "thumbnailUrl",
            ):
                value = item.get(key)

                if isinstance(value, str):
                    candidates.append(value)
                elif isinstance(value, list):
                    candidates.extend(
                        str(entry)
                        for entry in value
                        if isinstance(
                            entry,
                            str,
                        )
                    )
                elif isinstance(value, dict):
                    nested = (
                        value.get("url")
                        or value.get(
                            "contentUrl"
                        )
                    )

                    if nested:
                        candidates.append(
                            str(nested)
                        )

        for meta in soup.select(
            "meta[property='og:image'],"
            "meta[name='twitter:image'],"
            "meta[property='twitter:image']"
        ):
            value = str(
                meta.get("content", "")
            ).strip()

            if value:
                candidates.append(value)

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
                    image.get(
                        attribute,
                        "",
                    )
                ).strip()

                if value:
                    candidates.append(value)

            srcset = str(
                image.get("srcset", "")
            ).strip()

            if srcset:
                candidates.extend(
                    item.strip().split(" ")[0]
                    for item in srcset.split(",")
                    if item.strip()
                )

        for match in re.findall(
            r'https?:\\?/\\?/[^"\'\s<>]+?'
            r'\.(?:jpg|jpeg|png|webp)'
            r'(?:\\?[^"\'\s<>]*)?',
            html,
            flags=re.IGNORECASE,
        ):
            candidates.append(
                match.replace("\\/", "/")
            )

        results: list[str] = []
        seen: set[str] = set()

        for candidate in candidates:
            url = urljoin(
                base_url,
                str(candidate)
                .replace("\\/", "/")
                .replace("&amp;", "&")
                .strip(),
            )

            if not url.startswith(
                ("http://", "https://")
            ):
                continue

            if url in seen:
                continue

            if not self._looks_like_image(
                url
            ):
                continue

            seen.add(url)
            results.append(url)

            if len(results) >= self.MAX_IMAGES:
                break

        return results

    def _download_images(
        self,
        *,
        property_data: dict[str, Any],
        image_urls: list[str],
    ) -> list[str]:
        if not image_urls:
            return []

        external_id = str(
            property_data.get(
                "external_id",
                "",
            )
        ).strip()

        folder_name = self._safe_name(
            external_id
            or hashlib.sha1(
                property_data["url"].encode(
                    "utf-8"
                )
            ).hexdigest()[:16]
        )
        target_dir = (
            PROPERTY_IMAGE_ROOT
            / folder_name
        )
        target_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        downloaded: list[str] = []

        for index, image_url in enumerate(
            image_urls,
            start=1,
        ):
            extension = self._image_extension(
                image_url
            )
            target = (
                target_dir
                / f"{index:02d}{extension}"
            )

            if (
                target.exists()
                and target.stat().st_size > 5_000
            ):
                downloaded.append(
                    str(target.resolve())
                )
                continue

            try:
                response = self.session.get(
                    image_url,
                    timeout=30,
                    stream=True,
                    headers={
                        "Referer": property_data[
                            "url"
                        ],
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

                if len(content) < 5_000:
                    continue

                target.write_bytes(content)
                downloaded.append(
                    str(target.resolve())
                )

            except Exception:
                continue

        return downloaded

    @staticmethod
    def _walk_json(
        value: Any,
    ):
        if isinstance(value, dict):
            yield value

            for nested in value.values():
                yield from (
                    UniversalPropertyImportService
                    ._walk_json(nested)
                )

        elif isinstance(value, list):
            for nested in value:
                yield from (
                    UniversalPropertyImportService
                    ._walk_json(nested)
                )

    @staticmethod
    def _looks_like_address(
        value: str,
    ) -> bool:
        return bool(
            re.search(
                r"(市|縣).{0,30}(區|鄉|鎮|市)"
                r".{0,40}(路|街|段|巷|弄|號)",
                value,
            )
        )

    @staticmethod
    def _looks_like_image(
        url: str,
    ) -> bool:
        lowered = url.lower()

        excluded = (
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

        if any(
            word in lowered
            for word in excluded
        ):
            return False

        return bool(
            re.search(
                r"\.(jpg|jpeg|png|webp)"
                r"(?:\?|$)",
                lowered,
            )
            or any(
                hint in lowered
                for hint in (
                    "house",
                    "photo",
                    "image",
                    "object",
                    "estate",
                    "property",
                )
            )
        )

    @staticmethod
    def _image_extension(
        url: str,
    ) -> str:
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
    def _safe_name(
        value: str,
    ) -> str:
        result = re.sub(
            r"[^A-Za-z0-9_-]+",
            "_",
            value.strip(),
        )
        return result or "property"

    @staticmethod
    def _clean_text(
        value: str,
    ) -> str:
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

        if len(value) <= maximum:
            return value

        return value[:maximum].strip()