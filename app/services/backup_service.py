"""HouseFlow Backup 架構骨架（2026-09-21 產品化 Phase 1，規格第 21
節）。

這一輪要做的是「架構」：manifest／版本化／checksum 驗證先做對，之後
真的要接 UI（「立即備份」按鈕、排程自動備份、還原精靈）時，底層邏輯
已經是可測試、可信任的。這一輪刻意不做的事：
- 不接任何 UI 進入點——沒有任何按鈕會呼叫這裡的函式，純粹是可以被
  測試呼叫的服務層。
- 不做加密——規格明確說「不要現在發明不安全的加密」，備份檔案目前是
  明文複製＋checksum 驗證完整性，不是機密性保護；之後如果要加密，
  應該用經過審查的既有函式庫，不是這一輪自己土法煉鋼。
- Facebook Browser Session（facebook_browser_profile/）預設「不」包含
  在可攜式備份裡——換電腦後使用者應該重新登入 Facebook，而不是把整個
  瀏覽器 session（包含登入 cookie）複製到備份檔案到處帶著走，那是很大
  的帳號安全風險。

備份內容（對應 app_paths.py 的資料夾配置）：
- houseflow.db（+ -wal/-shm/-journal，如果存在）
- property_images/
- settings/
不包含：facebook_browser_profile/（見上）、logs/、temp/（暫存檔，備份
沒有意義）。
"""
from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.version import APP_VERSION

MANIFEST_FILENAME = "manifest.json"
PAYLOAD_DIRNAME = "payload"

# 相對於 data_root() 的項目清單。字串結尾是 "/" 的視為目錄（整個複製），
# 其餘視為單一檔案（存在才複製，不存在就跳過——例如 -wal/-shm 只有在
# WAL 模式下才存在）。
_BACKUP_INCLUDE_ITEMS = (
    "houseflow.db",
    "houseflow.db-wal",
    "houseflow.db-shm",
    "houseflow.db-journal",
    "property_images/",
    "settings/",
)

# 明確排除，即使將來 _BACKUP_INCLUDE_ITEMS 不小心被改動也要在這裡再擋
# 一次——這條規則本身就是規格要求的一部分，值得獨立成一個檢查點。
_ALWAYS_EXCLUDED_ITEMS = ("facebook_browser_profile",)


@dataclass
class BackupManifest:
    backup_id: str
    created_at: str
    app_version: str
    source_data_dir: str
    included_items: list[str] = field(default_factory=list)
    excluded_items: list[str] = field(default_factory=list)
    file_count: int = 0
    total_size_bytes: int = 0
    checksums: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {
                "backup_id": self.backup_id,
                "created_at": self.created_at,
                "app_version": self.app_version,
                "source_data_dir": self.source_data_dir,
                "included_items": self.included_items,
                "excluded_items": self.excluded_items,
                "file_count": self.file_count,
                "total_size_bytes": self.total_size_bytes,
                "checksums": self.checksums,
            },
            ensure_ascii=False,
            indent=2,
        )

    @classmethod
    def from_json(cls, raw: str) -> "BackupManifest":
        data = json.loads(raw)
        return cls(**data)


@dataclass
class BackupVerificationResult:
    ok: bool
    missing_files: list[str] = field(default_factory=list)
    checksum_mismatches: list[str] = field(default_factory=list)
    manifest: BackupManifest | None = None


@dataclass
class RestoreResult:
    restored_items: list[str]
    skipped_excluded: list[str]


def _sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_files_under(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def create_backup(data_dir: Path, backup_dir: Path) -> BackupManifest:
    """把 data_dir（即 app_paths.data_root() 指向的使用者資料根目錄）
    備份到 backup_dir（一個全新、應該還不存在內容的目錄——呼叫端負責
    決定放在哪裡，這裡不假設任何特定路徑，方便測試也方便未來讓使用者
    自己選存放位置）。回傳的 manifest 同時也會寫入
    backup_dir/manifest.json。
    """
    data_dir = Path(data_dir)
    backup_dir = Path(backup_dir)
    payload_dir = backup_dir / PAYLOAD_DIRNAME
    payload_dir.mkdir(parents=True, exist_ok=True)

    included: list[str] = []
    checksums: dict[str, str] = {}
    total_size = 0

    for item in _BACKUP_INCLUDE_ITEMS:
        is_dir_item = item.endswith("/")
        name = item.rstrip("/")
        if name in _ALWAYS_EXCLUDED_ITEMS:
            continue  # 不應該發生（_BACKUP_INCLUDE_ITEMS 本身就沒放排除項），但保留這道防線

        source = data_dir / name
        if not source.exists():
            continue

        destination = payload_dir / name
        if is_dir_item:
            shutil.copytree(source, destination, dirs_exist_ok=True)
            for file_path in _iter_files_under(destination):
                rel = file_path.relative_to(payload_dir).as_posix()
                checksums[rel] = _sha256_of_file(file_path)
                total_size += file_path.stat().st_size
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            rel = destination.relative_to(payload_dir).as_posix()
            checksums[rel] = _sha256_of_file(destination)
            total_size += destination.stat().st_size

        included.append(name)

    manifest = BackupManifest(
        backup_id=uuid.uuid4().hex,
        created_at=datetime.now().isoformat(),
        app_version=APP_VERSION,
        source_data_dir=str(data_dir),
        included_items=included,
        excluded_items=list(_ALWAYS_EXCLUDED_ITEMS),
        file_count=len(checksums),
        total_size_bytes=total_size,
        checksums=checksums,
    )

    (backup_dir / MANIFEST_FILENAME).write_text(manifest.to_json(), encoding="utf-8")
    return manifest


def verify_backup(backup_dir: Path) -> BackupVerificationResult:
    """檢查 manifest 記錄的每一個檔案都還在、checksum 都吻合——用來在
    真正 restore 之前確認備份沒有損毀（規格第 21 節：verify backup）。
    """
    backup_dir = Path(backup_dir)
    manifest_path = backup_dir / MANIFEST_FILENAME
    if not manifest_path.exists():
        return BackupVerificationResult(ok=False, missing_files=[MANIFEST_FILENAME])

    manifest = BackupManifest.from_json(manifest_path.read_text(encoding="utf-8"))
    payload_dir = backup_dir / PAYLOAD_DIRNAME

    missing: list[str] = []
    mismatched: list[str] = []
    for rel_path, expected_hash in manifest.checksums.items():
        file_path = payload_dir / rel_path
        if not file_path.exists():
            missing.append(rel_path)
            continue
        if _sha256_of_file(file_path) != expected_hash:
            mismatched.append(rel_path)

    ok = not missing and not mismatched
    return BackupVerificationResult(ok=ok, missing_files=missing, checksum_mismatches=mismatched, manifest=manifest)


def restore_backup(backup_dir: Path, target_data_dir: Path, overwrite: bool = False) -> RestoreResult:
    """把備份還原到 target_data_dir。刻意保守：
    - 還原前一定先 verify_backup()，驗證失敗就拒絕還原（不半途而廢）。
    - 絕對不會去動 target_data_dir 底下的 facebook_browser_profile/
      ——即使目標資料夾已經有登入中的 Facebook session，還原備份也
      不應該影響它（因為備份本來就沒收錄它）。
    - 預設 overwrite=False：如果 target_data_dir 已經有同名檔案，拒絕
      覆蓋並拋出例外，除非呼叫端明確傳入 overwrite=True——避免不小心
      蓋掉使用者在還原當下已經產生的新資料。

    這個函式目前只在測試中對暫存目錄呼叫，還沒有任何 UI 按鈕會在
    production 資料夾上呼叫它（規格第 21 節把「還原」列為未來項目，
    這裡先把底層邏輯做對、做安全）。
    """
    result = verify_backup(backup_dir)
    if not result.ok or result.manifest is None:
        raise ValueError(
            f"備份驗證失敗，拒絕還原。missing={result.missing_files} mismatched={result.checksum_mismatches}"
        )

    backup_dir = Path(backup_dir)
    target_data_dir = Path(target_data_dir)
    payload_dir = backup_dir / PAYLOAD_DIRNAME
    target_data_dir.mkdir(parents=True, exist_ok=True)

    restored: list[str] = []
    skipped: list[str] = []

    for item in result.manifest.included_items:
        if item in _ALWAYS_EXCLUDED_ITEMS:
            skipped.append(item)
            continue

        source = payload_dir / item
        destination = target_data_dir / item

        if destination.exists() and not overwrite:
            raise FileExistsError(
                f"{destination} 已經存在，還原會覆蓋既有資料。請明確傳入 overwrite=True 才會執行。"
            )

        if source.is_dir():
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(source, destination)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        restored.append(item)

    return RestoreResult(restored_items=restored, skipped_excluded=skipped)
