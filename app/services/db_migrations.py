"""正式 schema migration framework（2026-09-21 產品化 Phase 1）。

HouseFlow 一直以來的 schema 演進方式是 database.py 裡一整排
`_ensure_*_columns()`：每次啟動都檢查欄位存不存在、不存在就
`ALTER TABLE ADD COLUMN`。這個做法本身是安全的（冪等、不會刪資料），
但沒有版本記錄——沒辦法回答「這個資料庫現在是哪個版本」「上一次
migration 成功了沒」，未來要做真正需要資料轉換（不只是加欄位）的
版本升級時會很難掌控。

這裡建立的 framework：
- 一張 `schema_migrations` table，記錄「這個資料庫已經套用過哪些
  migration」，用 CREATE TABLE IF NOT EXISTS 建立——對已經存在、資料
  完整的 production 資料庫來說純粹是新增，不會動到任何既有的 table
  或欄位。
- Migration 只能「往前」套用（apply），每個 migration 都必須是
  冪等、可重複執行的（跟現有 `_ensure_*_columns()` 同一種寫法哲學）。
- 這一輪刻意只註冊一個 baseline migration（version 1），內容是
  no-op——現有 production 資料庫的 schema 已經等於 baseline，套用
  這個 migration 只是把「這個資料庫是 v1」這件事記錄下來，不會嘗試
  改變任何現有欄位或資料。之後真的需要 schema 變更時，往這個框架
  加新的 Migration 子類別即可，不需要再手動改 production SQLite。

這個模組本身不會在這一輪自動對 production 資料庫執行任何東西——
是否要把 MigrationRunner.migrate_to_latest() 接進
Database._initialize() 的正式啟動流程，留給下一階段決定並且需要先
過一次完整的 regression 才能上到會碰 production DB 的路徑。
"""
from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass


class Migration(ABC):
    """單一版本的 schema 變更。apply() 必須是冪等的——重複執行同一個
    已經套用過的 migration 不應該造成錯誤或資料變化（呼叫端理論上不會
    重複套用，但這個要求本身是防呆，跟 `_ensure_*_columns()` 現有的
    設計哲學一致）。
    """

    version: int
    description: str

    @abstractmethod
    def apply(self, conn: sqlite3.Connection) -> None: ...


class BaselineMigration(Migration):
    """version 1：現有 production schema 的基準線。不改變任何 table／
    欄位——純粹是「從這個版本開始，我們用 schema_migrations 記錄版本」
    這件事本身的起點。之後任何真正的欄位／table 變更都應該是
    version >= 2 的新 Migration，不能改這個 baseline。
    """

    version = 1
    description = "Baseline：記錄現有 schema 已知穩定狀態，不做任何變更。"

    def apply(self, conn: sqlite3.Connection) -> None:
        return None


@dataclass
class MigrationResult:
    starting_version: int
    ending_version: int
    applied_versions: list[int]

    @property
    def changed(self) -> bool:
        return bool(self.applied_versions)


class MigrationRunner:
    def __init__(self, migrations: list[Migration] | None = None) -> None:
        self.migrations = sorted(migrations or [BaselineMigration()], key=lambda m: m.version)
        seen_versions = [m.version for m in self.migrations]
        if len(seen_versions) != len(set(seen_versions)):
            raise ValueError(f"重複的 migration version：{seen_versions}")

    @staticmethod
    def ensure_schema_migrations_table(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                description TEXT NOT NULL DEFAULT '',
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    @classmethod
    def current_version(cls, conn: sqlite3.Connection) -> int:
        cls.ensure_schema_migrations_table(conn)
        row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
        value = row[0] if row else None
        return int(value) if value is not None else 0

    def pending_migrations(self, conn: sqlite3.Connection) -> list[Migration]:
        current = self.current_version(conn)
        return [m for m in self.migrations if m.version > current]

    def migrate_to_latest(self, conn: sqlite3.Connection, dry_run: bool = False) -> MigrationResult:
        """依序套用所有還沒套用過的 migration。單一 transaction 內完成
        （sqlite3 connection 預設就是 transaction），任何一個 migration
        失敗都會讓整批 rollback，不會留下「套用一半」的版本記錄——
        避免 production DB 卡在不上不下的狀態。
        """
        self.ensure_schema_migrations_table(conn)
        starting = self.current_version(conn)
        pending = self.pending_migrations(conn)
        applied: list[int] = []

        if dry_run or not pending:
            return MigrationResult(starting, starting, [])

        try:
            for migration in pending:
                migration.apply(conn)
                conn.execute(
                    "INSERT INTO schema_migrations(version, description) VALUES (?, ?)",
                    (migration.version, migration.description),
                )
                applied.append(migration.version)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        ending = self.current_version(conn)
        return MigrationResult(starting, ending, applied)


def default_runner() -> MigrationRunner:
    return MigrationRunner([BaselineMigration()])
