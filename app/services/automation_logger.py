from __future__ import annotations

from datetime import datetime

from app.services.app_paths import logs_dir

_LOG_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

# 簡單的大小上限 rotation：超過這個大小就把目前檔案搬成 .1（只留一份
# 備份，不是完整的多代 rotating log），避免無限成長。2026-09-19 的事故
# 之後日誌變得更重要，這裡順便補上原本缺的上限保護。
_MAX_LOG_BYTES = 5 * 1024 * 1024


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
        if log_path.exists() and log_path.stat().st_size > _MAX_LOG_BYTES:
            backup_path = log_path.with_suffix(".log.1")
            backup_path.unlink(missing_ok=True)
            log_path.rename(backup_path)

        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def log_heartbeat(detail: str = "") -> None:
    """Automation Engine 每次真正開始跑一個 cycle 時呼叫一次（不是每個
    tick 都呼叫，避免 30 秒一筆洗版）——用來回答「到某個時間點，
    HouseFlow 到底有沒有在跑」這個診斷問題。
    """
    log_event("heartbeat", detail)
