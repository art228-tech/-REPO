"""Сборка выгрузок: фильтры, имена файлов, вызов нужного форматтера."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tgparser.db.models import Lead
from tgparser.db.settings_store import ScanSettings
from tgparser.export.exporters import ExportResult, to_csv, to_json, to_tags, to_xlsx

FORMATS = ("csv", "xlsx", "json", "txt")


@dataclass(slots=True)
class ExportFilter:
    only_with_username: bool = False
    only_without_username: bool = False
    status: str | None = None
    chat_id: int | None = None
    source: str | None = None

    def describe(self) -> str:
        parts = []
        if self.only_with_username:
            parts.append("только с тегом")
        if self.only_without_username:
            parts.append("только без тега")
        if self.status:
            parts.append(f"статус {self.status}")
        if self.source:
            parts.append(f"источник {self.source}")
        if self.chat_id:
            parts.append(f"чат {self.chat_id}")
        return ", ".join(parts) if parts else "без фильтров"


async def fetch_leads(session: AsyncSession, flt: ExportFilter | None = None) -> list[Lead]:
    query = select(Lead).order_by(Lead.id)
    if flt is not None:
        if flt.only_with_username:
            query = query.where(Lead.username.is_not(None))
        if flt.only_without_username:
            query = query.where(Lead.username.is_(None))
        if flt.status:
            query = query.where(Lead.status == flt.status)
        if flt.chat_id is not None:
            query = query.where(Lead.chat_id == flt.chat_id)
        if flt.source:
            query = query.where(Lead.source == flt.source)
    rows = await session.scalars(query)
    return list(rows)


def build_filename(fmt: str, now: datetime | None = None) -> str:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
    return f"leads-{stamp}.{fmt}"


async def export(
    session: AsyncSession,
    fmt: str,
    export_dir: Path,
    settings: ScanSettings,
    flt: ExportFilter | None = None,
) -> ExportResult:
    if fmt not in FORMATS:
        raise ValueError(f"Неизвестный формат: {fmt}. Доступны: {', '.join(FORMATS)}")

    leads = await fetch_leads(session, flt)
    path = export_dir / build_filename(fmt)

    if fmt == "csv":
        return to_csv(leads, path, delimiter=settings.csv_delimiter, bom=settings.csv_bom)
    if fmt == "xlsx":
        return to_xlsx(leads, path)
    if fmt == "json":
        return to_json(leads, path)
    return to_tags(leads, path)
