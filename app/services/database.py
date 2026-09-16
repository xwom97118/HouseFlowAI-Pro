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

    def upsert_properties(self, properties: list[dict[str, Any]], source_url: str) -> int:
        saved = 0
        with self.connect() as conn:
            for item in properties:
                external_id = str(item.get("external_id", "")).strip()
                url = str(item.get("url", "")).strip()
                existing = None
                if external_id:
                    existing = conn.execute(
                        "SELECT id FROM properties WHERE external_id=? LIMIT 1",
                        (external_id,),
                    ).fetchone()
                if existing is None and url:
                    existing = conn.execute(
                        "SELECT id FROM properties WHERE url=? LIMIT 1",
                        (url,),
                    ).fetchone()
                image_paths="\n".join(item.get("image_paths", []))
                image_count=int(item.get("image_count",0))
                values = (
                    external_id,
                    str(item.get("title", "")).strip(),
                    str(item.get("address", "")).strip(),
                    str(item.get("price", "")).strip(),
                    str(item.get("layout", "")).strip(),
                    str(item.get("size", "")).strip(),
                    url,
                    str(item.get("status", "active")).strip() or "active",
                    source_url,
                    image_paths,
                    image_count,
                )
                if existing:
                    conn.execute(
                        """
                        UPDATE properties SET external_id=?, title=?, address=?, price=?,
                            layout=?, size=?, url=?, status=?, source_url=?, image_paths=?, image_count=?,
                            updated_at=CURRENT_TIMESTAMP WHERE id=?
                        """,
                        values + (existing["id"],),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO properties(
                            external_id, title, address, price, layout, size,
                            url, status, source_url, image_paths, image_count
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        values,
                    )
                saved += 1
        return saved

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