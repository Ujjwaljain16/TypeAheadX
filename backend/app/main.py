from __future__ import annotations
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)


from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.datastructures import MutableHeaders
from sqlalchemy.exc import SQLAlchemyError

from .api.suggestions import router as suggestions_router, build_service, get_repository, get_guard
from .api.cache import router as cache_router
from .api.search import router as search_router, _metrics_payload
from .cache.factory import CacheFactory
from .cache.metrics import CacheMetrics
from .database.config import get_settings
from .database.guard import DatabaseUnavailable
from .write_buffer.batch_worker import batch_worker
from .write_buffer.buffer import write_buffer
import asyncio
import string

logger = logging.getLogger(__name__)


def _warm_up_sync() -> None:
    service = build_service(get_settings())
    for char in string.ascii_lowercase:
        try:
            service.suggest(char)
        except Exception as e:
            logger.error(f"Failed to warm up cache for {char}: {e}")


async def warm_up_cache() -> None:
    logger.info("Warming up cache for A-Z prefixes...")
    # the repository/cache calls are synchronous, so run them off the event loop
    await asyncio.to_thread(_warm_up_sync)
    logger.info("Cache warmup complete.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    write_buffer.max_unique = settings.write_buffer_max_unique
    logger.info("Initializing Cache...")
    CacheFactory.get_cache()
    logger.info("Starting Batch Worker...")
    batch_worker.start()
    warm_task = asyncio.create_task(warm_up_cache())  # keep a reference so it is not GC'd mid-flight
    try:
        yield
    finally:
        warm_task.cancel()
        logger.info("Stopping Batch Worker...")
        await asyncio.to_thread(batch_worker.stop)  # includes the final flush (may block on the DB)


app = FastAPI(title="TypeAheadX", version="1.0.0", lifespan=lifespan)

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _settings.cors_origins.split(",") if o.strip()],
    allow_credentials=False,  # no cookies/credentials are used; "*" + credentials is invalid per the CORS spec
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(SQLAlchemyError)
async def database_unavailable(_: Request, exc: SQLAlchemyError):
    # includes connection-pool exhaustion (sqlalchemy.exc.TimeoutError) and lost connections
    logger.error("Database error: %s", type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "database temporarily unavailable"},
                        headers={"Retry-After": "1"})

@app.exception_handler(DatabaseUnavailable)
async def database_guard_rejected(_: Request, exc: DatabaseUnavailable):
    # timeout / saturated / circuit open: fail fast so request threads stay free for cache hits
    return JSONResponse(status_code=503, content={"detail": "database temporarily unavailable"},
                        headers={"Retry-After": "2"})

# Include routers
app.include_router(suggestions_router, tags=["Suggestions"])
app.include_router(cache_router, tags=["Cache"])
app.include_router(search_router, tags=["Search"])

@app.get("/health")
def health():
    return {"status": "healthy", "service": "typeaheadx-api", "phase": "phase-5"}


@app.get("/ready", tags=["Health"])
def ready():
    """Readiness: the database (the source of truth) must answer. Cache problems only degrade performance."""
    try:
        get_repository().ping()
    except Exception as exc:
        logger.error("readiness check failed: %s", type(exc).__name__)
        return JSONResponse(status_code=503, content={"status": "not_ready", "database": "unreachable"})
    return {"status": "ready"}

@app.get("/metrics", tags=["Metrics"])
async def unified_metrics():
    cache_data = CacheMetrics.get_metrics()
    return {
        "cache": cache_data,
        "write_buffer": _metrics_payload(),
        "database_guard": get_guard().stats(),
    }



class BodyLimitMiddleware:
    """Rejects request bodies above ``max_bytes`` with 413 without buffering them (checks the
    Content-Length header and also counts streamed/chunked bodies)."""

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return
        state = {"rejected": False, "started": False}
        response = JSONResponse(status_code=413, content={"detail": "request body too large"})

        async def reject():
            if not state["rejected"] and not state["started"]:
                state["rejected"] = True
                await response(scope, receive, send)

        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            await reject()
            return

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    await reject()
                    return {"type": "http.disconnect"}      # tell the application to stop reading
            return message

        async def tracking_send(message):
            if state["rejected"]:
                return                                       # 413 already sent; drop whatever the app emits now
            if message["type"] == "http.response.start":
                state["started"] = True
            await send(message)

        await self.app(scope, limited_receive, tracking_send)


class TimingMiddleware:
    """Adds X-Response-Time-ms. Implemented as a plain ASGI middleware: Starlette's
    BaseHTTPMiddleware (the previous implementation) wraps every request in an extra task + memory
    stream, which showed up in the CPU profile of the cache-hit path."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()

        async def send_with_timing(message):
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["X-Response-Time-ms"] = f"{(time.perf_counter() - start) * 1000.0:.2f}"
            await send(message)

        await self.app(scope, receive, send_with_timing)


app.add_middleware(BodyLimitMiddleware, max_bytes=_settings.max_request_bytes)
app.add_middleware(TimingMiddleware)  # added last => outermost, as the former @app.middleware("http") was
