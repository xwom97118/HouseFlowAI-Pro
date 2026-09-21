"""包裝現有、已經在 production 驗證穩定的 YungchingSyncService，讓它
符合 PropertySourceConnector 介面——不重寫任何抓取／解析邏輯，純粹
delegate。見 base.py 檔案開頭的說明。
"""
from __future__ import annotations

import re
import threading
from typing import Any, Callable

from app.services.property_sources.base import (
    ConnectorValidationError,
    NormalizedProperty,
    PropertySourceConnector,
    PropertySourceIdentity,
)
from app.services.sync_service import SyncResult, YungchingSyncService

# 跟 app/widgets/property_picker.py 的 PropertyPicker._extract_region()
# 是同一份規則——那裡是給 UI 篩選用的，這裡是給 normalize_property()
# 拆 city/district 用的，兩邊職責不同所以各自保留一份，不讓 service
# 層反過來 import widget 層。
_DISTRICT_PATTERN = re.compile(
    r"(桃園區|中壢區|平鎮區|龍潭區|楊梅區|"
    r"八德區|龜山區|蘆竹區|大溪區|大園區|"
    r"觀音區|新屋區|復興區|竹北市|新竹市|"
    r"竹東鎮|關西鎮)"
)


class YungchingConnector(PropertySourceConnector):
    """永慶／台慶店頭列表頁。"""

    def __init__(self, service_factory: Callable[[], YungchingSyncService] = YungchingSyncService) -> None:
        self._service_factory = service_factory

    def get_source_identity(self) -> PropertySourceIdentity:
        return PropertySourceIdentity(
            source_type="yungching_store",
            source_brand="yungching",
            display_name="永慶／台慶店頭",
            homepage_url="https://www.yungching.com.tw/",
            requires_authentication=False,
        )

    def validate_source(self, source_url: str) -> tuple[bool, str]:
        url = source_url.strip()
        if not url:
            return False, "尚未輸入店頭列表頁網址。"
        if not url.startswith(("http://", "https://")):
            return False, "網址格式不正確，必須以 http:// 或 https:// 開頭。"
        return True, ""

    def fetch_properties(
        self,
        source_url: str,
        progress_callback: Callable[[dict], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> SyncResult:
        ok, reason = self.validate_source(source_url)
        if not ok:
            raise ConnectorValidationError(reason)

        service = self._service_factory()
        return service.fetch(source_url, progress_callback=progress_callback, cancel_event=cancel_event)

    def parse_property(self, raw: dict[str, Any]) -> dict[str, Any]:
        # YungchingSyncService.fetch() 回傳的 result.properties 裡每一筆
        # 已經是解析好的乾淨 dict（見 sync_service.py），這裡不需要再做
        # 額外解析，直接回傳即可。
        return dict(raw)

    def normalize_property(self, parsed: dict[str, Any]) -> NormalizedProperty:
        identity = self.get_source_identity()
        address = str(parsed.get("address", "") or "")
        district_match = _DISTRICT_PATTERN.search(address)

        image_paths_raw = str(parsed.get("image_paths", "") or "")
        images = [p for p in image_paths_raw.split("\n") if p.strip()]

        return NormalizedProperty(
            source_type=identity.source_type,
            source_brand=identity.source_brand,
            source_id=str(parsed.get("external_id", "") or ""),
            source_url=str(parsed.get("source_url", "") or parsed.get("url", "") or ""),
            property_number=str(parsed.get("external_id", "") or ""),
            title=str(parsed.get("title", "") or ""),
            price=str(parsed.get("price", "") or ""),
            address=address,
            city="桃園市" if district_match else "",
            district=district_match.group(1) if district_match else "",
            property_type=str(parsed.get("property_type", "") or ""),
            layout=str(parsed.get("layout", "") or ""),
            size=str(parsed.get("size", "") or ""),
            community=str(parsed.get("community", "") or ""),
            features=str(parsed.get("features", "") or ""),
            images=images,
            extra={k: v for k, v in parsed.items() if k not in {
                "external_id", "title", "price", "address", "property_type",
                "layout", "size", "community", "features", "image_paths", "url", "source_url",
            }},
        )
