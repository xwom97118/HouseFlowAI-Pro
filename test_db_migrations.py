"""Schema migration framework 的正式回歸測試（2026-09-21 產品化 Phase
1，規格第 30 節：migration tests；第 23 節：backup, migration,
validation, rollback/failure recovery）。

全部對著一次性的暫存 SQLite 檔案（tempfile）測試，完全不碰 production
資料庫。
"""
from __future__ import annotations

import os
import sqlite3
import tempfile

from app.services.db_migrations import (
    BaselineMigration,
    Migration,
    MigrationRunner,
    default_runner,
)


class _AddColumnMigration(Migration):
    version = 2
    description = "新增 properties.test_column 欄位（測試用）。"

    def apply(self, conn: sqlite3.Connection) -> None:
        conn.execute("ALTER TABLE properties ADD COLUMN test_column TEXT DEFAULT ''")


class _FailingMigration(Migration):
    version = 3
    description = "刻意失敗的 migration，用來驗證 rollback。"

    def apply(self, conn: sqlite3.Connection) -> None:
        raise RuntimeError("deliberate failure for rollback test")


def _temp_conn():
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE properties (id INTEGER PRIMARY KEY, title TEXT)")
    conn.commit()
    return conn, path


def _cleanup(conn: sqlite3.Connection, path: str) -> None:
    conn.close()
    try:
        os.remove(path)
    except OSError:
        pass


def test_fresh_database_has_version_zero() -> None:
    conn, path = _temp_conn()
    try:
        assert MigrationRunner.current_version(conn) == 0
    finally:
        _cleanup(conn, path)


def test_migrate_to_latest_applies_baseline() -> None:
    conn, path = _temp_conn()
    try:
        runner = default_runner()
        result = runner.migrate_to_latest(conn)
        assert result.starting_version == 0
        assert result.ending_version == 1
        assert result.applied_versions == [1]
        assert result.changed is True
        assert MigrationRunner.current_version(conn) == 1
    finally:
        _cleanup(conn, path)


def test_migrate_to_latest_is_idempotent() -> None:
    conn, path = _temp_conn()
    try:
        runner = default_runner()
        runner.migrate_to_latest(conn)
        result = runner.migrate_to_latest(conn)
        assert result.starting_version == 1
        assert result.ending_version == 1
        assert result.applied_versions == []
        assert result.changed is False
    finally:
        _cleanup(conn, path)


def test_baseline_migration_does_not_modify_existing_schema() -> None:
    conn, path = _temp_conn()
    try:
        conn.execute("INSERT INTO properties (id, title) VALUES (1, 'existing row')")
        conn.commit()

        runner = default_runner()
        runner.migrate_to_latest(conn)

        row = conn.execute("SELECT title FROM properties WHERE id = 1").fetchone()
        assert row[0] == "existing row"

        columns = [r[1] for r in conn.execute("PRAGMA table_info(properties)").fetchall()]
        assert columns == ["id", "title"]  # baseline 沒有新增任何欄位
    finally:
        _cleanup(conn, path)


def test_incremental_migration_is_applied_in_order() -> None:
    conn, path = _temp_conn()
    try:
        runner = MigrationRunner([BaselineMigration(), _AddColumnMigration()])
        result = runner.migrate_to_latest(conn)

        assert result.applied_versions == [1, 2]
        assert MigrationRunner.current_version(conn) == 2

        columns = [r[1] for r in conn.execute("PRAGMA table_info(properties)").fetchall()]
        assert "test_column" in columns
    finally:
        _cleanup(conn, path)


def test_pending_migrations_only_returns_unapplied() -> None:
    conn, path = _temp_conn()
    try:
        runner = MigrationRunner([BaselineMigration(), _AddColumnMigration()])
        runner.migrate_to_latest(conn)

        # 模擬之後又加了一個新版本
        runner_v3 = MigrationRunner([BaselineMigration(), _AddColumnMigration()])
        pending = runner_v3.pending_migrations(conn)
        assert pending == []
    finally:
        _cleanup(conn, path)


def test_dry_run_does_not_change_version() -> None:
    conn, path = _temp_conn()
    try:
        runner = default_runner()
        result = runner.migrate_to_latest(conn, dry_run=True)
        assert result.changed is False
        assert MigrationRunner.current_version(conn) == 0
    finally:
        _cleanup(conn, path)


def test_failing_migration_rolls_back_entire_batch() -> None:
    """一批 migration 裡有一個失敗，整批都要 rollback——不能留下
    「套用一半」的版本記錄（規格第 23 節：rollback/failure recovery）。
    """
    conn, path = _temp_conn()
    try:
        runner = MigrationRunner([BaselineMigration(), _AddColumnMigration(), _FailingMigration()])
        try:
            runner.migrate_to_latest(conn)
            raise AssertionError("expected RuntimeError from _FailingMigration")
        except RuntimeError:
            pass

        # 整批（含原本會成功的 version 1, 2）都應該被 rollback，版本停在 0
        assert MigrationRunner.current_version(conn) == 0
        columns = [r[1] for r in conn.execute("PRAGMA table_info(properties)").fetchall()]
        assert "test_column" not in columns
    finally:
        _cleanup(conn, path)


def test_duplicate_version_numbers_rejected_at_construction() -> None:
    class _DupA(Migration):
        version = 5
        description = "a"

        def apply(self, conn):
            return None

    class _DupB(Migration):
        version = 5
        description = "b"

        def apply(self, conn):
            return None

    try:
        MigrationRunner([_DupA(), _DupB()])
        raise AssertionError("expected ValueError for duplicate migration versions")
    except ValueError:
        pass


def test_not_wired_into_production_database_initialize() -> None:
    """規格第 30 節：這一輪 Production DB 是唯讀，migration framework
    刻意「沒有」接進 Database._initialize()。這裡驗證 database.py 的
    原始碼裡沒有 import/呼叫 db_migrations，避免未來不小心接上去卻
    忘記通知使用者先驗收。
    """
    import inspect

    from app.services import database

    source = inspect.getsource(database)
    assert "db_migrations" not in source
    assert "MigrationRunner" not in source


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
