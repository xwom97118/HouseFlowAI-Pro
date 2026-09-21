"""PropertySourceConnector abstraction (2026-09-21 產品化 Phase 1，見
docs/ARCHITECTURE.md 的 Connector 章節）。

HouseFlow 目前唯一真正在用的物件來源是永慶／台慶店頭列表頁
（app/services/sync_service.py 的 YungchingSyncService，已經在正式
production 使用、抓取邏輯已驗證穩定）。這裡不是要重寫那份 parser，
而是幫「同步中心」原本假設「同步 = 永慶」的架構，補上一層品牌中立的
抽象——未來要加入永義、信義、住商、台灣房屋…等其他來源時，只需要新增
一個 Connector 子類別，不需要動到 HouseFlow 核心（database.py 的
schema、sync_runner.py 的 pipeline、AutomationEngine 的排程邏輯）。

這一輪刻意保守：
- execute_source_sync()／SyncRunner／AutomationEngine 的實際呼叫路徑
  「沒有」改成透過這裡的 Connector——那條路徑已經是 production 正在
  使用、已驗證穩定的程式碼，貿然抽換風險大於這一輪能拿到的好處。
- 這裡建立的是「形狀」：BasePropertySourceConnector 這個介面本身，
  以及一個把 YungchingSyncService 包起來、證明介面可行的
  YungchingConnector。下一階段如果要真的讓 sync_runner 改用
  Connector Registry，是刻意留給之後的決定，不在這一輪範圍內。
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class PropertySourceIdentity:
    """一個物件來源的品牌身分——source_type 是資料庫／程式邏輯用的
    穩定 key（不會因為顯示名稱改版而變動），source_brand 是給使用者看
    的品牌名稱。HouseFlow 核心（properties/sync_sources table）只認
    source_type，不應該對任何特定品牌字串做 if/else 判斷。
    """

    source_type: str
    source_brand: str
    display_name: str
    homepage_url: str = ""
    requires_authentication: bool = False


@dataclass
class NormalizedProperty:
    """跨來源統一的物件模型（HouseFlow Property）——不論物件從哪個
    品牌來源同步進來，進到 HouseFlow 核心之後都長這個樣子。

    目前 properties table 的欄位（title/address/price/layout/size/
    property_type/community/features/url/image_paths/...）對應到這裡
    的一部分；rooms/living_rooms/bathrooms/floor/total_floors/
    building_age/parking/building_area/land_area/city/district 是
    Section 8 規格要求預留、但目前的 parser 還沒有拆出結構化欄位的
    項目——這裡先留著讓 Connector 有地方填，HouseFlow 核心不需要因為
    某個來源填不出某些欄位就出錯（connector 負責 normalize，核心不需要
    知道任何網站的 HTML 細節）。

    這個 dataclass 目前「不會」寫進 production 的 properties table
    （那張表的 schema 不在這一輪變動範圍內，見
    docs/PRODUCT_V1_SPEC.md／schema migration 的說明）——它是給下一
    階段決定要不要擴充 schema 時，已經先設計好的目標形狀。
    """

    # 來源身分
    source_type: str = ""
    source_brand: str = ""
    source_id: str = ""
    source_url: str = ""

    # 基本資訊（目前 parser 已經可以填出來的）
    property_number: str = ""
    title: str = ""
    price: str = ""
    address: str = ""
    city: str = ""
    district: str = ""
    property_type: str = ""
    building_area: str = ""
    land_area: str = ""
    rooms: str = ""
    living_rooms: str = ""
    bathrooms: str = ""
    floor: str = ""
    total_floors: str = ""
    building_age: str = ""
    parking: str = ""
    description: str = ""
    images: list[str] = field(default_factory=list)
    agent_name: str = ""
    brokerage: str = ""
    last_synced_at: str = ""

    # 向下相容：目前 properties table 實際使用的組合欄位（layout/size
    # 是「3房2廳2衛」「29.31坪」這種還沒拆開的原始字串），HouseFlow
    # 核心目前直接用這兩個，rooms/bathrooms/building_area 等結構化
    # 欄位是給未來 schema 擴充時準備的。
    layout: str = ""
    size: str = ""
    community: str = ""
    features: str = ""

    extra: dict[str, Any] = field(default_factory=dict)


class PropertySourceConnector(ABC):
    """所有物件來源都要實作的介面。順序大致對應一次真正的同步流程：
    先確認網址／設定合不合法（validate_source），如果來源需要登入就先
    處理（authenticate_if_needed），抓取列表＋逐筆物件
    （fetch_properties，回傳值刻意沿用 sync_service.SyncResult 的形狀，
    細節見 YungchingConnector），最後把單筆原始資料轉成統一模型
    （parse_property + normalize_property）。
    """

    @abstractmethod
    def get_source_identity(self) -> PropertySourceIdentity:
        """回傳這個 connector 對應的品牌身分。"""

    @abstractmethod
    def validate_source(self, source_url: str) -> tuple[bool, str]:
        """檢查這個網址／設定是不是這個來源看得懂的格式。回傳
        (是否合法, 不合法時的原因)。不應該真的發出網路請求——這是
        「格式檢查」，不是「連線測試」。
        """

    def authenticate_if_needed(self) -> None:
        """大部分店頭列表頁不需要登入，預設是 no-op；需要登入的來源
        （例如未來可能需要帳密的自有網站）覆寫這個方法。
        """
        return None

    @abstractmethod
    def fetch_properties(
        self,
        source_url: str,
        progress_callback: Callable[[dict], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Any:
        """實際抓取。回傳值目前沿用 sync_service.SyncResult 的形狀
        （.found/.properties/.message/.failed_pages/.duration_seconds/
        .cancelled/.had_failures），跟 execute_source_sync() 現有的
        使用方式相容，不強迫每個 connector 重新定義一套結果格式。
        """

    @abstractmethod
    def parse_property(self, raw: dict[str, Any]) -> dict[str, Any]:
        """把來源網站的原始資料（例如 fetch_properties() 回傳的
        result.properties 裡的一筆）整理成乾淨的 dict——這一步通常
        已經由現有 parser 做完了，這裡多半是直接回傳或做欄位重新命名，
        不是重新爬一次。
        """

    @abstractmethod
    def normalize_property(self, parsed: dict[str, Any]) -> NormalizedProperty:
        """把 parse_property() 的結果轉成跨來源統一的 NormalizedProperty。
        這是「connector 負責 normalize，核心不需要知道任何網站 HTML
        細節」這句話實際落地的地方。
        """


class ConnectorValidationError(ValueError):
    """來源網址／設定格式不合法時拋出，不是網路或解析錯誤。"""
