import asyncio
import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import auth, feed, internal, me, notifications, quiz, stack
from app.services.scheduler import run_daily

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

# Startup prefill outlives the lifespan hook, so it needs a strong reference.
_startup_tasks: set[asyncio.Task] = set()


async def _prefill_on_startup() -> None:
    from app.services.prefill import prefill_all_categories

    try:
        result = await prefill_all_categories()
        logger.info("startup prefill: %s", result)
    except Exception:
        logger.exception("startup prefill failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.ENABLE_SCHEDULER:
        scheduler.add_job(run_daily, "cron", hour=6, minute=0)
        scheduler.start()
        logger.info("scheduler started (daily 06:00 UTC)")
    else:
        logger.info("scheduler disabled; use POST /internal/run-daily")

    # Fired without awaiting so a cold knowledgebase never delays boot.
    if settings.PREFILL_ON_STARTUP:
        task = asyncio.create_task(_prefill_on_startup())
        _startup_tasks.add(task)
        task.add_done_callback(_startup_tasks.discard)

    yield
    if settings.ENABLE_SCHEDULER:
        scheduler.shutdown()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(feed.router)
app.include_router(internal.router)
app.include_router(me.router)
app.include_router(notifications.router)
app.include_router(quiz.router)
app.include_router(stack.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
