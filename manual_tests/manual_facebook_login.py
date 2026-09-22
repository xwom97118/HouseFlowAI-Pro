"""手動、互動式的 Facebook 登入工具（原本檔名：test_facebook_login.py）。

這「不是」自動化測試，不會被任何 regression suite、pytest test
discovery 或 CI 呼叫——這是給人在需要重新登入 production Facebook
帳號時，手動在終端機執行一次的小工具，會打開一個真正的、指向
production Facebook 瀏覽器 profile 的瀏覽器視窗。

安全機制：
1. 這個檔案刻意放在 manual_tests/、檔名刻意不是 test_*.py，不會被
   `ls test_*.py`／pytest discovery／glob test sweep 掃到。
2. 執行期還有一層 require_live_facebook_confirmation() 檢查——沒有
   明確設定 HOUSEFLOW_ALLOW_LIVE_FACEBOOK=1，一律在做任何 Facebook
   相關操作之前直接拒絕執行（見 _live_guard.py）。

手動執行方式（在 repo 根目錄）：

    HOUSEFLOW_ALLOW_LIVE_FACEBOOK=1 python manual_tests/manual_facebook_login.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _live_guard import require_live_facebook_confirmation  # noqa: E402

if __name__ == "__main__":
    require_live_facebook_confirmation("manual_facebook_login.py")

    from app.services.facebook_service import FacebookService

    FacebookService().open_login()
