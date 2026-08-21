import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from .api import router as api_router
from .bot import bot, configure_bot, dp
from .database import engine
from .models import Base
from .services import dispatch_waiting_jobs

async def run_migrations() -> None:
    async with engine.begin() as conn:
        # Новый статус заявки.
        await conn.execute(
            text("""
                ALTER TYPE job_status
                ADD VALUE IF NOT EXISTS 'AWAITING_CALL'
            """)
        )

        # Комментарий к заявке.
        await conn.execute(
            text("""
                ALTER TABLE jobs
                ADD COLUMN IF NOT EXISTS comment_text TEXT
            """)
        )

        await conn.execute(
            text("""
                ALTER TABLE jobs
                ADD COLUMN IF NOT EXISTS comment_created_at TIMESTAMPTZ
            """)
        )

        await conn.execute(
            text("""
                ALTER TABLE jobs
                ADD COLUMN IF NOT EXISTS comment_updated_at TIMESTAMPTZ
            """)
        )

async def dispatcher_loop() -> None:
    while True:
        await dispatch_waiting_jobs(bot)
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await run_migrations()
    await configure_bot()
    polling_task = asyncio.create_task(dp.start_polling(bot, handle_signals=False))
    delivery_task = asyncio.create_task(dispatcher_loop())
    yield
    for task in (polling_task, delivery_task):
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    await bot.session.close()
    await engine.dispose()


app = FastAPI(title="Telegram Orders MiniApp", lifespan=lifespan)
app.include_router(api_router)

STATIC = Path("/app/static")
if STATIC.exists():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/{path:path}", include_in_schema=False)
async def frontend(path: str):
    file = STATIC / path
    if path and file.exists() and file.is_file():
        return FileResponse(file)
    return FileResponse(STATIC / "index.html")
