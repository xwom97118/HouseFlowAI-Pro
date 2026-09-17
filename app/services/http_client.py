from __future__ import annotations

import threading
from typing import Callable

import certifi
import requests
import ssl
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
}


class RelaxedTLSAdapter(HTTPAdapter):
    """保留憑證驗證，但關閉 Python 3.14 的 X509 strict 模式。

    部分房仲網站（例如永慶）的憑證鏈缺少 Subject Key Identifier，
    在 Python 3.14 預設的 OpenSSL strict X509 檢查下會被
    SSLCertVerificationError 擋下（Missing Subject Key Identifier）。
    這裡用 certifi CA 建立標準 SSLContext，只移除 VERIFY_X509_STRICT
    旗標本身，不關閉一般憑證鏈驗證，也不是 verify=False。

    這是整店同步（sync_service）已經驗證成功的作法，抽成共用元件
    讓單一物件匯入（universal_import_service）等其他呼叫端也能使用，
    避免同一個 SSL 問題以後要分開修兩套。
    """

    def __init__(self, *args, **kwargs) -> None:
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())
        strict_flag = getattr(ssl, "VERIFY_X509_STRICT", 0)
        if strict_flag:
            self.ssl_context.verify_flags &= ~strict_flag
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs["ssl_context"] = self.ssl_context
        return super().init_poolmanager(
            connections,
            maxsize,
            block=block,
            **pool_kwargs,
        )

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        proxy_kwargs["ssl_context"] = self.ssl_context
        return super().proxy_manager_for(proxy, **proxy_kwargs)


def build_session(
    *,
    pool_connections: int = 20,
    pool_maxsize: int = 20,
    retry_total: int = 4,
    backoff_factor: float = 0.7,
    extra_headers: dict[str, str] | None = None,
) -> requests.Session:
    """建立共用設定的 requests.Session：certifi CA、放寬 X509 strict、
    重試與 connection pooling。呼叫端可依自己的併發量調整
    pool_connections / pool_maxsize / retry_total。
    """
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    if extra_headers:
        session.headers.update(extra_headers)

    retry = Retry(
        total=retry_total,
        connect=retry_total,
        read=retry_total,
        status=retry_total,
        backoff_factor=backoff_factor,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    adapter = RelaxedTLSAdapter(
        max_retries=retry,
        pool_connections=pool_connections,
        pool_maxsize=pool_maxsize,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


class ThreadLocalSessionFactory:
    """讓每個執行緒各自持有一個共用設定的 requests.Session（例如
    ThreadPoolExecutor 併發抓取時，避免跨執行緒共用同一個
    連線池造成的問題）。
    """

    def __init__(self, **session_kwargs) -> None:
        self._local = threading.local()
        self._session_kwargs = session_kwargs

    def get(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = build_session(**self._session_kwargs)
            self._local.session = session
        return session


def fetch_html(
    session: requests.Session,
    url: str,
    timeout: int = 30,
    **kwargs,
) -> str:
    response = session.get(url, timeout=timeout, **kwargs)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding or "utf-8"
    return response.text


# ---------------------------------------------------------------------------
# Playwright fallback：單一物件匯入使用的共用瀏覽器
# ---------------------------------------------------------------------------
#
# 注意：整店同步（sync_service）的 Playwright fallback 是在
# ThreadPoolExecutor 的多個執行緒中並行呼叫的，Playwright 的 sync API
# 並非執行緒安全，跨執行緒共用同一個 Browser 物件有風險，因此那邊
# 「不」改用這裡的共用瀏覽器，維持原本每次呼叫獨立啟動/關閉的作法。
# 這裡的共用瀏覽器只給「單一物件匯入」這種一次只會有一個呼叫在跑的
# 情境使用，才能安全重複使用同一個 Chromium 行程，不必每次匯入都
# 重新啟動瀏覽器。

_playwright_lock = threading.Lock()
_playwright_state: dict[str, object] = {}


def _get_shared_browser():
    from playwright.sync_api import sync_playwright

    from app.services.browser_runtime import ensure_playwright_browsers_path

    ensure_playwright_browsers_path()

    with _playwright_lock:
        browser = _playwright_state.get("browser")
        if browser is not None:
            try:
                # 確認瀏覽器行程還活著；如果先前已經被關掉就重建一個。
                if browser.is_connected():
                    return browser
            except Exception:
                pass

        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=True)
        _playwright_state["playwright"] = playwright
        _playwright_state["browser"] = browser
        return browser


def close_shared_browser() -> None:
    """關閉共用的 Playwright 瀏覽器（app 結束時可選擇呼叫）。"""
    with _playwright_lock:
        browser = _playwright_state.pop("browser", None)
        playwright = _playwright_state.pop("playwright", None)
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass


def fetch_html_playwright(
    url: str,
    timeout_ms: int = 60_000,
    wait_selector: str | None = None,
) -> str:
    """用 HouseFlow 隨附的 Chromium（見 browser_runtime.py）渲染頁面，
    取得完整 HTML。共用同一個瀏覽器行程，只在每次呼叫時開新的
    context/page，用完即關閉，避免分頁與 cookie 互相污染。
    """
    browser = _get_shared_browser()
    context = browser.new_context(
        ignore_https_errors=True,
        locale="zh-TW",
        user_agent=DEFAULT_USER_AGENT,
    )
    try:
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        if wait_selector:
            try:
                page.wait_for_selector(wait_selector, timeout=8_000)
            except Exception:
                pass
        try:
            page.wait_for_load_state("networkidle", timeout=8_000)
        except Exception:
            page.wait_for_timeout(1200)
        return page.content()
    finally:
        context.close()
