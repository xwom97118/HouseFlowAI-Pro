"""License Server URL 安全性回歸測試（2026-09-23 Phase 3A，規格第 18、
19 節）：正式網址必須是 HTTPS，只有 localhost 允許明文 HTTP，Desktop
端可以透過環境變數 HOUSEFLOW_LICENSE_SERVER_URL 設定，不寫死任何
Render 臨時網址或未來的正式 Domain。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.services.license.http_provider import (  # noqa: E402
    DEFAULT_BASE_URL,
    HTTPLicenseProvider,
    InsecureLicenseServerURLError,
    _is_https_or_localhost,
)


def _fake_settings():
    store: dict[str, str] = {}
    return store, (lambda k, d="": store.get(k, d)), (lambda k, v: store.__setitem__(k, v))


def test_https_url_is_allowed() -> None:
    assert _is_https_or_localhost("https://license.example.com") is True


def test_localhost_http_is_allowed() -> None:
    assert _is_https_or_localhost("http://127.0.0.1:8000") is True
    assert _is_https_or_localhost("http://localhost:8000") is True


def test_plain_http_non_localhost_is_rejected() -> None:
    assert _is_https_or_localhost("http://license.example.com") is False
    assert _is_https_or_localhost("http://203.0.113.5:8000") is False


def test_default_base_url_is_localhost() -> None:
    """開發預設值必須是本機——不能不小心指到任何 Render 臨時網址或
    未來的正式 Domain。"""
    assert _is_https_or_localhost(DEFAULT_BASE_URL) is True
    assert "127.0.0.1" in DEFAULT_BASE_URL or "localhost" in DEFAULT_BASE_URL


def test_provider_construction_rejects_insecure_url() -> None:
    _, get_setting, set_setting = _fake_settings()
    try:
        HTTPLicenseProvider(get_setting, set_setting, base_url="http://license.example.com")
        raise AssertionError("expected InsecureLicenseServerURLError")
    except InsecureLicenseServerURLError:
        pass


def test_provider_construction_accepts_https_url() -> None:
    _, get_setting, set_setting = _fake_settings()
    provider = HTTPLicenseProvider(get_setting, set_setting, base_url="https://license.example.com")
    assert provider is not None


def test_provider_construction_accepts_localhost_http() -> None:
    _, get_setting, set_setting = _fake_settings()
    provider = HTTPLicenseProvider(get_setting, set_setting, base_url="http://127.0.0.1:8791")
    assert provider is not None


if __name__ == "__main__":
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
