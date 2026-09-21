from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.services import app_paths

# 排程相關時間欄位（scheduled_at、next_retry_at、delete_at、
# delete_next_retry_at、published_at、started_at、deleted_at）統一用
# 「本機時間」字串（跟 QDateTimeEdit 選出來的時間同一個基準），不要
# 混用 SQLite 的 CURRENT_TIMESTAMP（那是 UTC）。這裡提供一個共用格式
# 化函式，確保全部一致，避免比較時區跑掉。
LOCAL_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def now_local_str() -> str:
    return datetime.now().strftime(LOCAL_TIME_FORMAT)


def local_str_plus(base: str | None, **delta_kwargs: float) -> str:
    """base 是本機時間字串（空字串代表現在），回傳 base + timedelta。"""
    if base:
        try:
            start = datetime.strptime(base, LOCAL_TIME_FORMAT)
        except ValueError:
            start = datetime.now()
    else:
        start = datetime.now()
    return (start + timedelta(**delta_kwargs)).strftime(LOCAL_TIME_FORMAT)


class DuplicateSyncSourceError(Exception):
    """新增同步來源時，網址正規化後跟現有來源相同。"""

    def __init__(self, existing_id: int, existing_name: str) -> None:
        self.existing_id = existing_id
        self.existing_name = existing_name
        super().__init__(f"同步來源已存在：{existing_name}")


class Database:
    def __init__(self, path: Path | None = None) -> None:
        path = path if path is not None else app_paths.db_path()
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

                CREATE TABLE IF NOT EXISTS schedules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    property_id INTEGER,
                    platform TEXT NOT NULL DEFAULT 'facebook',
                    target TEXT NOT NULL DEFAULT '',
                    target_label TEXT NOT NULL DEFAULT '',
                    copy_text TEXT NOT NULL DEFAULT '',
                    images TEXT NOT NULL DEFAULT '',
                    scheduled_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    approved_at TEXT NOT NULL DEFAULT '',
                    published_at TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending_review',
                    post_url TEXT NOT NULL DEFAULT '',
                    post_id TEXT NOT NULL DEFAULT '',
                    error_message TEXT NOT NULL DEFAULT '',
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(property_id) REFERENCES properties(id) ON DELETE SET NULL
                );

                CREATE INDEX IF NOT EXISTS idx_schedules_status
                ON schedules(status);

                CREATE INDEX IF NOT EXISTS idx_schedules_scheduled_at
                ON schedules(scheduled_at);

                CREATE INDEX IF NOT EXISTS idx_schedules_property
                ON schedules(property_id);

                CREATE INDEX IF NOT EXISTS idx_schedules_created_at
                ON schedules(created_at);

                CREATE TABLE IF NOT EXISTS schedule_executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    schedule_id INTEGER NOT NULL,
                    execution_type TEXT NOT NULL,
                    attempt_number INTEGER NOT NULL DEFAULT 1,
                    execution_token TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL DEFAULT '',
                    finished_at TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'running',
                    error_message TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(schedule_id) REFERENCES schedules(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_schedule_executions_schedule
                ON schedule_executions(schedule_id);
                """
            )
            self._ensure_sync_source_columns(conn)
            self._ensure_sync_source_indexes(conn)
            self._ensure_schedule_columns(conn)
            self._ensure_schedule_delete_indexes(conn)
            self.set_default_setting(conn, "ai_enabled", "0")
            self._seed_default_brand_profile(conn)
            self._seed_default_automation_settings(conn)

    def _ensure_schedule_columns(self, conn: sqlite3.Connection) -> None:
        """3.3 Automation Engine 用到的欄位：atomic claim token、批次
        分組（同一次「加入排程」建立的多個 target 共用 batch_id，UI
        用來顯示「3/4 發布成功」）、發布重試排程、自動刪文規則與狀態。
        backward-compatible ALTER TABLE，不影響既有 schedules 資料。
        """
        existing = {row[1] for row in conn.execute("PRAGMA table_info(schedules)")}
        additions = {
            "batch_id": "TEXT NOT NULL DEFAULT ''",
            "execution_token": "TEXT NOT NULL DEFAULT ''",
            "started_at": "TEXT NOT NULL DEFAULT ''",
            "next_retry_at": "TEXT NOT NULL DEFAULT ''",
            "delete_after_days": "INTEGER",
            # DEV ONLY：分鐘級的刪文倒數，供開發驗收測試使用（例如「發布
            # 後 5 分鐘」），不對應任何正式 UI 選項，一般排程永遠是 NULL。
            # delete_after_days 是整數天，天生無法表示 5 分鐘這種粒度，
            # 所以另外開一個欄位，而不是硬塞一個會被 int() 捨去成 0 的
            # 假天數。mark_schedule_published() 有值時優先使用這個欄位。
            "delete_after_minutes": "INTEGER",
            "delete_at": "TEXT NOT NULL DEFAULT ''",
            "delete_status": "TEXT NOT NULL DEFAULT 'not_scheduled'",
            "delete_attempt_count": "INTEGER NOT NULL DEFAULT 0",
            "delete_next_retry_at": "TEXT NOT NULL DEFAULT ''",
            "deleted_at": "TEXT NOT NULL DEFAULT ''",
        }
        for column, definition in additions.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE schedules ADD COLUMN {column} {definition}")

    def _ensure_schedule_delete_indexes(self, conn: sqlite3.Connection) -> None:
        """delete_status/delete_at 是用 ALTER TABLE 後補上的欄位，所以索引
        要等 _ensure_schedule_columns() 確保欄位存在之後才能建立。
        """
        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_schedules_delete_status
            ON schedules(delete_status);

            CREATE INDEX IF NOT EXISTS idx_schedules_delete_at
            ON schedules(delete_at);
            """
        )

    def _seed_default_automation_settings(self, conn: sqlite3.Connection) -> None:
        defaults = {
            "automation_enabled": "1",
            "automation_check_interval_seconds": "30",
            "automation_max_publish_retries": "3",
            "automation_delete_enabled": "1",
            "automation_default_delete_days": "15",
            "automation_max_delete_retries": "3",
            "minimize_to_tray": "1",
            "timezone": "Asia/Taipei",
            "history_retention_days": "15",
            "automation_sync_enabled": "1",
            "automation_sync_max_concurrent": "1",
            "automation_sync_timeout_seconds": "120",
            "automation_sync_max_retries": "3",
            "sync_history_retention_days": "30",
        }
        for key, value in defaults.items():
            self.set_default_setting(conn, key, value)

    def _ensure_sync_source_columns(self, conn: sqlite3.Connection) -> None:
        """3.4 Auto Sync Center 用到的欄位：atomic claim（sync_status +
        execution_token，跟 schedules 的 claim 模式一樣）、重試狀態、
        累計次數。sync_interval_minutes/next_sync_at 是 3.3 就預留的
        欄位，這裡繼續沿用，不重新建立。全部都是 backward-compatible
        ALTER TABLE，不影響既有 sync_sources 資料。
        """
        existing = {row[1] for row in conn.execute("PRAGMA table_info(sync_sources)")}
        additions = {
            "sync_interval_minutes": "INTEGER NOT NULL DEFAULT 60",
            "next_sync_at": "TEXT NOT NULL DEFAULT ''",
            "sync_status": "TEXT NOT NULL DEFAULT 'idle'",
            "execution_token": "TEXT NOT NULL DEFAULT ''",
            "last_status": "TEXT NOT NULL DEFAULT ''",
            "last_error": "TEXT NOT NULL DEFAULT ''",
            "last_success_at": "TEXT NOT NULL DEFAULT ''",
            "last_failure_at": "TEXT NOT NULL DEFAULT ''",
            "retry_count": "INTEGER NOT NULL DEFAULT 0",
            "next_retry_at": "TEXT NOT NULL DEFAULT ''",
            "sync_success_count": "INTEGER NOT NULL DEFAULT 0",
            "sync_failure_count": "INTEGER NOT NULL DEFAULT 0",
            "syncing_started_at": "TEXT NOT NULL DEFAULT ''",
        }
        for column, definition in additions.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE sync_sources ADD COLUMN {column} {definition}")

    def _ensure_sync_source_indexes(self, conn: sqlite3.Connection) -> None:
        """next_sync_at/sync_status 是後補欄位，索引要等欄位確定存在後才能建立。"""
        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_sync_sources_next_sync
            ON sync_sources(next_sync_at);

            CREATE INDEX IF NOT EXISTS idx_sync_sources_status
            ON sync_sources(sync_status);
            """
        )

    def _seed_default_brand_profile(self, conn: sqlite3.Connection) -> None:
        """第一次啟動時的品牌／經紀業資訊種子值。只有在該 key 完全沒有
        值時才會寫入（set_default_setting 用 INSERT OR IGNORE），之後
        使用者在設定頁改掉的內容永遠不會被這裡覆蓋。之所以在這裡而不是
        寫死在 copywriting_engine.py，是因為這些是「這台機器目前使用者
        的資料」，不是程式邏輯，未來其他房仲安裝 HouseFlow 時應該要能
        完全換成自己的資料，而不必改程式碼。
        """
        defaults = {
            "display_name": "阿嘉",
            "brand_slogan": "我是阿嘉，幫你更了解你的不動產價值。",
            "default_hashtags": "#不動產買賣找阿嘉\n#龍潭成交策略",
            "brokerage_name": "洺城開發企業社",
            "salesperson_license": "（108）登字第352260號",
            "broker_license": "（113）南市字第01004號",
        }
        for key, value in defaults.items():
            self.set_default_setting(conn, key, value)

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
            "missing_count": "INTEGER NOT NULL DEFAULT 0",
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

    # 連續幾次同步都沒看到才真的判定下架——避免網站單次抓取不完整就
    # 誤判一堆物件下架。見 TEST G/H（一次沒看到不下架、連續三次才下架）。
    OFFLINE_MISSING_THRESHOLD = 3

    def _mark_offline_properties(
        self,
        conn: sqlite3.Connection,
        source_id: int,
        seen_ids: list[int],
        sync_run_id: int | None,
    ) -> int:
        # 這次有看到的物件，下線倒數重新歸零（不管之前累積到第幾次）。
        if seen_ids:
            seen_placeholders = ", ".join("?" for _ in seen_ids)
            conn.execute(
                f"""
                UPDATE properties SET missing_count=0
                WHERE source_id=? AND id IN ({seen_placeholders})
                """,
                [source_id, *seen_ids],
            )

        placeholders = ", ".join("?" for _ in seen_ids) if seen_ids else ""
        where_not_seen = f"AND id NOT IN ({placeholders})" if placeholders else ""
        params: list[Any] = [source_id]
        params.extend(seen_ids)

        candidates = conn.execute(
            f"""
            SELECT id, missing_count FROM properties
            WHERE source_id=? AND status != 'offline' {where_not_seen}
            """,
            params,
        ).fetchall()

        active_total = conn.execute(
            "SELECT COUNT(*) FROM properties WHERE source_id=? AND status != 'offline'",
            (source_id,),
        ).fetchone()[0]

        # 安全判定：單次同步不應該把來源中大部分物件都判定「這次沒看到」，
        # 避免解析失敗或網站改版時，把一整批物件的下線倒數都往前推。
        if active_total > 0 and len(candidates) > max(3, active_total * 0.5):
            return 0

        offline_count = 0
        for row in candidates:
            new_missing = int(row["missing_count"] or 0) + 1
            if new_missing >= self.OFFLINE_MISSING_THRESHOLD:
                conn.execute(
                    """
                    UPDATE properties SET status='offline', missing_count=?,
                        updated_at=CURRENT_TIMESTAMP WHERE id=?
                    """,
                    (new_missing, row["id"]),
                )
                self._record_property_change(
                    conn, row["id"], "offline", "active", "offline", sync_run_id
                )
                offline_count += 1
            else:
                conn.execute(
                    "UPDATE properties SET missing_count=? WHERE id=?",
                    (new_missing, row["id"]),
                )

        return offline_count

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

    def recent_property_changes_map(self, days: int = 3) -> dict[int, dict[str, Any]]:
        """回傳 {property_id: 最重要的一筆最近異動}，物件中心用來顯示
        🆕新物件／↓價格異動／已異動 badge。優先順序：created > price_changed
        > content_changed（下架直接看 properties.status，不需要查這裡）。
        """
        priority = {"created": 3, "price_changed": 2, "content_changed": 1}
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM property_changes
                WHERE change_type IN ('created', 'price_changed', 'content_changed')
                  AND detected_at >= datetime('now', ?)
                ORDER BY detected_at DESC
                """,
                (f"-{days} days",),
            ).fetchall()

        result: dict[int, dict[str, Any]] = {}
        for row in rows:
            property_id = int(row["property_id"])
            change_type = row["change_type"]
            existing = result.get(property_id)
            if existing is None or priority.get(change_type, 0) > priority.get(
                existing["change_type"], 0
            ):
                result[property_id] = dict(row)
        return result

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

    @staticmethod
    def normalize_sync_source_url(url: str) -> str:
        """把網址正規化成方便比對重複的形式：scheme/host 轉小寫、去掉
        結尾斜線、去掉 fragment。刻意不動 query string 與 path 大小寫，
        避免把實際不同的來源誤判成同一個。
        """
        from urllib.parse import urlparse, urlunparse

        parsed = urlparse(url.strip())
        path = parsed.path.rstrip("/")
        return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", parsed.query, ""))

    def find_sync_source_by_url(self, url: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            return self._find_sync_source_by_url(conn, url)

    def _find_sync_source_by_url(
        self, conn: sqlite3.Connection, url: str
    ) -> dict[str, Any] | None:
        normalized = self.normalize_sync_source_url(url)
        rows = conn.execute("SELECT * FROM sync_sources").fetchall()
        for row in rows:
            if self.normalize_sync_source_url(str(row["url"])) == normalized:
                return dict(row)
        return None

    def save_sync_source(
        self, data: dict[str, Any], source_id: int | None = None
    ) -> int:
        name = str(data.get("name", "")).strip() or "未命名來源"
        source_type = str(data.get("source_type", "yungching_store")).strip() or "yungching_store"
        url = str(data.get("url", "")).strip()
        enabled = 1 if data.get("enabled", True) else 0
        auto_sync_enabled = 1 if data.get("auto_sync_enabled", False) else 0
        try:
            interval = int(data.get("sync_interval_minutes", 360) or 360)
        except (TypeError, ValueError):
            interval = 360
        interval = max(5, interval)

        if not url:
            raise ValueError("同步來源網址不可空白")

        with self.connect() as conn:
            if source_id is None:
                duplicate = self._find_sync_source_by_url(conn, url)
                if duplicate is not None:
                    raise DuplicateSyncSourceError(
                        existing_id=int(duplicate["id"]),
                        existing_name=str(duplicate["name"]),
                    )
                cur = conn.execute(
                    """
                    INSERT INTO sync_sources(
                        name, source_type, url, enabled, auto_sync_enabled, sync_interval_minutes
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (name, source_type, url, enabled, auto_sync_enabled, interval),
                )
                return int(cur.lastrowid)
            conn.execute(
                """
                UPDATE sync_sources SET name=?, source_type=?, url=?, enabled=?,
                    auto_sync_enabled=?, sync_interval_minutes=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (name, source_type, url, enabled, auto_sync_enabled, interval, source_id),
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

    # ---------------------------------------------------------------
    # Auto Sync Center：atomic claim / retry / 完成後排下一次
    # ---------------------------------------------------------------

    def list_due_sync_sources(self, limit: int = 10) -> list[dict[str, Any]]:
        now = now_local_str()
        sql = """
            SELECT * FROM sync_sources
            WHERE enabled=1 AND auto_sync_enabled=1 AND sync_status='idle'
              AND (next_sync_at='' OR next_sync_at<=?)
            ORDER BY CASE WHEN next_sync_at='' THEN 1 ELSE 0 END, next_sync_at ASC
            LIMIT ?
        """
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, (now, limit)).fetchall()]

    def claim_sync_source_for_sync(self, source_id: int, execution_token: str) -> bool:
        """Atomic claim：跟 schedules 的 claim_schedule_for_publish 同一個模式
        ——只有真的把 sync_status 從 idle 改成 syncing 的那次呼叫，rowcount
        才會是 1。手動按「立即同步」跟 Automation tick 同時打到同一個來源，
        只有一邊搶得到，這是防止同一來源重複同步的核心機制。

        syncing_started_at 用本機時間記錄 claim 的當下，是 stale-recovery
        判斷「這筆同步是不是卡住太久」唯一依據的欄位——不能用 updated_at
        （那欄位是 CURRENT_TIMESTAMP／UTC，跟這裡的本機時間基準不一致，
        混用會讓 stale 判斷差 8 小時）。
        """
        with self.connect() as conn:
            cur = conn.execute(
                """
                UPDATE sync_sources SET sync_status='syncing', execution_token=?,
                    syncing_started_at=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=? AND sync_status='idle'
                """,
                (execution_token, now_local_str(), source_id),
            )
            return cur.rowcount == 1

    def list_stale_syncing_sources(self, stale_minutes: int = 15) -> list[dict[str, Any]]:
        """Crash recovery 用：找出卡在 syncing 太久的來源——代表上次 claim
        之後，process 在同步完成前就被 crash/taskkill/關機/斷電 中斷，
        claim 沒有機會正常釋放。用 syncing_started_at（本機時間）判斷，
        還在合理時間內的（真的在正常同步中）不會被這裡動到，避免誤判
        造成同一來源被啟動第二次同步。
        """
        threshold = local_str_plus(None, minutes=-stale_minutes)
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM sync_sources
                WHERE sync_status='syncing' AND syncing_started_at != ''
                  AND syncing_started_at <= ?
                """,
                (threshold,),
            ).fetchall()
        return [dict(row) for row in rows]

    def recover_stale_sync_source(self, source_id: int) -> None:
        """對應的 orphaned sync_runs 一律標記 cancelled（不能假裝 success，
        也不知道實際進度到哪），並釋放 claim 讓下一次 tick 可以正常重新
        嘗試——不消耗 retry_count，因為這不是來源本身的錯。
        """
        now = now_local_str()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE sync_runs SET status='cancelled', finished_at=?,
                    error_message='Interrupted: HouseFlow terminated before sync completed.'
                WHERE source_id=? AND status='running'
                """,
                (now, source_id),
            )
            conn.execute(
                """
                UPDATE sync_sources SET sync_status='idle', execution_token='',
                    syncing_started_at='', updated_at=CURRENT_TIMESTAMP
                WHERE id=? AND sync_status='syncing'
                """,
                (source_id,),
            )

    def count_active_properties_for_source(self, source_id: int) -> int:
        with self.connect() as conn:
            return int(
                conn.execute(
                    "SELECT COUNT(*) FROM properties WHERE source_id=? AND status != 'offline'",
                    (source_id,),
                ).fetchone()[0]
            )

    def mark_sync_source_success(self, source_id: int) -> None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT sync_interval_minutes FROM sync_sources WHERE id=?", (source_id,)
            ).fetchone()
            interval = int(row["sync_interval_minutes"]) if row else 360
            now = now_local_str()
            next_sync = local_str_plus(now, minutes=interval)
            conn.execute(
                """
                UPDATE sync_sources SET sync_status='idle', last_status='success', last_error='',
                    last_sync_at=?, last_success_at=?, next_sync_at=?, retry_count=0,
                    next_retry_at='', execution_token='', syncing_started_at='',
                    sync_success_count=sync_success_count+1, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (now, now, next_sync, source_id),
            )

    def mark_sync_source_partial_or_suspicious(self, source_id: int, status: str, error_message: str) -> None:
        """partial/suspicious：這次有抓到結果、也寫進 DB 了（partial 是部分
        頁面失敗，suspicious 是抓到的數量疑似不完整所以沒有做下架判斷），
        不算失敗、不重試，只是照正常頻率排下一次，並把原因留在 last_error
        方便使用者在來源卡片上看到。
        """
        with self.connect() as conn:
            row = conn.execute(
                "SELECT sync_interval_minutes FROM sync_sources WHERE id=?", (source_id,)
            ).fetchone()
            interval = int(row["sync_interval_minutes"]) if row else 360
            now = now_local_str()
            next_sync = local_str_plus(now, minutes=interval)
            conn.execute(
                """
                UPDATE sync_sources SET sync_status='idle', last_status=?, last_error=?,
                    last_sync_at=?, next_sync_at=?, retry_count=0, next_retry_at='',
                    execution_token='', syncing_started_at='', updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (status, error_message, now, next_sync, source_id),
            )

    def mark_sync_source_retry_or_fail(
        self, source_id: int, error_message: str, max_retries: int = 3
    ) -> None:
        """明確失敗（例外、逾時、來源整體不可用）：前 max_retries 次用
        5/15/30 分鐘 backoff 重試；超過後標記 needs_review，不再無限重試，
        改回等下一個正常 sync_interval 再試一次。
        """
        backoff_minutes = (5, 15, 30)
        with self.connect() as conn:
            row = conn.execute(
                "SELECT retry_count, sync_interval_minutes FROM sync_sources WHERE id=?",
                (source_id,),
            ).fetchone()
            retry_count = (int(row["retry_count"] or 0) if row else 0) + 1
            interval = int(row["sync_interval_minutes"]) if row else 360
            now = now_local_str()

            if retry_count > max_retries:
                next_sync = local_str_plus(now, minutes=interval)
                conn.execute(
                    """
                    UPDATE sync_sources SET sync_status='idle', last_status='needs_review',
                        last_error=?, last_sync_at=?, last_failure_at=?, next_sync_at=?,
                        retry_count=0, next_retry_at='', execution_token='', syncing_started_at='',
                        sync_failure_count=sync_failure_count+1, updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (error_message, now, now, next_sync, source_id),
                )
            else:
                delay = backoff_minutes[min(retry_count - 1, len(backoff_minutes) - 1)]
                next_retry = local_str_plus(now, minutes=delay)
                conn.execute(
                    """
                    UPDATE sync_sources SET sync_status='idle', last_status='failed',
                        last_error=?, last_sync_at=?, last_failure_at=?, next_sync_at=?,
                        next_retry_at=?, retry_count=?, execution_token='', syncing_started_at='',
                        sync_failure_count=sync_failure_count+1, updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (error_message, now, now, next_retry, next_retry, retry_count, source_id),
                )

    def cleanup_old_sync_runs(self, retention_days: int = 30) -> int:
        """只清 sync_runs 歷史列，絕對不動 property_changes（未來分析可能
        還會用到，這輪明確不清）。
        """
        retention_days = max(1, int(retention_days))
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM sync_runs WHERE started_at <= datetime('now', ?)",
                (f"-{retention_days} days",),
            )
            return cur.rowcount

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
            today_changed = conn.execute(
                "SELECT COUNT(*) FROM property_changes WHERE change_type IN ('price_changed', 'content_changed') AND date(detected_at)=date('now', 'localtime')"
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
            auto_sync_sources = conn.execute(
                "SELECT COUNT(*) FROM sync_sources WHERE enabled=1 AND auto_sync_enabled=1"
            ).fetchone()[0]
            today_sync_runs = conn.execute(
                "SELECT COUNT(*) FROM sync_runs WHERE date(started_at, 'localtime')=date('now', 'localtime')"
            ).fetchone()[0]
            next_source = conn.execute(
                """
                SELECT next_sync_at FROM sync_sources
                WHERE enabled=1 AND auto_sync_enabled=1 AND next_sync_at != ''
                ORDER BY next_sync_at ASC LIMIT 1
                """
            ).fetchone()
            failing_sources = conn.execute(
                "SELECT COUNT(*) FROM sync_sources WHERE last_status IN ('failed', 'needs_review')"
            ).fetchone()[0]

        return {
            "last_sync_at": last_run["started_at"] if last_run else "",
            "last_sync_status": last_run["status"] if last_run else "",
            "today_new": today_new,
            "today_price_changed": today_price,
            "today_changed": today_changed,
            "today_offline": today_offline,
            "today_failed": today_failed_runs,
            "total_properties": total_properties,
            "auto_sync_sources": auto_sync_sources,
            "today_sync_runs": today_sync_runs,
            "next_sync_at": next_source["next_sync_at"] if next_source else "",
            "failing_sources": failing_sources,
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

    # ---------------------------------------------------------------
    # 排程發布中心（Schedule Center）
    # ---------------------------------------------------------------

    def create_schedule(self, data: dict[str, Any]) -> int:
        images_value = data.get("images", [])
        images = images_value if isinstance(images_value, str) else "\n".join(images_value)
        delete_after_days = data.get("delete_after_days")
        # DEV ONLY——見 _ensure_schedule_columns() 的說明，一般呼叫端不會
        # 傳這個 key，一定是 None。
        delete_after_minutes = data.get("delete_after_minutes")

        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO schedules(
                    property_id, platform, target, target_label, copy_text,
                    images, scheduled_at, status, batch_id, delete_after_days,
                    delete_after_minutes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data.get("property_id"),
                    str(data.get("platform", "facebook")).strip() or "facebook",
                    str(data.get("target", "")).strip(),
                    str(data.get("target_label", "")).strip(),
                    str(data.get("copy_text", "")).strip(),
                    images,
                    str(data.get("scheduled_at", "")).strip(),
                    str(data.get("status", "pending_review")).strip() or "pending_review",
                    str(data.get("batch_id", "")).strip(),
                    int(delete_after_days) if delete_after_days not in (None, "") else None,
                    int(delete_after_minutes) if delete_after_minutes not in (None, "") else None,
                ),
            )
            return int(cur.lastrowid)

    def get_schedule(self, schedule_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT s.*, p.title AS property_title, p.address AS property_address,
                       p.external_id AS property_external_id
                FROM schedules s
                LEFT JOIN properties p ON p.id = s.property_id
                WHERE s.id = ?
                """,
                (schedule_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_schedules(
        self,
        statuses: list[str] | None = None,
        search: str = "",
        only_today: bool = False,
        limit: int = 300,
        delete_statuses: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT s.*, p.title AS property_title, p.address AS property_address,
                   p.external_id AS property_external_id
            FROM schedules s
            LEFT JOIN properties p ON p.id = s.property_id
        """
        clauses: list[str] = []
        params: list[Any] = []

        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            clauses.append(f"s.status IN ({placeholders})")
            params.extend(statuses)

        if delete_statuses:
            placeholders = ", ".join("?" for _ in delete_statuses)
            clauses.append(f"s.delete_status IN ({placeholders})")
            params.extend(delete_statuses)

        if only_today:
            clauses.append("date(s.scheduled_at) = date('now', 'localtime')")

        if search:
            pattern = f"%{search}%"
            clauses.append(
                "(p.title LIKE ? OR p.address LIKE ? OR s.target_label LIKE ? OR s.copy_text LIKE ?)"
            )
            params.extend([pattern] * 4)

        if clauses:
            sql += " WHERE " + " AND ".join(clauses)

        sql += " ORDER BY CASE WHEN s.scheduled_at='' THEN 1 ELSE 0 END, s.scheduled_at, s.id DESC LIMIT ?"
        params.append(limit)

        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]

    def latest_schedule_by_property(self) -> dict[int, dict[str, Any]]:
        """每個物件最新（id 最大）的一筆排程摘要——物件中心用這個顯示
        「未排程／已排程／已發布／發布失敗」狀態，不必為了這個額外查詢
        整張 schedules table 的所有欄位。純唯讀，不影響任何 automation
        邏輯，只是給 UI 顯示用的投影。
        """
        sql = """
            SELECT s.property_id, s.status, s.scheduled_at, s.published_at,
                   s.delete_status, s.delete_at, s.error_message
            FROM schedules s
            INNER JOIN (
                SELECT property_id, MAX(id) AS max_id
                FROM schedules
                GROUP BY property_id
            ) latest ON latest.property_id = s.property_id AND latest.max_id = s.id
        """
        with self.connect() as conn:
            rows = conn.execute(sql).fetchall()
        return {int(row["property_id"]): dict(row) for row in rows if row["property_id"] is not None}

    def _update_schedule(self, schedule_id: int, **fields: Any) -> None:
        if not fields:
            return
        assignments = ", ".join(f"{key}=?" for key in fields)
        with self.connect() as conn:
            conn.execute(
                f"UPDATE schedules SET {assignments}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (*fields.values(), schedule_id),
            )

    def approve_schedule(self, schedule_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE schedules SET status='scheduled', approved_at=CURRENT_TIMESTAMP,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (schedule_id,),
            )

    def approve_all_pending_today(self) -> int:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id FROM schedules
                WHERE status='pending_review' AND date(scheduled_at) = date('now', 'localtime')
                """
            ).fetchall()
            ids = [int(row["id"]) for row in rows]
            for schedule_id in ids:
                conn.execute(
                    "UPDATE schedules SET status='scheduled', approved_at=CURRENT_TIMESTAMP, "
                    "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (schedule_id,),
                )
        return len(ids)

    def reject_schedule(self, schedule_id: int) -> None:
        """退回修改：回到草稿，讓使用者重新編輯後再送審。"""
        self._update_schedule(schedule_id, status="draft")

    def submit_draft(self, schedule_id: int, scheduled_at: str) -> None:
        """把草稿送出待檢核，需要指定發布時間。"""
        self._update_schedule(
            schedule_id,
            status="pending_review",
            scheduled_at=scheduled_at.strip(),
        )

    def cancel_schedule(self, schedule_id: int) -> None:
        self._update_schedule(schedule_id, status="cancelled")

    def delete_schedule(self, schedule_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM schedules WHERE id=?", (schedule_id,))

    def update_schedule_content(
        self,
        schedule_id: int,
        copy_text: str,
        images: list[str] | str,
        scheduled_at: str,
    ) -> None:
        images_value = images if isinstance(images, str) else "\n".join(images)
        self._update_schedule(
            schedule_id,
            copy_text=copy_text.strip(),
            images=images_value,
            scheduled_at=scheduled_at.strip(),
        )

    def update_schedule_time(self, schedule_id: int, scheduled_at: str) -> None:
        """只改預定發布時間，不動文案／圖片——排程中心「修改時間」用。"""
        self._update_schedule(schedule_id, scheduled_at=scheduled_at.strip())

    def mark_schedule_publishing(self, schedule_id: int) -> None:
        self._update_schedule(schedule_id, status="publishing")

    def mark_schedule_published(
        self, schedule_id: int, post_url: str = "", post_id: str = ""
    ) -> None:
        """標記發布成功。published_at 用本機時間（跟 scheduled_at 同一個
        基準），並且用這筆排程自己保存的 delete_after_days 規則，從
        「這次真正發布成功的時間」（不是原本排程時間）算出 delete_at ——
        手動「立即發布」跟 Automation Engine 自動發布都會呼叫這裡，
        自動刪文排程只需要在這一個地方算，兩條路徑都會拿到。
        """
        published_at = now_local_str()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT delete_after_days, delete_after_minutes FROM schedules WHERE id=?",
                (schedule_id,),
            ).fetchone()
            delete_after_days = row["delete_after_days"] if row else None
            delete_after_minutes = row["delete_after_minutes"] if row else None

            delete_at = ""
            delete_status = "not_scheduled"
            if delete_after_minutes is not None:
                # DEV ONLY 分鐘級倒數優先於天數——見 _ensure_schedule_columns()。
                delete_at = local_str_plus(published_at, minutes=int(delete_after_minutes))
                delete_status = "pending"
            elif delete_after_days is not None:
                delete_at = local_str_plus(published_at, days=int(delete_after_days))
                delete_status = "pending"

            conn.execute(
                """
                UPDATE schedules SET status='published', published_at=?,
                    post_url=?, post_id=?, error_message='', execution_token='',
                    delete_at=?, delete_status=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (published_at, post_url, post_id, delete_at, delete_status, schedule_id),
            )

    def mark_schedule_failed(self, schedule_id: int, error_message: str) -> None:
        """終端失敗（不會再自動重試，需要人工「重新執行」）。"""
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE schedules
                SET status='failed', error_message=?, retry_count=retry_count+1,
                    execution_token='', updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (error_message, schedule_id),
            )

    # ---------------------------------------------------------------
    # Automation Engine：atomic claim / retry / recovery（發布）
    # ---------------------------------------------------------------

    def list_due_publish_schedules(self, limit: int = 20) -> list[dict[str, Any]]:
        now = now_local_str()
        sql = """
            SELECT * FROM schedules
            WHERE status='scheduled'
              AND scheduled_at <= ?
              AND (next_retry_at = '' OR next_retry_at <= ?)
            ORDER BY scheduled_at ASC
            LIMIT ?
        """
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, (now, now, limit)).fetchall()]

    def claim_schedule_for_publish(self, schedule_id: int, execution_token: str) -> bool:
        """Atomic claim：只有真的把 status 從 scheduled 改成 publishing 的
        那一次呼叫，affected rowcount 才會是 1。任何併發呼叫（timer tick
        跟手動「立即檢查排程」同時觸發、engine 重複啟動…）都只有一個
        會搶到，這是防止重複發文的核心機制，不是靠 in-process 的鎖。
        """
        with self.connect() as conn:
            cur = conn.execute(
                """
                UPDATE schedules SET status='publishing', started_at=?,
                    execution_token=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=? AND status='scheduled'
                """,
                (now_local_str(), execution_token, schedule_id),
            )
            return cur.rowcount == 1

    def schedule_publish_retry(
        self, schedule_id: int, delay_kwargs: dict[str, float], error_message: str
    ) -> None:
        """發布失敗但明確可以重試：retry_count+1，回到 scheduled 狀態，
        設定 next_retry_at 讓 engine 之後才會再撿起來，不用 sleep()。
        """
        next_retry_at = local_str_plus(None, **delay_kwargs)
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE schedules
                SET status='scheduled', retry_count=retry_count+1,
                    next_retry_at=?, error_message=?, execution_token='',
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (next_retry_at, error_message, schedule_id),
            )

    def mark_schedule_needs_review(self, schedule_id: int, error_message: str) -> None:
        """結果不確定（例如送出後 timeout），不能自動重試以免重複發文。
        需要使用者確認「有沒有真的發出去」後才能繼續。
        """
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE schedules SET status='needs_review', error_message=?,
                    execution_token='', updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (error_message, schedule_id),
            )

    def resolve_needs_review(self, schedule_id: int, resolution: str) -> None:
        """使用者確認後的處理：
        resolution='already_published' -> 直接標記已發布（不重發）
        resolution='retry'             -> 回到 scheduled，讓 engine 重新嘗試
        resolution='cancel'            -> 取消這筆排程
        """
        with self.connect() as conn:
            if resolution == "already_published":
                conn.execute(
                    """
                    UPDATE schedules SET status='published', published_at=?,
                        error_message='', updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (now_local_str(), schedule_id),
                )
            elif resolution == "retry":
                conn.execute(
                    """
                    UPDATE schedules SET status='scheduled', next_retry_at='',
                        error_message='', updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (schedule_id,),
                )
            elif resolution == "cancel":
                conn.execute(
                    "UPDATE schedules SET status='cancelled', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (schedule_id,),
                )

    def list_stale_publishing(self, stale_minutes: int = 10) -> list[dict[str, Any]]:
        """Crash recovery 用：APP 啟動時找「卡在 publishing 太久」的排程。
        無法確認 Facebook 是否真的發布成功，一律標記 needs_review，
        絕對不會自動重發。
        """
        threshold = local_str_plus(None, minutes=-stale_minutes)
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM schedules WHERE status='publishing' AND started_at <= ? AND started_at != ''",
                (threshold,),
            ).fetchall()
        return [dict(row) for row in rows]

    # ---------------------------------------------------------------
    # Automation Engine：自動刪文
    # ---------------------------------------------------------------

    def list_due_delete_schedules(self, limit: int = 20) -> list[dict[str, Any]]:
        now = now_local_str()
        sql = """
            SELECT * FROM schedules
            WHERE delete_status='pending'
              AND delete_at != '' AND delete_at <= ?
              AND (delete_next_retry_at = '' OR delete_next_retry_at <= ?)
            ORDER BY delete_at ASC
            LIMIT ?
        """
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, (now, now, limit)).fetchall()]

    def claim_schedule_for_delete(self, schedule_id: int, execution_token: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                """
                UPDATE schedules SET delete_status='deleting', execution_token=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=? AND delete_status='pending'
                """,
                (execution_token, schedule_id),
            )
            return cur.rowcount == 1

    def mark_schedule_deleted(self, schedule_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE schedules SET delete_status='deleted', deleted_at=?,
                    execution_token='', updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (now_local_str(), schedule_id),
            )

    def schedule_delete_retry(
        self, schedule_id: int, delay_kwargs: dict[str, float], error_message: str
    ) -> None:
        next_retry_at = local_str_plus(None, **delay_kwargs)
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE schedules
                SET delete_status='pending', delete_attempt_count=delete_attempt_count+1,
                    delete_next_retry_at=?, error_message=?, execution_token='',
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (next_retry_at, error_message, schedule_id),
            )

    def mark_delete_failed_terminal(self, schedule_id: int, error_message: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE schedules
                SET delete_status='delete_failed', delete_attempt_count=delete_attempt_count+1,
                    error_message=?, execution_token='', updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (error_message, schedule_id),
            )

    def mark_delete_manual_required(self, schedule_id: int, reason: str = "") -> None:
        """沒有可靠的 remote_post_id/post_url，絕對不能猜、不能自動刪。"""
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE schedules SET delete_status='manual_required', error_message=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (reason, schedule_id),
            )

    def cancel_auto_delete(self, schedule_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE schedules SET delete_status='cancelled', delete_at='',
                    delete_after_days=NULL, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (schedule_id,),
            )

    def update_delete_rule(self, schedule_id: int, delete_after_days: int | None) -> None:
        """修改刪除時間（例如 15 天 -> 30 天）。只允許在還沒真的執行
        刪除以前調整；delete_at 依目前的 published_at 重新計算。
        """
        with self.connect() as conn:
            row = conn.execute(
                "SELECT published_at FROM schedules WHERE id=?", (schedule_id,)
            ).fetchone()
            published_at = row["published_at"] if row else ""

            if delete_after_days is None:
                conn.execute(
                    """
                    UPDATE schedules SET delete_after_days=NULL, delete_at='',
                        delete_status='not_scheduled', updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (schedule_id,),
                )
                return

            delete_at = local_str_plus(published_at, days=int(delete_after_days)) if published_at else ""
            delete_status = "pending" if published_at else "not_scheduled"
            conn.execute(
                """
                UPDATE schedules SET delete_after_days=?, delete_at=?, delete_status=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (delete_after_days, delete_at, delete_status, schedule_id),
            )

    # ---------------------------------------------------------------
    # Automation Engine：execution 記錄（audit trail）
    # ---------------------------------------------------------------

    def create_execution(
        self, schedule_id: int, execution_type: str, attempt_number: int, execution_token: str
    ) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO schedule_executions(
                    schedule_id, execution_type, attempt_number, execution_token, started_at, status
                ) VALUES (?, ?, ?, ?, ?, 'running')
                """,
                (schedule_id, execution_type, attempt_number, execution_token, now_local_str()),
            )
            return int(cur.lastrowid)

    def finish_execution(self, execution_id: int, status: str, error_message: str = "") -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE schedule_executions SET status=?, error_message=?, finished_at=?
                WHERE id=?
                """,
                (status, error_message, now_local_str(), execution_id),
            )

    def list_executions(self, schedule_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM schedule_executions WHERE schedule_id=? ORDER BY id",
                (schedule_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    # ---------------------------------------------------------------
    # Automation Engine：批次（同一次「加入排程」建立的多個 target）
    # ---------------------------------------------------------------

    def list_batch_schedules(self, batch_id: str) -> list[dict[str, Any]]:
        if not batch_id:
            return []
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM schedules WHERE batch_id=? ORDER BY id", (batch_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def today_automation_summary(self) -> dict[str, int]:
        with self.connect() as conn:
            def _count(where: str) -> int:
                return int(
                    conn.execute(f"SELECT COUNT(*) FROM schedules WHERE {where}").fetchone()[0]
                )

            today = "date('now', 'localtime')"
            return {
                "pending_review_today": _count(
                    f"status='pending_review' AND date(created_at, 'localtime') = {today}"
                ),
                "scheduled_today": _count(f"status='scheduled' AND date(scheduled_at) = {today}"),
                "published_today": _count(
                    f"status='published' AND date(published_at) = {today}"
                ),
                "failed_today": _count(
                    f"status IN ('failed','needs_review') AND date(updated_at, 'localtime') = {today}"
                ),
                "delete_pending_today": _count(
                    f"delete_status='pending' AND date(delete_at) = {today}"
                ),
                "deleted_today": _count(f"delete_status='deleted' AND date(deleted_at) = {today}"),
            }

    def cleanup_old_schedule_history(self, retention_days: int) -> int:
        """清除 HouseFlow 這邊「已經完全結束」且超過保留天數的排程歷史
        紀錄列——這跟 Facebook 貼文本身的自動刪除（delete_post()）是
        兩件事：這裡只刪 HouseFlow 資料庫裡的排程紀錄列，不會觸碰
        Facebook、也不會動到 property/sync_sources/CRM/settings/
        Facebook session/圖片。

        只有同時符合以下條件才會被清除：
        - status 是終態（published / failed / cancelled，draft、
          pending_review、scheduled、publishing、needs_review 永遠不會
          被清除，因為它們還是待處理的工作）
        - delete_status 不是 pending/deleting（代表這個 target 沒有還在
          等待或執行中的自動刪文工作）
        - updated_at 超過保留天數
        """
        retention_days = max(1, int(retention_days))
        with self.connect() as conn:
            cur = conn.execute(
                """
                DELETE FROM schedules
                WHERE status IN ('published', 'failed', 'cancelled')
                  AND delete_status NOT IN ('pending', 'deleting')
                  AND updated_at <= datetime('now', ?)
                """,
                (f"-{retention_days} days",),
            )
            return cur.rowcount

