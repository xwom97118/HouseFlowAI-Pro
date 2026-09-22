"""共用時間工具——全部統一用「語意上是 UTC 的 naive datetime」，避免
SQLite 對 timezone-aware datetime 往返不穩定的問題（見 models/license.py
檔案開頭的說明）。"""
from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
