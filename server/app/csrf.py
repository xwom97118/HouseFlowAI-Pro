"""CSRF 保護（2026-09-23 Phase 3A，規格第 9 節）：Admin UI 所有會修改
資料的 POST action 都要求一個跟目前 session 綁定的 token。

用「從 session token 用 HMAC 推導出來」的做法，不需要另外開一張表存
CSRF token、也不需要另一個 cookie——token 本身跟 session 綁定，
session 換了（重新登入）token 就跟著換，session 結束 token 就失效。
"""
from __future__ import annotations

import hmac
import hashlib

from server.app.config import get_settings


def generate_csrf_token(session_token: str) -> str:
    if not session_token:
        return ""
    secret = get_settings().secret_key
    return hmac.new(secret.encode("utf-8"), session_token.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_csrf_token(session_token: str, submitted_token: str) -> bool:
    if not session_token or not submitted_token:
        return False
    expected = generate_csrf_token(session_token)
    return hmac.compare_digest(expected, submitted_token)
