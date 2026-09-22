"""共用安全閘門（2026-09-22 產品化 Phase 1.1）：任何一個會碰「真正」
Facebook 瀏覽器 session（production browser profile）的手動 script，
執行前都必須呼叫 require_live_facebook_confirmation()。

背景：一次 regression sweep（`ls test_*.py` 之後逐一執行）誤執行了
manual_tests/manual_facebook_login.py（原本檔名是 test_facebook_login.py，
因為符合 `test_*.py` 命名規則而被自動 sweep 掃到），開啟了一個真正、
已登入的 production Facebook 瀏覽器視窗。雖然那次沒有造成 publish/
delete，但這種事情不能再發生第二次。

這裡的防護分兩層：
1. 檔名／目錄層級：manual_tests/ 底下的檔案一律不叫 test_*.py，
   不會被任何 glob test sweep、pytest test discovery、CI 規則掃到。
2. 執行期層級（這個檔案）：即使某個地方還是不小心呼叫到了這裡的
   script，只要沒有明確設定 HOUSEFLOW_ALLOW_LIVE_FACEBOOK=1，
   一律在「做任何 Facebook 相關的事之前」直接拒絕並結束程式，
   不會建立瀏覽器 context、不會碰 production Facebook profile。

之後如果要新增其他 manual/live Facebook script，一律放在這個目錄，
並且在做任何真正的 Facebook 操作之前，第一步就呼叫
require_live_facebook_confirmation()。
"""
from __future__ import annotations

import os
import sys

ALLOW_LIVE_FACEBOOK_ENV_VAR = "HOUSEFLOW_ALLOW_LIVE_FACEBOOK"


def is_live_facebook_allowed() -> bool:
    return os.environ.get(ALLOW_LIVE_FACEBOOK_ENV_VAR, "").strip() == "1"


def require_live_facebook_confirmation(script_name: str = "這個 script") -> None:
    """預設一律拒絕。只有明確設定環境變數 HOUSEFLOW_ALLOW_LIVE_FACEBOOK=1
    才會放行。這個檢查必須是呼叫端做任何 Facebook 相關操作前的第一步。
    """
    if is_live_facebook_allowed():
        print(
            f"[manual_tests] 已確認 {ALLOW_LIVE_FACEBOOK_ENV_VAR}=1，"
            f"允許 {script_name} 存取真正的 production Facebook 瀏覽器 session。"
        )
        return

    print(
        f"[manual_tests] 拒絕執行 {script_name}。\n\n"
        f"這是一個會開啟「真正」的 Facebook 瀏覽器 session（production browser "
        f"profile）的手動 script，不是自動化測試，預設一律拒絕執行——避免被 "
        f"pytest / test discovery / regression suite / CI / glob test sweep 誤觸。\n\n"
        f"如果你現在「確實」要手動、有意識地執行它，請先在同一個 shell 設定：\n"
        f"    {ALLOW_LIVE_FACEBOOK_ENV_VAR}=1\n"
        f"再重新執行一次這個 script。",
        file=sys.stderr,
    )
    sys.exit(1)
