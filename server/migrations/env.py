"""Alembic migration 環境（2026-09-23 Phase 3A）。

刻意讓 Alembic 讀跟其他地方完全同一個 DATABASE_URL 來源
（server.app.config.get_settings()，也就是環境變數
HOUSEFLOW_LICENSE_DB_URL），不用 alembic.ini 裡另外寫死一份連線字串
——只有一個地方需要設定資料庫要接去哪裡，不會有「app 連的是這個
DB，migration 跑到另一個 DB」的風險。
"""
from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from server.app.config import get_settings  # noqa: E402
from server.app.models import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# 只有在還沒被明確設定過（呼叫端沒有主動指定要連哪個資料庫，例如直接
# 從命令列跑 `alembic upgrade head`）時，才用 get_settings() 的值當
# 預設——如果呼叫端（例如 server/app/database.py 的
# run_migrations(database_url=...)）已經明確設定過 sqlalchemy.url，
# 這裡不能覆蓋掉它，否則呼叫端指定的資料庫會被忽略。
_placeholder_url = "driver://user:pass@localhost/dbname"
_current_url = config.get_main_option("sqlalchemy.url")
if not _current_url or _current_url == _placeholder_url:
    config.set_main_option("sqlalchemy.url", get_settings().database_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
