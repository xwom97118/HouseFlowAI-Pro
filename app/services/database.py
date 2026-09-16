from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "houseflow.db"


class Database:
    def __init__(self, path: Path = DB_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS properties (
                    id INTEGER PRIMARY KEY AUTOINCREMENT
                );
                """
            )
            self._ensure_property_columns(conn)
            conn.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_properties_source_id
                ON properties(source_id);

                CREATE UNIQUE INDEX IF NOT EXISTS idx_properties_external_id
                ON properties(external_id)
                WHERE external_id IS NOT NULL AND external_id != '';

                CREATE UNIQUE INDEX IF NOT EXISTS idx_properties_url
                ON properties(url)
                WHERE url IS NOT NULL AND url != '';

                CREATE TABLE IF NOT EXISTS property_notes (
                    property_id INTEGER PRIMARY KEY,
                    favorite INTEGER NOT NULL DEFAULT 0,
                    tag TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(property_id) REFERENCES properties(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS ai_generations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    property_id INTEGER,
                    platform TEXT NOT NULL,
                    style TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS contacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT '買方',
                    phone TEXT NOT NULL DEFAULT '',
                    budget TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '追蹤中',
                    next_followup TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS deal_strategies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    asking_price TEXT NOT NULL DEFAULT '',
                    buyer_offer TEXT NOT NULL DEFAULT '',
                    owner_floor TEXT NOT NULL DEFAULT '',
                    situation TEXT NOT NULL DEFAULT '',
                    strategy TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
CREATE TABLE IF NOT EXISTS facebook_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL UNIQUE,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS sync_sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    source_type TEXT NOT NULL DEFAULT 'yungching_store',
                    url TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    auto_sync_enabled INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_sync_at TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS sync_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id INTEGER,
                    source_url TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    finished_at TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'running',
                    found_count INTEGER NOT NULL DEFAULT 0,
                    new_count INTEGER NOT NULL DEFAULT 0,
                    updated_count INTEGER NOT NULL DEFAULT 0,
                    offline_count INTEGER NOT NULL DEFAULT 0,
                    failed_count INTEGER NOT NULL DEFAULT 0,
                    duration_seconds INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(source_id) REFERENCES sync_sources(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS property_changes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    property_id INTEGER NOT NULL,
                    change_type TEXT NOT NULL,
                    old_value TEXT NOT NULL DEFAULT '',
                    new_value TEXT NOT NULL DEFAULT '',
                    detected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    sync_run_id INTEGER,
                    FOREIGN KEY(property_id) REFERENCES properties(id) ON DELETE CASCADE,
                    FOREIGN KEY(sync_run_id) REFERENCES sync_runs(id) ON DELETE SET NULL
                );

                CREATE INDEX IF NOT EXISTS idx_property_changes_property
                ON property_changes(property_id);

                CREATE INDEX IF NOT EXISTS idx_property_changes_run
                ON property_changes(sync_run_id);

                CREATE INDEX IF NOT EXISTS idx_sync_runs_source
                ON sync_runs(source_id);
                """
            )
            self.set_default_setting(conn, "ai_enabled", "0")

    @staticmethod
    def set_default_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
        conn.execute(
            "INSERT OR IGNORE INTO app_settings(key, value) VALUES (?, ?)",
            (key, value),
        )

    def _ensure_property_columns(self, conn: sqlite3.Connection) -> None:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(properties)")}
        additions = {
            "external_id": "TEXT",
            "title": "TEXT NOT NULL DEFAULT ''",
            "address": "TEXT NOT NULL DEFAULT ''",
            "price": "TEXT NOT NULL DEFAULT ''",
            "layout": "TEXT NOT NULL DEFAULT ''",
            "size": "TEXT NOT NULL DEFAULT ''",
            "url": "TEXT NOT NULL DEFAULT ''",
            "status": "TEXT NOT NULL DEFAULT 'active'",
            "source_url": "TEXT NOT NULL DEFAULT ''",
            "created_at": "TEXT NOT NULL DEFAULT ''",
            "updated_at": "TEXT NOT NULL DEFAULT ''",
            "image_paths": "TEXT NOT NULL DEFAULT ''",
            "image_count": "INTEGER NOT NULL DEFAULT 0",
            "property_type": "TEXT NOT NULL DEFAULT ''",
            "community": "TEXT NOT NULL DEFAULT ''",
            "features": "TEXT NOT NULL DEFAULT ''",
            "source_site": "TEXT NOT NULL DEFAULT ''",
            "source_id": "INTEGER",
            "last_seen_at": "TEXT NOT NULL DEFAULT ''",
        }
        for column, definition in additions.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE properties ADD COLUMN {column} {definition}")

    def table_exists(self, name: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (name,),
            ).fetchone()
        return row is not None

    def columns(self, table: str) -> list[str]:
        if not self.table_exists(table):
            return []
        with self.connect() as conn:
            return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]

    def count(self, table: str, where: str = "", params: tuple[Any, ...] = ()) -> int:
        if not self.table_exists(table):
            return 0
        sql = f"SELECT COUNT(*) FROM {table}"
        if where:
            sql += f" WHERE {where}"
        with self.connect() as conn:
            return int(conn.execute(sql, params).fetchone()[0])

    def dashboard_counts(self) -> dict[str, int]:
        return {
            "properties": self.count("properties"),
            "favorites": self.count("property_notes", "favorite = 1"),
            "drafts": self.count("ai_generations"),
            "scheduled": self.count("schedules"),
            "contacts": self.count("contacts"),
        }

    def list_properties(self, search: str = "", favorites_only: bool = False) -> list[dict[str, Any]]:
        sql = """
            SELECT p.id, p.external_id, p.title, p.address, p.price,
                   p.layout, p.size, p.url, p.status, p.source_url, p.updated_at,
                   p.image_paths, p.image_count,
                   p.property_type, p.community, p.features, p.source_site,
                   p.source_id, p.last_seen_at,
                   COALESCE(n.favorite, 0) AS favorite,
                   COALESCE(n.tag, '') AS tag,
                   COALESCE(n.note, '') AS note
            FROM properties p
            LEFT JOIN property_notes n ON n.property_id = p.id
        """
        clauses: list[str] = []
        params: list[Any] = []
        if search:
            pattern = f"%{search}%"
            clauses.append(
                "(p.title LIKE ? OR p.address LIKE ? OR p.external_id LIKE ? "
                "OR p.price LIKE ? OR n.tag LIKE ? OR n.note LIKE ?)"
            )
            params.extend([pattern] * 6)
        if favorites_only:
            clauses.append("COALESCE(n.favorite, 0) = 1")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY COALESCE(n.favorite, 0) DESC, p.updated_at DESC, p.id DESC LIMIT 500"
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]

    def get_property(self, property_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT p.*, COALESCE(n.favorite, 0) AS favorite,
                       COALESCE(n.tag, '') AS tag, COALESCE(n.note, '') AS note
                FROM properties p
                LEFT JOIN property_notes n ON n.property_id = p.id
                WHERE p.id = ?
                """,
                (property_id,),
            ).fetchone()
        return dict(row) if row else None

    def upsert_properties(
        self,
        properties: list[dict[str, Any]],
        source_url: str,
        source_id: int | None = None,
        sync_run_id: int | None = None,
    ) -> int:
        """向下相容的簡易寫入介面（單一物件匯入、舊呼叫端使用）。"""
        counts = self.sync_properties_for_source(
            properties,
            source_url=source_url,
            source_id=source_id,
            sync_run_id=sync_run_id,
            mark_offline=False,
        )
        return counts["new"] + counts["updated"]

    def sync_properties_for_source(
        self,
        properties: list[dict[str, Any]],
        source_url: str,
        source_id: int | None = None,
        sync_run_id: int | None = None,
        mark_offline: bool = False,
    ) -> dict[str, int]:
        """寫入這次同步抓到的物件，並記錄新增／異動／下架。

        只有 mark_offline=True 時才會把這個來源「這次沒抓到」的既有物件
        標記下架；呼叫端必須自行確保這次同步是「完整且沒有失敗頁面」，
        避免同步中途失敗把大量物件誤標下架。
        """
        counts = {
            "new": 0,
            "updated": 0,
            "price_changed": 0,
            "content_changed": 0,
            "online_again": 0,
            "offline": 0,
        }
        seen_ids: list[int] = []

        with self.connect() as conn:
            for item in properties:
                property_id, change = self._upsert_property_row(
                    conn, item, source_url, source_id, sync_run_id
                )
                seen_ids.append(property_id)
                counts["new" if change["created"] else "updated"] += 1
                if change["price_changed"]:
                    counts["price_changed"] += 1
                if change["content_changed"]:
                    counts["content_changed"] += 1
                if change["online_again"]:
                    counts["online_again"] += 1

            if mark_offline and source_id is not None:
                counts["offline"] = self._mark_offline_properties(
                    conn, source_id, seen_ids, sync_run_id
                )

        return counts

    def _upsert_property_row(
        self,
        conn: sqlite3.Connection,
        item: dict[str, Any],
        source_url: str,
        source_id: int | None,
        sync_run_id: int | None,
    ) -> tuple[int, dict[str, bool]]:
        external_id = str(item.get("external_id", "")).strip()
        url = str(item.get("url", "")).strip()

        existing = None
        if external_id:
            existing = conn.execute(
                "SELECT * FROM properties WHERE external_id=? LIMIT 1",
                (external_id,),
            ).fetchone()
        if existing is None and url:
            existing = conn.execute(
                "SELECT * FROM properties WHERE url=? LIMIT 1",
                (url,),
            ).fetchone()

        image_paths_value = item.get("image_paths", [])
        if isinstance(image_paths_value, str):
            image_paths = image_paths_value
        else:
            image_paths = "\n".join(image_paths_value)

        features_value = item.get("features", [])
        if isinstance(features_value, str):
            features = features_value
        else:
            features = "、".join(features_value)

        new_price = str(item.get("price", "")).strip()
        new_fields = {
            "external_id": external_id,
            "title": str(item.get("title", "")).strip(),
            "address": str(item.get("address", "")).strip(),
            "price": new_price,
            "layout": str(item.get("layout", "")).strip(),
            "size": str(item.get("size", "")).strip(),
            "url": url,
            "status": str(item.get("status", "active")).strip() or "active",
            "source_url": source_url,
            "image_paths": image_paths,
            "image_count": int(item.get("image_count", 0) or 0),
            "property_type": str(item.get("property_type", "")).strip(),
            "community": str(item.get("community", "")).strip(),
            "features": features,
            "source_site": str(item.get("source_site", "")).strip(),
        }
        if source_id is not None:
            new_fields["source_id"] = source_id

        change = {
            "created": existing is None,
            "price_changed": False,
            "content_changed": False,
            "online_again": False,
        }

        content_compare_keys = (
            "title", "address", "layout", "size", "property_type",
            "community", "features", "image_count",
        )

        if existing is not None:
            old_price = str(existing["price"] or "").strip()
            if new_price and old_price and new_price != old_price:
                change["price_changed"] = True
            for key in content_compare_keys:
                old_value = existing[key] if key in existing.keys() else ""
                if old_value is None:
                    old_value = ""
                if str(new_fields[key]) != str(old_value):
                    change["content_changed"] = True
                    break
            if str(existing["status"] or "") == "offline" and new_fields["status"] != "offline":
                change["online_again"] = True

        columns = list(new_fields.keys())
        values = [new_fields[key] for key in columns]

        if existing is None:
            placeholders = ", ".join("?" for _ in columns)
            cur = conn.execute(
                f"""
                INSERT INTO properties(
                    {', '.join(columns)}, last_seen_at
                ) VALUES ({placeholders}, CURRENT_TIMESTAMP)
                """,
                values,
            )
            property_id = int(cur.lastrowid)
        else:
            assignments = ", ".join(f"{key}=?" for key in columns)
            conn.execute(
                f"""
                UPDATE properties SET {assignments},
                    updated_at=CURRENT_TIMESTAMP, last_seen_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                values + [existing["id"]],
            )
            property_id = int(existing["id"])

        if change["price_changed"]:
            self._record_property_change(
                conn, property_id, "price_changed", old_price, new_price, sync_run_id
            )
        if change["content_changed"]:
            self._record_property_change(
                conn, property_id, "content_changed", "", "", sync_run_id
            )
        if change["online_again"]:
            self._record_property_change(
                conn, property_id, "online_again", "offline", "active", sync_run_id
            )
        if change["created"]:
            self._record_property_change(
                conn, property_id, "created", "", new_fields["title"], sync_run_id
            )

        return property_id, change

    def _mark_offline_properties(
        self,
        conn: sqlite3.Connection,
        source_id: int,
        seen_ids: list[int],
        sync_run_id: int | None,
    ) -> int:
        placeholders = ", ".join("?" for _ in seen_ids) if seen_ids else ""
        where_not_seen = f"AND id NOT IN ({placeholders})" if placeholders else ""
        params: list[Any] = [source_id]
        params.extend(seen_ids)

        candidates = conn.execute(
            f"""
            SELECT id FROM properties
            WHERE source_id=? AND status != 'offline' {where_not_seen}
            """,
            params,
        ).fetchall()

        active_total = conn.execute(
            "SELECT COUNT(*) FROM properties WHERE source_id=? AND status != 'offline'",
            (source_id,),
        ).fetchone()[0]

        # 安全判定：單次同步不應該把來源中大部分物件都判定下架，
        # 避免解析失敗或網站改版時誤刪一整批物件的狀態。
        if active_total > 0 and len(candidates) > max(3, active_total * 0.5):
            return 0

        for row in candidates:
            conn.execute(
                "UPDATE properties SET status='offline', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (row["id"],),
            )
            self._record_property_change(
                conn, row["id"], "offline", "active", "offline", sync_run_id
            )

        return len(candidates)

    @staticmethod
    def _record_property_change(
        conn: sqlite3.Connection,
        property_id: int,
        change_type: str,
        old_value: str,
        new_value: str,
        sync_run_id: int | None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO property_changes(property_id, change_type, old_value, new_value, sync_run_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (property_id, change_type, old_value, new_value, sync_run_id),
        )

    def list_property_changes(
        self,
        limit: int = 100,
        change_type: str = "",
        since: str = "",
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT c.*, p.title AS property_title, p.external_id AS property_external_id
            FROM property_changes c
            LEFT JOIN properties p ON p.id = c.property_id
        """
        clauses: list[str] = []
        params: list[Any] = []
        if change_type:
            clauses.append("c.change_type = ?")
            params.append(change_type)
        if since:
            clauses.append("c.detected_at >= ?")
            params.append(since)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY c.detected_at DESC, c.id DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]

    # ---------------------------------------------------------------
    # Sync Center：同步來源
    # ---------------------------------------------------------------

    def list_sync_sources(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM sync_sources ORDER BY name"
                ).fetchall()
            ]

    def get_sync_source(self, source_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM sync_sources WHERE id=?", (source_id,)
            ).fetchone()
        return dict(row) if row else None

    def save_sync_source(
        self, data: dict[str, Any], source_id: int | None = None
    ) -> int:
        name = str(data.get("name", "")).strip() or "未命名來源"
        source_type = str(data.get("source_type", "yungching_store")).strip() or "yungching_store"
        url = str(data.get("url", "")).strip()
        enabled = 1 if data.get("enabled", True) else 0
        auto_sync_enabled = 1 if data.get("auto_sync_enabled", False) else 0

        if not url:
            raise ValueError("同步來源網址不可空白")

        with self.connect() as conn:
            if source_id is None:
                cur = conn.execute(
                    """
                    INSERT INTO sync_sources(name, source_type, url, enabled, auto_sync_enabled)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (name, source_type, url, enabled, auto_sync_enabled),
                )
                return int(cur.lastrowid)
            conn.execute(
                """
                UPDATE sync_sources SET name=?, source_type=?, url=?, enabled=?,
                    auto_sync_enabled=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (name, source_type, url, enabled, auto_sync_enabled, source_id),
            )
            return source_id

    def delete_sync_source(self, source_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM sync_sources WHERE id=?", (source_id,))

    def set_sync_source_enabled(self, source_id: int, enabled: bool) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE sync_sources SET enabled=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (1 if enabled else 0, source_id),
            )

    def set_sync_source_auto(self, source_id: int, enabled: bool) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE sync_sources SET auto_sync_enabled=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (1 if enabled else 0, source_id),
            )

    def touch_sync_source_last_sync(self, source_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE sync_sources SET last_sync_at=CURRENT_TIMESTAMP,
                    updated_at=CURRENT_TIMESTAMP WHERE id=?
                """,
                (source_id,),
            )

    # ---------------------------------------------------------------
    # Sync Center：同步紀錄
    # ---------------------------------------------------------------

    def create_sync_run(self, source_id: int | None, source_url: str) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO sync_runs(source_id, source_url, status)
                VALUES (?, ?, 'running')
                """,
                (source_id, source_url),
            )
            return int(cur.lastrowid)

    def finish_sync_run(
        self,
        run_id: int,
        status: str,
        found_count: int = 0,
        new_count: int = 0,
        updated_count: int = 0,
        offline_count: int = 0,
        failed_count: int = 0,
        duration_seconds: int = 0,
        error_message: str = "",
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE sync_runs SET
                    status=?, found_count=?, new_count=?, updated_count=?,
                    offline_count=?, failed_count=?, duration_seconds=?,
                    error_message=?, finished_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    status, found_count, new_count, updated_count,
                    offline_count, failed_count, duration_seconds,
                    error_message, run_id,
                ),
            )

    def list_sync_runs(
        self, source_id: int | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT r.*, COALESCE(s.name, '手動同步（未建立來源）') AS source_name
            FROM sync_runs r
            LEFT JOIN sync_sources s ON s.id = r.source_id
        """
        params: list[Any] = []
        if source_id is not None:
            sql += " WHERE r.source_id = ?"
            params.append(source_id)
        sql += " ORDER BY r.started_at DESC, r.id DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]

    def get_last_sync_run(self, source_id: int | None = None) -> dict[str, Any] | None:
        runs = self.list_sync_runs(source_id=source_id, limit=1)
        return runs[0] if runs else None

    def sync_dashboard_summary(self) -> dict[str, Any]:
        with self.connect() as conn:
            last_run = conn.execute(
                "SELECT * FROM sync_runs WHERE status != 'running' ORDER BY started_at DESC, id DESC LIMIT 1"
            ).fetchone()
            today_new = conn.execute(
                "SELECT COUNT(*) FROM property_changes WHERE change_type='created' AND date(detected_at)=date('now', 'localtime')"
            ).fetchone()[0]
            today_price = conn.execute(
                "SELECT COUNT(*) FROM property_changes WHERE change_type='price_changed' AND date(detected_at)=date('now', 'localtime')"
            ).fetchone()[0]
            today_offline = conn.execute(
                "SELECT COUNT(*) FROM property_changes WHERE change_type='offline' AND date(detected_at)=date('now', 'localtime')"
            ).fetchone()[0]
            today_failed_runs = conn.execute(
                "SELECT COUNT(*) FROM sync_runs WHERE status='failed' AND date(started_at)=date('now', 'localtime')"
            ).fetchone()[0]
            total_properties = conn.execute(
                "SELECT COUNT(*) FROM properties WHERE status != 'offline'"
            ).fetchone()[0]

        return {
            "last_sync_at": last_run["started_at"] if last_run else "",
            "last_sync_status": last_run["status"] if last_run else "",
            "today_new": today_new,
            "today_price_changed": today_price,
            "today_offline": today_offline,
            "today_failed": today_failed_runs,
            "total_properties": total_properties,
        }

    def get_note(self, property_id: int) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT favorite, tag, note, updated_at FROM property_notes WHERE property_id=?",
                (property_id,),
            ).fetchone()
        return dict(row) if row else {"favorite": 0, "tag": "", "note": ""}

    def save_note(self, property_id: int, favorite: int, tag: str, note: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO property_notes(property_id, favorite, tag, note, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(property_id) DO UPDATE SET
                    favorite=excluded.favorite,
                    tag=excluded.tag,
                    note=excluded.note,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (property_id, 1 if favorite else 0, tag.strip(), note.strip()),
            )

    def get_setting(self, key: str, default: str = "") -> str:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO app_settings(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, value),
            )

    def save_generation(self, property_id: int, platform: str, style: str, content: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO ai_generations(property_id, platform, style, content)
                VALUES (?, ?, ?, ?)
                """,
                (property_id, platform, style, content),
            )

    def list_contacts(self, search: str = "") -> list[dict[str, Any]]:
        sql = "SELECT * FROM contacts"
        params: tuple[Any, ...] = ()
        if search:
            pattern = f"%{search}%"
            sql += " WHERE name LIKE ? OR role LIKE ? OR phone LIKE ? OR status LIKE ? OR note LIKE ?"
            params = (pattern, pattern, pattern, pattern, pattern)
        sql += " ORDER BY CASE WHEN next_followup='' THEN 1 ELSE 0 END, next_followup, updated_at DESC"
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def save_contact(self, data: dict[str, Any], contact_id: int | None = None) -> int:
        values = (
            str(data.get("name", "")).strip(),
            str(data.get("role", "買方")).strip() or "買方",
            str(data.get("phone", "")).strip(),
            str(data.get("budget", "")).strip(),
            str(data.get("status", "追蹤中")).strip() or "追蹤中",
            str(data.get("next_followup", "")).strip(),
            str(data.get("note", "")).strip(),
        )
        if not values[0]:
            raise ValueError("聯絡人姓名不可空白")
        with self.connect() as conn:
            if contact_id is None:
                cur = conn.execute(
                    """INSERT INTO contacts(name, role, phone, budget, status, next_followup, note)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""", values
                )
                return int(cur.lastrowid)
            conn.execute(
                """UPDATE contacts SET name=?, role=?, phone=?, budget=?, status=?,
                   next_followup=?, note=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                values + (contact_id,),
            )
            return contact_id

    def delete_contact(self, contact_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM contacts WHERE id=?", (contact_id,))

    def list_strategies(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM deal_strategies ORDER BY created_at DESC, id DESC LIMIT 100"
            ).fetchall()]

    def save_strategy(self, data: dict[str, Any]) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """INSERT INTO deal_strategies(
                    title, asking_price, buyer_offer, owner_floor, situation, strategy
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    str(data.get("title", "")).strip() or "未命名案件",
                    str(data.get("asking_price", "")).strip(),
                    str(data.get("buyer_offer", "")).strip(),
                    str(data.get("owner_floor", "")).strip(),
                    str(data.get("situation", "")).strip(),
                    str(data.get("strategy", "")).strip(),
                ),
            )
            return int(cur.lastrowid)


    def list_facebook_groups(self):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM facebook_groups ORDER BY name"
            ).fetchall()
        return [dict(r) for r in rows]

    def save_facebook_group(self, name: str, url: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO facebook_groups(name, url)
                VALUES (?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    name=excluded.name,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (name.strip(), url.strip()),
            )

    def delete_facebook_group(self, group_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM facebook_groups WHERE id=?",
                (group_id,),
            )

    def enabled_groups(self):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM facebook_groups WHERE enabled=1 ORDER BY name"
            ).fetchall()
        return [dict(r) for r in rows]

    def set_group_enabled(self, group_id: int, enabled: bool) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE facebook_groups
                SET enabled=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (1 if enabled else 0, group_id),
            )