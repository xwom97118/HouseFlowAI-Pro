"""HouseFlow Updater 架構骨架的正式回歸測試（2026-09-21 產品化 Phase
1，規格第 30 節；規格第 22 節：check → download → verify → backup →
apply → rollback 狀態機）。

這裡完全不下載、不安裝、不重啟任何東西——只驗證版本比較邏輯、狀態機
的呼叫順序，以及任一步驟失敗時會正確走到 rollback。
"""
from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path

from app.services.updater_service import (
    MockUpdateProvider,
    UpdateMetadata,
    UpdateProgressEvent,
    UpdateStage,
    UpdateSteps,
    check_for_update,
    is_newer_version,
    perform_update,
)


def _make_fake_data_dir() -> Path:
    root = Path(tempfile.mkdtemp(prefix="hf_updater_src_"))
    (root / "houseflow.db").write_bytes(b"fake-sqlite-bytes")
    return root


def test_is_newer_version_basic_cases() -> None:
    assert is_newer_version("3.5.0", "3.4.0") is True
    assert is_newer_version("3.4.0", "3.4.0") is False
    assert is_newer_version("3.3.9", "3.4.0") is False
    assert is_newer_version("4.0.0", "3.4.0") is True


def test_is_newer_version_handles_uneven_segment_counts() -> None:
    assert is_newer_version("3.4.0.1", "3.4.0") is True
    assert is_newer_version("3.4", "3.4.0") is False


def test_check_for_update_reports_available() -> None:
    metadata = UpdateMetadata(
        latest_version="3.5.0",
        minimum_supported_version="3.0.0",
        release_notes="修正若干問題",
        download_url="https://example.invalid/update.zip",
        sha256="deadbeef",
        published_at="2026-09-21T00:00:00",
    )
    result = check_for_update("3.4.0", MockUpdateProvider(metadata))
    assert result.update_available is True
    assert result.below_minimum_supported is False


def test_check_for_update_reports_no_update_when_current() -> None:
    metadata = UpdateMetadata(
        latest_version="3.4.0",
        minimum_supported_version="3.0.0",
        release_notes="",
        download_url="",
        sha256="",
        published_at="",
    )
    result = check_for_update("3.4.0", MockUpdateProvider(metadata))
    assert result.update_available is False


def test_check_for_update_flags_below_minimum_supported() -> None:
    metadata = UpdateMetadata(
        latest_version="4.0.0",
        minimum_supported_version="3.4.0",
        release_notes="",
        download_url="",
        sha256="",
        published_at="",
    )
    result = check_for_update("3.0.0", MockUpdateProvider(metadata))
    assert result.below_minimum_supported is True


def test_check_for_update_flags_mandatory() -> None:
    metadata = UpdateMetadata(
        latest_version="3.5.0",
        minimum_supported_version="3.0.0",
        release_notes="",
        download_url="",
        sha256="",
        published_at="",
        mandatory=True,
    )
    result = check_for_update("3.4.0", MockUpdateProvider(metadata))
    assert result.is_mandatory is True


class _SucceedingSteps(UpdateSteps):
    def __init__(self, expected_content: bytes) -> None:
        self._expected_content = expected_content
        self.applied = False

    def download_update(self, metadata, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self._expected_content)
        return destination

    def apply_update(self, downloaded_file, install_dir):
        self.applied = True


class _FailingApplySteps(_SucceedingSteps):
    def apply_update(self, downloaded_file, install_dir):
        raise RuntimeError("simulated install failure")


def _metadata_for(content: bytes) -> UpdateMetadata:
    return UpdateMetadata(
        latest_version="3.5.0",
        minimum_supported_version="3.0.0",
        release_notes="",
        download_url="https://example.invalid/update.zip",
        sha256=hashlib.sha256(content).hexdigest(),
        published_at="",
    )


def test_perform_update_happy_path_reaches_done_and_creates_backup() -> None:
    src = _make_fake_data_dir()
    backup_dir = Path(tempfile.mkdtemp(prefix="hf_updater_backup_"))
    download_dest = Path(tempfile.mkdtemp(prefix="hf_updater_dl_")) / "update.zip"
    install_dir = Path(tempfile.mkdtemp(prefix="hf_updater_install_"))
    try:
        content = b"fake-update-package-bytes"
        steps = _SucceedingSteps(content)
        events: list[UpdateProgressEvent] = []

        result = perform_update(
            _metadata_for(content),
            data_dir=src,
            backup_dir=backup_dir,
            steps=steps,
            download_destination=download_dest,
            install_dir=install_dir,
            on_progress=events.append,
        )

        assert result.final_stage == UpdateStage.DONE
        assert steps.applied is True
        assert result.backup_manifest is not None
        assert UpdateStage.BACKING_UP in result.stages_completed
        assert UpdateStage.APPLYING_UPDATE in result.stages_completed
        assert (backup_dir / "manifest.json").exists()
    finally:
        shutil.rmtree(src, ignore_errors=True)
        shutil.rmtree(backup_dir, ignore_errors=True)
        shutil.rmtree(download_dest.parent, ignore_errors=True)
        shutil.rmtree(install_dir, ignore_errors=True)


def test_perform_update_rejects_checksum_mismatch_before_backing_up() -> None:
    src = _make_fake_data_dir()
    backup_dir = Path(tempfile.mkdtemp(prefix="hf_updater_backup_"))
    download_dest = Path(tempfile.mkdtemp(prefix="hf_updater_dl_")) / "update.zip"
    install_dir = Path(tempfile.mkdtemp(prefix="hf_updater_install_"))
    try:
        real_content = b"real-bytes"
        steps = _SucceedingSteps(real_content)
        # metadata 記錄的是「別的」sha256，模擬下載內容被竄改/損毀
        bad_metadata = _metadata_for(b"different-bytes-than-what-gets-downloaded")

        result = perform_update(
            bad_metadata,
            data_dir=src,
            backup_dir=backup_dir,
            steps=steps,
            download_destination=download_dest,
            install_dir=install_dir,
        )

        assert result.final_stage == UpdateStage.FAILED
        assert steps.applied is False
        # 還沒有走到 backup 這一步，不應該留下 manifest
        assert not (backup_dir / "manifest.json").exists()
    finally:
        shutil.rmtree(src, ignore_errors=True)
        shutil.rmtree(backup_dir, ignore_errors=True)
        shutil.rmtree(download_dest.parent, ignore_errors=True)
        shutil.rmtree(install_dir, ignore_errors=True)


def test_perform_update_rolls_back_on_apply_failure_after_backup_exists() -> None:
    src = _make_fake_data_dir()
    backup_dir = Path(tempfile.mkdtemp(prefix="hf_updater_backup_"))
    download_dest = Path(tempfile.mkdtemp(prefix="hf_updater_dl_")) / "update.zip"
    install_dir = Path(tempfile.mkdtemp(prefix="hf_updater_install_"))
    try:
        content = b"fake-update-package-bytes"
        steps = _FailingApplySteps(content)

        result = perform_update(
            _metadata_for(content),
            data_dir=src,
            backup_dir=backup_dir,
            steps=steps,
            download_destination=download_dest,
            install_dir=install_dir,
        )

        assert result.final_stage == UpdateStage.ROLLED_BACK
        assert result.backup_manifest is not None
        # 備份已經確實建立（apply 失敗發生在 backup 之後）
        assert (backup_dir / "manifest.json").exists()
        assert result.error is not None
    finally:
        shutil.rmtree(src, ignore_errors=True)
        shutil.rmtree(backup_dir, ignore_errors=True)
        shutil.rmtree(download_dest.parent, ignore_errors=True)
        shutil.rmtree(install_dir, ignore_errors=True)


def test_default_update_steps_download_and_apply_are_not_implemented() -> None:
    """規格明確禁止這一輪做出真正會下載/安裝的 Updater——這裡驗證預設
    的 UpdateSteps（沒有被測試用子類別覆寫時）對這兩個步驟就是
    NotImplementedError，不會意外真的動手做任何事。
    """
    steps = UpdateSteps()
    try:
        steps.download_update(_metadata_for(b"x"), Path("unused"))
        raise AssertionError("expected NotImplementedError")
    except NotImplementedError:
        pass

    try:
        steps.apply_update(Path("unused"), Path("unused"))
        raise AssertionError("expected NotImplementedError")
    except NotImplementedError:
        pass


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
