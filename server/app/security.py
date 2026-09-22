"""密碼雜湊、License Key 產生／雜湊、Session Token 產生／雜湊
（2026-09-22 Phase 2，規格第 5、14 節）。

刻意只用 Python 標準函式庫（hashlib、secrets、hmac），不引入
passlib/bcrypt/PyJWT 之類的第三方套件——scrypt（PEP 458／
hashlib.scrypt，Python 3.6+ 內建）是被廣泛信任的記憶體困難 KDF，
secrets 模組是 Python 官方建議的「cryptographically secure random」
來源，避免多一個新依賴的同時仍然滿足規格「使用 cryptographically
secure random generation」「secure password hash」的要求。
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

# 排除容易混淆的字元（0/O、1/I/L），降低使用者手動輸入 License Key 時
# 抄錯的機率。
_LICENSE_KEY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_LICENSE_KEY_GROUP_COUNT = 4
_LICENSE_KEY_GROUP_LENGTH = 4


# ---------------------------------------------------------------------------
# 密碼雜湊（Admin 帳號）
# ---------------------------------------------------------------------------

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${derived.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, n_str, r_str, p_str, salt_hex, hash_hex = stored_hash.split("$")
        if scheme != "scrypt":
            return False
        n, r, p = int(n_str), int(r_str), int(p_str)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, AttributeError):
        return False

    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=len(expected))
    return hmac.compare_digest(derived, expected)


# ---------------------------------------------------------------------------
# License Key：產生、雜湊
# ---------------------------------------------------------------------------


def generate_license_key() -> str:
    """回傳一組完整、明文的 License Key，格式
    HF-PRO-XXXX-XXXX-XXXX-XXXX。呼叫端負責只在建立當下顯示一次，
    之後只存它的 hash（見 hash_license_key）。使用 secrets.choice——
    禁止流水號、timestamp 或任何可預測的 random 來源。
    """
    groups = [
        "".join(secrets.choice(_LICENSE_KEY_ALPHABET) for _ in range(_LICENSE_KEY_GROUP_LENGTH))
        for _ in range(_LICENSE_KEY_GROUP_COUNT)
    ]
    return "HF-PRO-" + "-".join(groups)


def hash_license_key(license_key: str) -> str:
    normalized = license_key.strip().upper()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def license_key_last4(license_key: str) -> str:
    normalized = license_key.strip().upper().replace("-", "")
    return normalized[-4:] if len(normalized) >= 4 else normalized


# ---------------------------------------------------------------------------
# Admin Session Token
# ---------------------------------------------------------------------------


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Device fingerprint（Desktop 傳來的值本身已經是本機隨機 UUID 的
# sha256——這裡再雜湊一次是防禦性深度，不代表 server 端持有任何可逆推
# 硬體身分的資訊）。
# ---------------------------------------------------------------------------


def hash_device_fingerprint(fingerprint: str) -> str:
    return hashlib.sha256(fingerprint.strip().encode("utf-8")).hexdigest()
