from typing import AsyncGenerator
from pathlib import Path
from sqlalchemy import Column, String, Boolean
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from fastapi import Depends
from fastapi_users.db import SQLAlchemyBaseUserTableUUID, SQLAlchemyUserDatabase

# DB at project root (parent of 'core')
BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = (BASE_DIR / "data" / "auth.db").resolve()
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

engine = create_async_engine(DATABASE_URL)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(SQLAlchemyBaseUserTableUUID, Base):
    full_name = Column(String(255), nullable=True)
    # fastapi-users adds: id, email, hashed_password, is_active, is_superuser, is_verified


async def create_db_and_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


async def get_user_db(session: AsyncSession = Depends(get_async_session)):
    yield SQLAlchemyUserDatabase(session, User)


async def init_db_async():
    await create_db_and_tables()


def init_db():
    # Sync wrapper for backward compatibility or scripts if needed
    import asyncio
    try:
        asyncio.run(create_db_and_tables())
    except RuntimeError:
        # Event loop already running, this function should not be called from async context
        pass

if __name__ == "__main__":
    init_db()
