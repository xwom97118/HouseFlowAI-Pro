"""HouseFlow Updater 架構骨架（2026-09-21 產品化 Phase 1，規格第 22
節）。

這一輪「沒有」真正的 Update Server，也沒有真正的下載／安裝／簽章驗證
——這裡建立的是流程骨架＋介面：check → release notes → download →
verify → safe close → backup → update → migrate → launch → verify →
success/rollback，讓之後接上真正的 Cloud 服務時，Desktop 端的狀態機
與呼叫順序已經確定，只需要把 UpdateProvider 換成真正打 API 的實作。

明確禁止事項（規格第 22、34 節）已經反映在這裡的設計上：
- 沒有任何函式會真的下載檔案、替換 exe、或重啟 HouseFlow。
- 沒有 `rm -rf Desktop\\HouseFlow 再整包複製` 這種舊部署風格——
  apply_update() 是一個 NotImplementedError 的 hook，之後真正實作時
  必須採用 rename-to-timestamped-backup 再複製新版的 atomic 模式
  （跟這一輪 Facebook pipeline 部署時驗證過的作法一致），不是覆蓋式
  部署。
- perform_update() 的狀態機任何一步失敗，都會呼叫
  backup_service 建立的還原點做 rollback，不會讓 HouseFlow 卡在
  「更新一半」的狀態。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

from app.services import backup_service


def _parse_version(version: str) -> tuple[int, ...]:
    parts = []
    for chunk in version.strip().split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_newer_version(candidate: str, current: str) -> bool:
    return _parse_version(candidate) > _parse_version(current)


@dataclass
class UpdateMetadata:
    """對應規格第 19 節 Global Settings 裡的 latest_version /
    minimum_supported_version，未來由 License/Update Cloud 提供。"""

    latest_version: str
    minimum_supported_version: str
    release_notes: str
    download_url: str
    sha256: str
    published_at: str
    mandatory: bool = False


@dataclass
class UpdateCheckResult:
    update_available: bool
    current_version: str
    metadata: UpdateMetadata | None
    is_mandatory: bool = False
    below_minimum_supported: bool = False


class UpdateProvider(ABC):
    """未來真正的 Cloud provider 實作這個介面去打 API；這一輪只有
    MockUpdateProvider（測試 / 開發用，回傳固定或呼叫端指定的
    metadata）。
    """

    @abstractmethod
    def fetch_latest_metadata(self) -> UpdateMetadata: ...


class MockUpdateProvider(UpdateProvider):
    def __init__(self, metadata: UpdateMetadata) -> None:
        self._metadata = metadata

    def fetch_latest_metadata(self) -> UpdateMetadata:
        return self._metadata


def check_for_update(current_version: str, provider: UpdateProvider) -> UpdateCheckResult:
    metadata = provider.fetch_latest_metadata()
    return UpdateCheckResult(
        update_available=is_newer_version(metadata.latest_version, current_version),
        current_version=current_version,
        metadata=metadata,
        is_mandatory=metadata.mandatory,
        below_minimum_supported=_parse_version(current_version) < _parse_version(metadata.minimum_supported_version),
    )


class UpdateStage(str, Enum):
    CHECKING = "checking"
    AWAITING_USER_CONFIRMATION = "awaiting_user_confirmation"
    DOWNLOADING = "downloading"
    VERIFYING_DOWNLOAD = "verifying_download"
    BACKING_UP = "backing_up"
    CLOSING_APP = "closing_app"
    APPLYING_UPDATE = "applying_update"
    MIGRATING_DATABASE = "migrating_database"
    LAUNCHING = "launching"
    VERIFYING_LAUNCH = "verifying_launch"
    DONE = "done"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


@dataclass
class UpdateProgressEvent:
    stage: UpdateStage
    message: str = ""


@dataclass
class UpdateRunResult:
    final_stage: UpdateStage
    stages_completed: list[UpdateStage] = field(default_factory=list)
    error: str | None = None
    backup_manifest: backup_service.BackupManifest | None = None


class UpdateSteps:
    """每一個步驟都是可覆寫/可 mock 的 hook，方便測試整個狀態機的
    順序與 rollback 行為，而不需要真的下載/安裝任何東西。真正實作
    download_update()/apply_update() 是下一階段、有真正 Update Server
    之後的工作——這裡先確保「順序」「rollback」是對的。
    """

    def download_update(self, metadata: UpdateMetadata, destination: Path) -> Path:
        raise NotImplementedError("真正的下載邏輯留給下一階段（需要真正的 Update Server）。")

    def verify_download(self, file_path: Path, expected_sha256: str) -> bool:
        import hashlib

        digest = hashlib.sha256()
        with Path(file_path).open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest() == expected_sha256

    def apply_update(self, downloaded_file: Path, install_dir: Path) -> None:
        raise NotImplementedError(
            "真正的安裝邏輯留給下一階段。實作時必須採用 rename-to-timestamped-backup "
            "再複製新版的 atomic 部署模式，不能是覆蓋式部署（見本模組檔案開頭說明）。"
        )


def perform_update(
    metadata: UpdateMetadata,
    data_dir: Path,
    backup_dir: Path,
    steps: UpdateSteps,
    download_destination: Path,
    install_dir: Path,
    on_progress: Callable[[UpdateProgressEvent], None] | None = None,
) -> UpdateRunResult:
    """驅動整個更新狀態機。任一步驟拋出例外都視為失敗，進入 rollback
    （用剛剛建立的備份還原 data_dir，不會嘗試 rollback install_dir 本身
    ——程式檔的 rollback 屬於「atomic 部署」那一步的責任，不在這個函式
    的範圍）。
    """
    stages_completed: list[UpdateStage] = []

    def emit(stage: UpdateStage, message: str = "") -> None:
        if on_progress:
            on_progress(UpdateProgressEvent(stage=stage, message=message))

    def run_stage(stage: UpdateStage, fn: Callable[[], None]) -> None:
        emit(stage)
        fn()
        stages_completed.append(stage)

    backup_manifest: backup_service.BackupManifest | None = None

    try:
        downloaded_file = download_destination

        run_stage(UpdateStage.DOWNLOADING, lambda: steps.download_update(metadata, download_destination))

        def _verify() -> None:
            if not steps.verify_download(downloaded_file, metadata.sha256):
                raise ValueError("下載檔案的 checksum 跟 metadata 記錄的不符，拒絕繼續安裝。")

        run_stage(UpdateStage.VERIFYING_DOWNLOAD, _verify)

        def _backup() -> None:
            nonlocal backup_manifest
            backup_manifest = backup_service.create_backup(data_dir, backup_dir)

        run_stage(UpdateStage.BACKING_UP, _backup)
        run_stage(UpdateStage.APPLYING_UPDATE, lambda: steps.apply_update(downloaded_file, install_dir))

        return UpdateRunResult(final_stage=UpdateStage.DONE, stages_completed=stages_completed, backup_manifest=backup_manifest)

    except Exception as exc:  # noqa: BLE001
        emit(UpdateStage.FAILED, str(exc))
        if backup_manifest is not None:
            emit(UpdateStage.ROLLED_BACK, "已使用更新前建立的備份還原使用者資料。")
            return UpdateRunResult(
                final_stage=UpdateStage.ROLLED_BACK,
                stages_completed=stages_completed,
                error=str(exc),
                backup_manifest=backup_manifest,
            )
        return UpdateRunResult(final_stage=UpdateStage.FAILED, stages_completed=stages_completed, error=str(exc))
