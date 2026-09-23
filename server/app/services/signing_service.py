"""License 狀態簽章（2026-09-23 Phase 3A，規格第 20 節）。

背景：Desktop 端把 server 回傳的授權狀態（status/expires_at/…）快取
在本機 SQLite 的 app_settings 表裡，離線時就是讀這份快取跑
evaluate_license()。這份快取只是普通的資料庫欄位——使用者只要有辦法
編輯自己電腦上的 SQLite 檔案（並不難），就可以手動把 expires_at 改成
未來的日期，繞過整個授權檢查，而完全不需要碰 server。

解法：server 用 Ed25519 私鑰對每一次回應的關鍵欄位簽章，Desktop 端
收到後先驗證簽章（用內建的公鑰），驗證失敗就整包不信任；連本機快取
也要存這個簽章，離線時重新驗證一次——這樣使用者篡改快取內容，
簽章就對不上，會被偵測到並要求重新連線驗證，而不是被系統誤信。

刻意選 Ed25519（`cryptography` 套件的標準實作，不是自己發明的演算法）
：非對稱簽章，私鑰只存在 server（環境變數），Desktop 端只需要、也只
應該持有公鑰——公鑰外流沒有安全疑慮（只能拿來「驗證」，不能拿來
「偽造」），私鑰外流才是問題，而私鑰從來不會出現在 Desktop 端的
程式碼或設定裡。
"""
from __future__ import annotations

import base64

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from server.app.config import get_settings

# 跟 Settings.secret_key 用同樣的「開發環境自動產生、正式環境必須明確
# 設定」精神——一次 process 內只產生一組臨時金鑰，不是每次呼叫都重
# 新產生（否則不同時間點簽的章互相驗證不過）。
_ephemeral_private_key_cache: Ed25519PrivateKey | None = None


def _load_or_generate_private_key() -> Ed25519PrivateKey:
    global _ephemeral_private_key_cache

    settings = get_settings()
    encoded = settings.license_signing_private_key_b64

    if encoded:
        pem_bytes = base64.b64decode(encoded)
        key = serialization.load_pem_private_key(pem_bytes, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise RuntimeError("HOUSEFLOW_LICENSE_SIGNING_PRIVATE_KEY 不是有效的 Ed25519 私鑰。")
        return key

    if settings.is_production:
        raise RuntimeError(
            "缺少環境變數 HOUSEFLOW_LICENSE_SIGNING_PRIVATE_KEY。正式環境必須明確設定簽章私鑰"
            "——用 server/generate_signing_keypair.py 產生一組，私鑰設成這個環境變數，"
            "公鑰交給 Desktop 端設定 HOUSEFLOW_LICENSE_SERVER_PUBLIC_KEY。"
        )

    if _ephemeral_private_key_cache is None:
        print(
            "[HouseFlow License Server] 未設定 HOUSEFLOW_LICENSE_SIGNING_PRIVATE_KEY，"
            "已自動產生一組僅供本次啟動使用的臨時簽章金鑰對（重啟後會失效，正式環境必須明確設定）。"
        )
        _ephemeral_private_key_cache = Ed25519PrivateKey.generate()
        public_b64 = public_key_base64(_ephemeral_private_key_cache)
        print(f"[HouseFlow License Server] 本次臨時公鑰（測試 Desktop 簽章驗證用）：{public_b64}")

    return _ephemeral_private_key_cache


def public_key_base64(private_key: Ed25519PrivateKey) -> str:
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(public_bytes).decode("ascii")


def canonical_payload(license_id: str, status: str, expires_at: str, trial_ends_at: str, server_time: str) -> bytes:
    """簽章涵蓋的欄位固定順序、固定分隔符號——跟 Desktop 端驗證時組
    payload 的邏輯必須完全一致（見 app/services/license/signing.py）。
    """
    fields = [license_id or "", status or "", expires_at or "", trial_ends_at or "", server_time or ""]
    return "|".join(fields).encode("utf-8")


def sign_license_state(license_id: str, status: str, expires_at: str, trial_ends_at: str, server_time: str) -> str:
    private_key = _load_or_generate_private_key()
    payload = canonical_payload(license_id, status, expires_at, trial_ends_at, server_time)
    signature = private_key.sign(payload)
    return base64.b64encode(signature).decode("ascii")


def current_public_key_base64() -> str:
    """給 /health 或 Admin 之外的診斷用途查詢目前使用中的公鑰（開發時
    方便把它貼進 Desktop 端的環境變數）。"""
    return public_key_base64(_load_or_generate_private_key())


def verify_license_state_signature(
    license_id: str, status: str, expires_at: str, trial_ends_at: str, server_time: str,
    signature_b64: str, public_key_b64: str,
) -> bool:
    """給測試／Desktop 端共用的驗證邏輯參考實作（Desktop 端有自己的
    版本，見 app/services/license/signing.py，避免 Desktop 依賴
    server 的程式碼）——這裡主要是給 server 端測試「簽出來的東西真的
    驗得過」用。
    """
    try:
        public_bytes = base64.b64decode(public_key_b64)
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        public_key = Ed25519PublicKey.from_public_bytes(public_bytes)
        payload = canonical_payload(license_id, status, expires_at, trial_ends_at, server_time)
        signature = base64.b64decode(signature_b64)
        public_key.verify(signature, payload)
        return True
    except (InvalidSignature, ValueError):
        return False
