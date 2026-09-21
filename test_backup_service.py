"""HouseFlow Backup 架構的正式回歸測試（2026-09-21 產品化 Phase 1，
規格第 30 節；規格第 21 節：create/verify/restore backup）。

全程只對 tempfile 建立的暫存目錄操作，不會碰觸任何真正的
%LOCALAPPDATA%\\HouseFlow\\ 或 production 資料。
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from app.services.backup_service import create_backup, restore_backup, verify_backup


def _make_fake_data_dir() -> Path:
    root = Path(tempfile.mkdtemp(prefix="hf_backup_src_"))
    (root / "houseflow.db").write_bytes(b"fake-sqlite-bytes")
    (root / "property_images").mkdir()
    (root / "property_images" / "a.jpg").write_bytes(b"fake-jpg-bytes-1")
    (root / "property_images" / "b.jpg").write_bytes(b"fake-jpg-bytes-2")
    (root / "settings").mkdir()
    (root / "settings" / "prefs.json").write_text('{"k": "v"}', encoding="utf-8")
    # 這個資料夾必須「不」出現在備份裡
    (root / "facebook_browser_profile").mkdir()
    (root / "facebook_browser_profile" / "Cookies").write_bytes(b"super-secret-session-data")
    return root


def _cleanup(*paths: Path) -> None:
    for p in paths:
        shutil.rmtree(p, ignore_errors=True)


def test_create_backup_includes_expected_items() -> None:
    src = _make_fake_data_dir()
    backup_dir = Path(tempfile.mkdtemp(prefix="hf_backup_dst_"))
    try:
        manifest = create_backup(src, backup_dir)
        assert "houseflow.db" in manifest.included_items
        assert "property_images" in manifest.included_items
        assert "settings" in manifest.included_items
        assert manifest.file_count == 4  # houseflow.db + a.jpg + b.jpg + prefs.json
    finally:
        _cleanup(src, backup_dir)


def test_create_backup_never_includes_facebook_session() -> None:
    src = _make_fake_data_dir()
    backup_dir = Path(tempfile.mkdtemp(prefix="hf_backup_dst_"))
    try:
        manifest = create_backup(src, backup_dir)
        assert "facebook_browser_profile" not in manifest.included_items
        assert "facebook_browser_profile" in manifest.excluded_items

        payload_dir = backup_dir / "payload"
        assert not (payload_dir / "facebook_browser_profile").exists()
        for path in payload_dir.rglob("*"):
            assert "Cookies" not in path.name
    finally:
        _cleanup(src, backup_dir)


def test_manifest_is_written_to_disk_and_reloadable() -> None:
    src = _make_fake_data_dir()
    backup_dir = Path(tempfile.mkdtemp(prefix="hf_backup_dst_"))
    try:
        manifest = create_backup(src, backup_dir)
        manifest_path = backup_dir / "manifest.json"
        assert manifest_path.exists()

        from app.services.backup_service import BackupManifest

        reloaded = BackupManifest.from_json(manifest_path.read_text(encoding="utf-8"))
        assert reloaded.backup_id == manifest.backup_id
        assert reloaded.checksums == manifest.checksums
    finally:
        _cleanup(src, backup_dir)


def test_verify_backup_passes_on_untouched_backup() -> None:
    src = _make_fake_data_dir()
    backup_dir = Path(tempfile.mkdtemp(prefix="hf_backup_dst_"))
    try:
        create_backup(src, backup_dir)
        result = verify_backup(backup_dir)
        assert result.ok is True
        assert result.missing_files == []
        assert result.checksum_mismatches == []
    finally:
        _cleanup(src, backup_dir)


def test_verify_backup_detects_corrupted_file() -> None:
    src = _make_fake_data_dir()
    backup_dir = Path(tempfile.mkdtemp(prefix="hf_backup_dst_"))
    try:
        create_backup(src, backup_dir)
        db_file = backup_dir / "payload" / "houseflow.db"
        db_file.write_bytes(b"corrupted-bytes")

        result = verify_backup(backup_dir)
        assert result.ok is False
        assert "houseflow.db" in result.checksum_mismatches
    finally:
        _cleanup(src, backup_dir)


def test_verify_backup_detects_missing_file() -> None:
    src = _make_fake_data_dir()
    backup_dir = Path(tempfile.mkdtemp(prefix="hf_backup_dst_"))
    try:
        create_backup(src, backup_dir)
        (backup_dir / "payload" / "houseflow.db").unlink()

        result = verify_backup(backup_dir)
        assert result.ok is False
        assert "houseflow.db" in result.missing_files
    finally:
        _cleanup(src, backup_dir)


def test_verify_backup_missing_manifest() -> None:
    empty_dir = Path(tempfile.mkdtemp(prefix="hf_backup_empty_"))
    try:
        result = verify_backup(empty_dir)
        assert result.ok is False
        assert "manifest.json" in result.missing_files
    finally:
        _cleanup(empty_dir)


def test_restore_backup_round_trip() -> None:
    src = _make_fake_data_dir()
    backup_dir = Path(tempfile.mkdtemp(prefix="hf_backup_dst_"))
    target = Path(tempfile.mkdtemp(prefix="hf_backup_restore_target_"))
    shutil.rmtree(target)  # restore_backup 應該自己建立這個目錄
    try:
        create_backup(src, backup_dir)
        result = restore_backup(backup_dir, target)

        assert "houseflow.db" in result.restored_items
        assert (target / "houseflow.db").read_bytes() == b"fake-sqlite-bytes"
        assert (target / "property_images" / "a.jpg").exists()
        assert (target / "settings" / "prefs.json").exists()
    finally:
        _cleanup(src, backup_dir, target)


def test_restore_backup_never_touches_facebook_profile() -> None:
    src = _make_fake_data_dir()
    backup_dir = Path(tempfile.mkdtemp(prefix="hf_backup_dst_"))
    target = Path(tempfile.mkdtemp(prefix="hf_backup_restore_target_"))
    try:
        # target 已經有一個「目前登入中」的 facebook session
        (target / "facebook_browser_profile").mkdir(parents=True, exist_ok=True)
        (target / "facebook_browser_profile" / "Cookies").write_bytes(b"currently-logged-in-session")

        create_backup(src, backup_dir)
        result = restore_backup(backup_dir, target)

        assert "facebook_browser_profile" not in result.restored_items
        # 還原後，原本登入中的 session 必須維持原樣、完全沒被動過
        assert (target / "facebook_browser_profile" / "Cookies").read_bytes() == b"currently-logged-in-session"
    finally:
        _cleanup(src, backup_dir, target)


def test_restore_backup_refuses_to_overwrite_without_explicit_flag() -> None:
    src = _make_fake_data_dir()
    backup_dir = Path(tempfile.mkdtemp(prefix="hf_backup_dst_"))
    target = Path(tempfile.mkdtemp(prefix="hf_backup_restore_target_"))
    try:
        create_backup(src, backup_dir)
        target.mkdir(parents=True, exist_ok=True)
        (target / "houseflow.db").write_bytes(b"newer-data-user-does-not-want-to-lose")

        try:
            restore_backup(backup_dir, target, overwrite=False)
            raise AssertionError("expected FileExistsError")
        except FileExistsError:
            pass

        # 確認沒有真的被覆蓋
        assert (target / "houseflow.db").read_bytes() == b"newer-data-user-does-not-want-to-lose"
    finally:
        _cleanup(src, backup_dir, target)


def test_restore_backup_refuses_corrupted_backup() -> None:
    src = _make_fake_data_dir()
    backup_dir = Path(tempfile.mkdtemp(prefix="hf_backup_dst_"))
    target = Path(tempfile.mkdtemp(prefix="hf_backup_restore_target_"))
    try:
        create_backup(src, backup_dir)
        (backup_dir / "payload" / "houseflow.db").write_bytes(b"corrupted")

        try:
            restore_backup(backup_dir, target, overwrite=True)
            raise AssertionError("expected ValueError for corrupted backup")
        except ValueError:
            pass
    finally:
        _cleanup(src, backup_dir, target)


if __name__ == "__main__":
    import sys

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
