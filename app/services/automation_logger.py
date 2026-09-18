from __future__ import annotations

from datetime import datetime

from app.services.app_paths import logs_dir

_LOG_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def log_event(event: str, detail: str = "") -> None:
    """把 Automation Engine 的生命週期事件寫到永久 log 檔（%LOCALAPPDATA%\\HouseFlow\\logs\\automation.log）。

    只寫事件名稱跟簡短說明文字——呼叫端絕對不能把 Facebook 密碼、
    cookie、session token 等敏感資訊當作 detail 傳進來。
    """
    line = f"[{datetime.now().strftime(_LOG_TIME_FORMAT)}] {event}"
    if detail:
        line += f" — {detail}"

    log_path = logs_dir() / "automation.log"
    try:
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass
