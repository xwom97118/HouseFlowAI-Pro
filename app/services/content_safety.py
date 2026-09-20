from __future__ import annotations

# 這些字樣只能留在 HouseFlow 內部（Database / Automation Log / Debug
# Log / UI），絕對不能出現在真正發布到 Facebook 的公開貼文內容裡——
# 不管是正式排程、DEV 測試、QA 測試、自動刪文驗證，或任何工程用途。
#
# 2026-09-20 的教訓：先前的真人驗收測試曾經把「【HouseFlow 自動排程
# 測試】」這類文字直接寫進真正發布到 Facebook 的貼文內容，讓內部測試
# 標記外流到公開頁面。這裡建立一個發布前的硬性檢查，之後不管是工程
# 手動建立測試排程、還是任何自動化流程，都不可能再把這類字樣送到
# Facebook——檢查點在 FacebookService 本身，是所有發文路徑的必經之地。
INTERNAL_MARKER_PATTERNS = (
    "【HouseFlow 自動排程測試】",
    "HouseFlow Test",
    "Automation Test",
    "Auto Publish",
    "自動發布測試",
    "自動排程測試",
    "自動排程",
    "機器人測試",
    "BOT",
    "DEV TEST",
    "QA TEST",
    "Schedule ID",
    "Property ID",
    "Debug",
    "Test Post",
    "Delete Test",
)


class InternalMarkerDetectedError(ValueError):
    """文案裡偵測到只該留在 HouseFlow 內部的工程／測試標記，拒絕發布。"""


def find_internal_marker(content: str) -> str | None:
    """掃描文案，回傳第一個命中的內部標記關鍵字；沒有就回傳 None。
    英文關鍵字比對忽略大小寫；這不是要掃描或竄改使用者自己正常撰寫的
    文案內容本身，只是擋下這一份特定的工程/測試用字清單。
    """
    lowered = content.lower()
    for pattern in INTERNAL_MARKER_PATTERNS:
        if pattern.lower() in lowered:
            return pattern
    return None


def assert_public_content_safe(content: str) -> None:
    """發布到 Facebook 前的最後一道關卡：找到內部標記就直接拒絕，
    不會嘗試「清掉標記後繼續發布」之類的自動修正——工程/測試需求
    應該從一開始就不要把這些字放進文案，而不是讓程式事後幫忙擦掉。
    """
    marker = find_internal_marker(content)
    if marker:
        raise InternalMarkerDetectedError(
            f"貼文內容包含只能用於內部測試／除錯的標記「{marker}」，"
            "已阻止發布到 Facebook。測試狀態請只保留在 HouseFlow 的"
            "資料庫／Log／UI，不要出現在真正對外的貼文內容裡。"
        )
