"""Connector registry：source_type -> connector 實例。未來新增品牌
（信義、住商、台灣房屋…）只需要在這裡多註冊一行，HouseFlow 核心程式碼
（sync_runner.py／database.py／UI）不需要對任何特定品牌名稱做判斷。

這一輪只註冊 YungchingConnector——其他品牌的 scraper 明確不在這一輪
範圍內（見使用者指示第 31 節：「不要實作其他品牌 scraper」）。
"""
from __future__ import annotations

from app.services.property_sources.base import PropertySourceConnector
from app.services.property_sources.yungching_connector import YungchingConnector


class PropertySourceRegistry:
    def __init__(self) -> None:
        self._connectors: dict[str, PropertySourceConnector] = {}

    def register(self, connector: PropertySourceConnector) -> None:
        source_type = connector.get_source_identity().source_type
        self._connectors[source_type] = connector

    def get(self, source_type: str) -> PropertySourceConnector | None:
        return self._connectors.get(source_type)

    def list_identities(self) -> list[dict[str, str]]:
        return [
            {
                "source_type": c.get_source_identity().source_type,
                "source_brand": c.get_source_identity().source_brand,
                "display_name": c.get_source_identity().display_name,
            }
            for c in self._connectors.values()
        ]


def default_registry() -> PropertySourceRegistry:
    registry = PropertySourceRegistry()
    registry.register(YungchingConnector())
    return registry
