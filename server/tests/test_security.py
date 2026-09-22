"""License Server security.py 的回歸測試（2026-09-22 Phase 2，規格第
5、14、28 節）：License Key 產生/雜湊、密碼雜湊、session token。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from server.app.security import (  # noqa: E402
    generate_license_key,
    generate_session_token,
    hash_device_fingerprint,
    hash_license_key,
    hash_password,
    hash_session_token,
    license_key_last4,
    verify_password,
)


def test_generated_license_key_matches_format() -> None:
    key = generate_license_key()
    assert key.startswith("HF-PRO-")
    groups = key.split("-")
    assert len(groups) == 6  # HF, PRO, 4 groups of 4
    for group in groups[2:]:
        assert len(group) == 4


def test_generated_license_keys_are_unique() -> None:
    keys = {generate_license_key() for _ in range(200)}
    assert len(keys) == 200  # 極低碰撞機率；一旦重複代表 random 來源有問題


def test_license_key_excludes_ambiguous_characters() -> None:
    ambiguous = set("0O1IL")
    for _ in range(50):
        key = generate_license_key()
        body = key.replace("-", "").replace("HF", "").replace("PRO", "")
        assert not (set(body) & ambiguous), key


def test_license_key_hash_is_deterministic_and_case_insensitive() -> None:
    key = "HF-PRO-ABCD-EFGH-IJKL-MNOP"
    assert hash_license_key(key) == hash_license_key(key.lower())
    assert hash_license_key(key) == hash_license_key(f" {key} ")


def test_license_key_hash_never_contains_plaintext() -> None:
    key = generate_license_key()
    digest = hash_license_key(key)
    assert key not in digest
    assert len(digest) == 64  # sha256 hex


def test_license_key_last4() -> None:
    assert license_key_last4("HF-PRO-ABCD-EFGH-IJKL-WXYZ") == "WXYZ"


def test_password_hash_roundtrip() -> None:
    stored = hash_password("correct horse battery staple 42")
    assert verify_password("correct horse battery staple 42", stored) is True
    assert verify_password("wrong password entirely", stored) is False


def test_password_hash_never_stores_plaintext() -> None:
    password = "super-secret-admin-password-123"
    stored = hash_password(password)
    assert password not in stored


def test_password_hash_uses_random_salt() -> None:
    hash_a = hash_password("same-password-both-times")
    hash_b = hash_password("same-password-both-times")
    assert hash_a != hash_b  # 不同 salt，結果不應該一樣


def test_session_token_hash_roundtrip() -> None:
    token = generate_session_token()
    assert len(token) >= 32
    digest = hash_session_token(token)
    assert digest == hash_session_token(token)
    assert token not in digest


def test_device_fingerprint_hash_is_deterministic() -> None:
    fp = "some-opaque-fingerprint-value"
    assert hash_device_fingerprint(fp) == hash_device_fingerprint(fp)
    assert hash_device_fingerprint(fp) != fp


if __name__ == "__main__":
    failures = 0
    tests = [(name, obj) for name, obj in list(globals().items()) if name.startswith("test_")]
    for name, test in tests:
        try:
            test()
            print(f"PASS: {name}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL: {name}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)
