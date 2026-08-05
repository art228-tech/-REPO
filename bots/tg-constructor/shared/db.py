"""
Common DB helper utilities.
"""
from contextlib import asynccontextmanager
from shared.models import async_session


@asynccontextmanager
async def db():
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
