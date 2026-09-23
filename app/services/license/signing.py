"""License 狀態簽章驗證（Desktop 端，2026-09-23 Phase 3A，規格第 20
節）。

只做「驗證」，不做「簽署」——Desktop 端從來不持有、也不需要持有簽章
用的私鑰（那只存在 License Server 的環境變數）。這裡的公鑰透過環境
變數 HOUSEFLOW_LICENSE_SERVER_PUBLIC_KEY 注入，沒有寫死在原始碼裡的
理由：每個環境（本機開發／正式）用的是不同的金鑰對，寫死會綁死成
只能對一組固定金鑰驗證。

沒有設定公鑰時（例如還沒對過 Phase 3B 的正式 server），
verify_license_state_signature() 回傳 False——HTTPLicenseProvider 在
這種情況下的行為由呼叫端決定（Phase 3A 預設：沒有設定公鑰時視為
「這個環境還沒啟用簽章驗證」，不強制擋下既有的 Phase 2 行為，避免
沒設定這個新環境變數的既有安裝一夜之間全部被鎖住——但這代表沒有設定
公鑰的 Desktop 完全沒有防篡改保護，正式上線前 Phase 3B 必須把這個
環境變數設成必填）。
"""
from __future__ import annotations

import base64
import os

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

_PUBLIC_KEY_ENV_VAR = "HOUSEFLOW_LICENSE_SERVER_PUBLIC_KEY"


def configured_public_key_base64() -> str:
    return os.environ.get(_PUBLIC_KEY_ENV_VAR, "").strip()


def is_signature_verification_enabled() -> bool:
    return bool(configured_public_key_base64())


def _canonical_payload(license_id: str, status: str, expires_at: str, trial_ends_at: str, server_time: str) -> bytes:
    # 必須跟 server/app/services/signing_service.py 的 canonical_payload()
    # 完全一致（欄位順序、分隔符號），否則永遠驗證不過。
    fields = [license_id or "", status or "", expires_at or "", trial_ends_at or "", server_time or ""]
    return "|".join(fields).encode("utf-8")


def verify_license_state_signature(
    license_id: str,
    status: str,
    expires_at: str,
    trial_ends_at: str,
    server_time: str,
    signature_b64: str,
) -> bool:
    """回傳 True 代表簽章有效（這份狀態確實是 License Server 簽發、
    內容沒有被竄改）。公鑰沒設定，或簽章缺失/格式錯誤/驗證失敗，一律
    回傳 False——呼叫端必須把 False 當成「不能信任這份資料」處理。
    """
    public_key_b64 = configured_public_key_base64()
    if not public_key_b64 or not signature_b64:
        return False

    try:
        public_key_bytes = base64.b64decode(public_key_b64)
        public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        payload = _canonical_payload(license_id, status, expires_at, trial_ends_at, server_time)
        signature = base64.b64decode(signature_b64)
        public_key.verify(signature, payload)
        return True
    except (InvalidSignature, ValueError):
        return False
