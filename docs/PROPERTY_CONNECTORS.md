# Property Source Connectors

> 說明 `PropertySourceConnector` 這個抽象層本身，以及未來要新增其他
> 品牌來源時該怎麼做。**這份文件只講架構**——本輪（2026-09-22）沒有、
> 也不會實作永慶以外的任何品牌 scraper。整體架構脈絡見
> [ARCHITECTURE.md](ARCHITECTURE.md#4-property-source-connector)。

## 現況

目前唯一已實作、已在 production 使用的 connector 是
`app/services/property_sources/yungching_connector.py` 的
`YungchingConnector`——包裝既有、已驗證穩定的 `YungchingSyncService`
（`app/services/sync_service.py`），沒有重寫任何抓取/解析邏輯。

`execute_source_sync()` / `SyncRunner` / `AutomationEngine` 的實際
呼叫路徑**目前還沒有**改成透過 Connector Registry——那條路徑本身已經
是 production 正在使用、已驗證穩定的程式碼，這一輪刻意不去動它。
Connector 層目前是獨立存在、經過測試、但還沒有被正式 sync 流程呼叫的
「形狀」。

## Connector 介面

新增一個品牌，就是寫一個 `PropertySourceConnector` 子類別
（`app/services/property_sources/base.py`），實作五個方法：

| 方法 | 職責 |
|---|---|
| `get_source_identity()` | 回傳 `PropertySourceIdentity`（source_type、品牌名稱、首頁網址、是否需要登入） |
| `validate_source(source_url)` | 純格式檢查（不發網路請求），回傳 `(是否合法, 原因)` |
| `authenticate_if_needed()` | 大部分店頭列表頁不需要登入，預設 no-op；需要登入的來源才要覆寫 |
| `fetch_properties(source_url, progress_callback, cancel_event)` | 實際抓取，回傳值沿用 `SyncResult` 的形狀（`.found`/`.properties`/`.message`/`.failed_pages`/`.duration_seconds`/`.cancelled`） |
| `parse_property(raw)` | 把抓回來的原始資料整理成乾淨 dict（通常抓取階段已經做完，這裡多半是直接回傳） |
| `normalize_property(parsed)` | 轉成跨品牌統一的 `NormalizedProperty`（見下） |

`NormalizedProperty`（`base.py`）是跨來源統一的欄位形狀：
`source_type`/`source_brand`/`source_id`/`source_url`、
`title`/`price`/`address`/`city`/`district`/`property_type`、
`rooms`/`bathrooms`/`floor`/`total_floors`/`building_age`/`parking`、
`images`/`agent_name`/`brokerage`/`last_synced_at`，加上向下相容的
`layout`/`size`/`community`/`features`（目前 `properties` table 實際
使用的組合欄位）。不是每個品牌都能填出每一個欄位——填不出來就留空
字串，HouseFlow 核心不需要因為某個來源缺欄位而出錯。

## 新增一個品牌的步驟

1. 在 `app/services/property_sources/` 新增 `<brand>_connector.py`，
   繼承 `PropertySourceConnector`，實作上面五個方法。
   - 如果這個品牌需要一個全新的抓取器（沒有既有的
     `XxxSyncService` 可以包），抓取邏輯本身應該先獨立寫成一個
     service 類別（跟 `YungchingSyncService` 平行），再由 connector
     包起來——不要把 Playwright/requests/BeautifulSoup 的細節直接寫
     在 connector 裡。
2. 在 `registry.py` 的 `default_registry()` 註冊新的 connector 實例。
3. 幫新 connector 寫對應的 `test_property_connector.py` 測項（可以
   參考既有的 `YungchingConnector` 測試：格式驗證、`fetch_properties`
   delegate 行為、`normalize_property` 欄位拆解），用假的
   `service_factory` 完全不連真正的網站。
4. 如果這個品牌的物件頁面結構跟永慶差異很大（例如需要登入、需要
   分頁邏輯完全不同、地址格式完全不同），`normalize_property()` 裡的
   city/district 拆解規則要獨立寫一份，不要硬套用
   `YungchingConnector._DISTRICT_PATTERN`。
5. **不要**改動 `execute_source_sync()` / `SyncRunner` /
   `AutomationEngine` 呼叫永慶那條路徑的既有邏輯，除非是刻意的、
   之後單獨決定的「把 sync 流程整個改成走 Connector Registry」的
   工程——那是比「加一個品牌」更大的變動，需要獨立評估。

## 未來預計支援的品牌（規劃中，尚未實作）

- 永慶房屋 / 永慶不動產（目前已支援：永慶／台慶店頭列表頁）
- 永義房屋
- 有巢氏房屋
- 台慶不動產
- 信義房屋
- 住商不動產
- 台灣房屋
- 中信房屋
- 東森房屋
- 21世紀不動產
- 太平洋房屋
- 群義房屋
- 地方型房仲（各地獨立經營的中小型房仲網站）
- 公司自有網站（使用者自己公司的物件列表頁）
- 其他合法來源

每一個都會是獨立的 connector 子類別，彼此不互相依賴。加入新品牌
不需要修改 `NormalizedProperty` 的欄位定義，除非確實出現現有欄位
無法表達的資訊（那種情況下才需要擴充 `NormalizedProperty`，並且
評估是否要擴充 `properties` table 的 schema——見
[ARCHITECTURE.md](ARCHITECTURE.md#5-schema-migration) 的 migration
框架說明）。
