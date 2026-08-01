"""Подключение к БД."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tgparser.db.models import Base

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, url: str, echo: bool = False) -> None:
        self._engine: AsyncEngine = create_async_engine(url, echo=echo, future=True)
        self._sessionmaker = async_sessionmaker(
            self._engine, expire_on_commit=False, class_=AsyncSession
        )

    async def create_all(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def migrate(self) -> list[str]:
        """Дописать столбцы, появившиеся в моделях после создания базы.

        ``create_all`` создаёт только отсутствующие таблицы и молча
        игнорирует новые столбцы в существующих: запросы потом падают на
        «no such column». Полноценный инструмент миграций здесь избыточен, а
        добавления столбцов SQLite умеет сам.
        """
        added: list[str] = []
        async with self._engine.begin() as conn:
            for table in Base.metadata.sorted_tables:
                existing = await conn.run_sync(
                    lambda sync_conn, name=table.name: {
                        row[1]
                        for row in sync_conn.exec_driver_sql(f"PRAGMA table_info({name})")
                    }
                )
                if not existing:
                    # Таблицы ещё нет — её создаст create_all.
                    continue
                for column in table.columns:
                    if column.name in existing:
                        continue
                    clause = self._add_column_sql(table.name, column)
                    if clause is None:
                        logger.warning(
                            "Столбец %s.%s нельзя добавить автоматически",
                            table.name,
                            column.name,
                        )
                        continue
                    await conn.exec_driver_sql(clause)
                    added.append(f"{table.name}.{column.name}")
                    logger.info("Добавлен столбец %s.%s", table.name, column.name)
        return added

    def _add_column_sql(self, table: str, column: Any) -> str | None:
        type_sql = column.type.compile(dialect=self._engine.dialect)
        default = getattr(column.default, "arg", None) if column.default else None

        if column.nullable:
            tail = f" DEFAULT {self._literal(default)}" if default is not None else ""
            return f"ALTER TABLE {table} ADD COLUMN {column.name} {type_sql}{tail}"

        if default is None or callable(default):
            # SQLite не примет NOT NULL без значения для существующих строк.
            return None
        return (
            f"ALTER TABLE {table} ADD COLUMN {column.name} {type_sql} "
            f"NOT NULL DEFAULT {self._literal(default)}"
        )

    @staticmethod
    def _literal(value: Any) -> str:
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, (int, float)):
            return str(value)
        return "'" + str(value).replace("'", "''") + "'"

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self._sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def dispose(self) -> None:
        await self._engine.dispose()
