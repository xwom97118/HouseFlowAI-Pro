"""PropertySourceConnector 的正式回歸測試（2026-09-21 產品化 Phase 1，
規格第 30 節：property sync / connector tests）。

重點驗證：
1. YungchingConnector 正確 wrap 既有的 YungchingSyncService（不重爬、
   不重寫既有 parser 邏輯，只是 delegate + normalize）。
2. validate_source() 是純格式檢查，不發出真正的網路請求。
3. normalize_property() 能正確把既有 parser 產生的原始 dict 轉成跨
   來源統一的 NormalizedProperty，包含 city/district 拆解、圖片清單。
4. PropertySourceRegistry 的註冊/查詢行為正確。

完全不連真正的永慶網站、不使用 Playwright/requests，YungchingSyncService
用一個假的 service_factory 取代。
"""
from __future__ import annotations

from app.services.property_sources import (
    NormalizedProperty,
    PropertySourceRegistry,
    YungchingConnector,
    default_registry,
)
from app.services.property_sources.base import ConnectorValidationError
from app.services.sync_service import SyncResult


class _FakeYungchingService:
    def __init__(self, result: SyncResult) -> None:
        self._result = result

    def fetch(self, source_url, progress_callback=None, cancel_event=None):
        return self._result


def _sample_raw_property() -> dict:
    return {
        "external_id": "A123456789",
        "title": "龍潭區三房兩廳電梯大樓",
        "price": "888萬",
        "address": "桃園市龍潭區中正路100號",
        "property_type": "電梯大樓",
        "layout": "3房2廳2衛",
        "size": "29.31坪",
        "community": "測試社區",
        "features": "採光佳,近學區",
        "image_paths": "C:\\imgs\\1.jpg\nC:\\imgs\\2.jpg\nC:\\imgs\\3.jpg",
        "url": "https://www.yungching.com.tw/sale/A123456789",
        "agent_name": "測試業務",
    }


def test_get_source_identity() -> None:
    connector = YungchingConnector()
    identity = connector.get_source_identity()
    assert identity.source_type == "yungching_store"
    assert identity.source_brand == "yungching"
    assert identity.requires_authentication is False


def test_validate_source_rejects_empty_url() -> None:
    connector = YungchingConnector()
    ok, reason = connector.validate_source("")
    assert ok is False
    assert reason


def test_validate_source_rejects_bad_scheme() -> None:
    connector = YungchingConnector()
    ok, reason = connector.validate_source("ftp://example.com")
    assert ok is False


def test_validate_source_accepts_http_url() -> None:
    connector = YungchingConnector()
    ok, reason = connector.validate_source("https://www.yungching.com.tw/store/123")
    assert ok is True
    assert reason == ""


def test_fetch_properties_delegates_to_wrapped_service() -> None:
    fake_result = SyncResult(found=1, saved=0, properties=[_sample_raw_property()], message="ok")
    connector = YungchingConnector(service_factory=lambda: _FakeYungchingService(fake_result))

    result = connector.fetch_properties("https://www.yungching.com.tw/store/123")

    assert result is fake_result
    assert result.found == 1
    assert len(result.properties) == 1


def test_fetch_properties_rejects_invalid_url_without_calling_service() -> None:
    calls = []

    class _TrackingService:
        def fetch(self, source_url, progress_callback=None, cancel_event=None):
            calls.append(source_url)
            raise AssertionError("service should never be called for an invalid URL")

    connector = YungchingConnector(service_factory=_TrackingService)
    try:
        connector.fetch_properties("not-a-url")
        raise AssertionError("expected ConnectorValidationError")
    except ConnectorValidationError:
        pass
    assert calls == []


def test_parse_property_passes_through_unchanged() -> None:
    connector = YungchingConnector()
    raw = _sample_raw_property()
    parsed = connector.parse_property(raw)
    assert parsed == raw
    assert parsed is not raw  # 回傳的是拷貝，不是同一個物件參照


def test_normalize_property_extracts_district_and_city() -> None:
    connector = YungchingConnector()
    parsed = connector.parse_property(_sample_raw_property())
    normalized = connector.normalize_property(parsed)

    assert isinstance(normalized, NormalizedProperty)
    assert normalized.source_type == "yungching_store"
    assert normalized.district == "龍潭區"
    assert normalized.city == "桃園市"
    assert normalized.title == "龍潭區三房兩廳電梯大樓"
    assert normalized.layout == "3房2廳2衛"
    assert normalized.size == "29.31坪"


def test_normalize_property_splits_image_paths_into_list() -> None:
    connector = YungchingConnector()
    parsed = connector.parse_property(_sample_raw_property())
    normalized = connector.normalize_property(parsed)

    assert normalized.images == ["C:\\imgs\\1.jpg", "C:\\imgs\\2.jpg", "C:\\imgs\\3.jpg"]


def test_normalize_property_handles_missing_district_gracefully() -> None:
    connector = YungchingConnector()
    raw = _sample_raw_property()
    raw["address"] = "台北市信義區某路1號"  # 不在既有 _DISTRICT_PATTERN 清單裡
    parsed = connector.parse_property(raw)
    normalized = connector.normalize_property(parsed)

    assert normalized.district == ""
    assert normalized.city == ""
    assert normalized.address == "台北市信義區某路1號"  # 原始地址仍完整保留


def test_normalize_property_puts_unmapped_fields_into_extra() -> None:
    connector = YungchingConnector()
    parsed = connector.parse_property(_sample_raw_property())
    normalized = connector.normalize_property(parsed)

    assert normalized.extra.get("agent_name") == "測試業務"


def test_registry_register_and_get() -> None:
    registry = PropertySourceRegistry()
    connector = YungchingConnector()
    registry.register(connector)

    assert registry.get("yungching_store") is connector
    assert registry.get("nonexistent_brand") is None


def test_registry_list_identities() -> None:
    registry = PropertySourceRegistry()
    registry.register(YungchingConnector())
    identities = registry.list_identities()

    assert len(identities) == 1
    assert identities[0]["source_type"] == "yungching_store"


def test_default_registry_has_yungching_only() -> None:
    registry = default_registry()
    identities = registry.list_identities()
    assert len(identities) == 1
    assert identities[0]["source_type"] == "yungching_store"


if __name__ == "__main__":
    import sys

    failures = 0
    tests = [(name, obj) for name, obj in list(globals().items()) if name.startswith("test_")]
    for name, test in tests:
        try:
            test()
            print(f"PASS: {name}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL: {name}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)
