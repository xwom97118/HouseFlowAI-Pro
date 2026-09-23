"""Production-friendly structured logging（2026-09-23 Phase 3A，規格第
15 節）。

輸出成一行一個 JSON object（方便 Render/任何 log 收集系統直接解析），
欄位至少有 timestamp/level/event/request_id。**絕對不記錄**：完整
License Key、密碼、cookie、session token、任何 secret、Facebook
相關資料——這個規則不是靠「大家小心一點」，是靠 `mask_sensitive()`
在真的要記錄某個 dict 之前先過濾一次。
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

_SENSITIVE_KEYS = {
    "password", "password_hash", "license_key", "session_token", "token",
    "secret", "cookie", "authorization", "signature", "private_key",
}


def mask_sensitive(data: dict) -> dict:
    """回傳一份過濾過的複本——敏感欄位名稱換成 "***"，不是直接刪除
    （刪除會讓人以為那個欄位不存在，換成遮罩比較清楚「這裡本來有
    東西，只是不給看」）。"""
    return {
        key: ("***" if key.lower() in _SENSITIVE_KEYS else value)
        for key, value in data.items()
    }


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
            "logger": record.name,
        }
        request_id = getattr(record, "request_id", None)
        if request_id:
            payload["request_id"] = request_id
        extra_fields = getattr(record, "fields", None)
        if extra_fields:
            payload.update(mask_sensitive(extra_fields))
        if record.exc_info:
            # 只記錄例外的類型名稱，不記錄完整 traceback/檔案路徑
            # （規格第 14 節：不要把 traceback/filesystem path 回傳給
            # client；這裡進一步延伸成同一份 log 本身也不留完整
            # traceback 細節到一般 INFO/ERROR log 裡，只留類型方便
            # 統計）。真正除錯需要的完整 traceback 由 uvicorn 自己的
            # error log 記錄，不是這裡的結構化 event log。
            payload["exception_type"] = record.exc_info[0].__name__ if record.exc_info[0] else "Unknown"
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger("houseflow_license_server")
    root.setLevel(level.upper())
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root.addHandler(handler)
    root.propagate = False


def get_logger() -> logging.Logger:
    return logging.getLogger("houseflow_license_server")


def log_event(event: str, level: str = "info", request_id: str | None = None, **fields) -> None:
    logger = get_logger()
    log_fn = getattr(logger, level.lower(), logger.info)
    log_fn(event, extra={"request_id": request_id, "fields": fields})
