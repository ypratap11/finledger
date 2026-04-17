from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from finledger.config import settings


def _async_url(url: str) -> str:
    return url.replace("postgresql://", "postgresql+asyncpg://")


def _sync_url(url: str) -> str:
    return url.replace("postgresql://", "postgresql+psycopg://").replace("postgresql+asyncpg://", "postgresql+psycopg://")


engine = create_async_engine(_async_url(settings.database_url), pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

sync_engine = create_engine(_sync_url(settings.database_url), pool_pre_ping=True)
SyncSessionLocal = sessionmaker(sync_engine, expire_on_commit=False)
