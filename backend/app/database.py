from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings


settings = get_settings()

database_url = settings.database_url

if database_url.startswith("postgresql://"):
    database_url = database_url.replace(
        "postgresql://",
        "postgresql+asyncpg://",
        1,
    )

engine = create_async_engine(
    database_url,
    pool_pre_ping=True,
)

SessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_session():
    async with SessionLocal() as session:
        yield session