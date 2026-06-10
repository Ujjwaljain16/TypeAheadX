from __future__ import annotations
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)


from fastapi import FastAPI
from fastapi.requests import Request
from fastapi.middleware.cors import CORSMiddleware

from .api.suggestions import router as suggestions_router
from .api.cache import router as cache_router
from .api.search import router as search_router
from .cache.factory import CacheFactory
from .cache.metrics import CacheMetrics
from .write_buffer.batch_worker import batch_worker
from .write_buffer.metrics import write_metrics
from .write_buffer.buffer import write_buffer
from .services.suggestion_service import SuggestionService
import asyncio
import string
from fastapi import Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

app = FastAPI(title="TypeAheadX", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def warm_up_cache():
    logger.info("Warming up cache for A-Z prefixes...")
    from .repositories.query_repository import QueryRepository
    from .services.suggestion_service import SuggestionService
    from .cache.factory import CacheFactory
    
    repository = QueryRepository()
    cache = CacheFactory.get_cache()
    service = SuggestionService(repository, cache)
    for char in string.ascii_lowercase:
        try:
            # We must use asyncio.to_thread because the underlying db call is synchronous
            await asyncio.to_thread(service.get_suggestions, char)
        except Exception as e:
            logger.error(f"Failed to warm up cache for {char}: {e}")
    logger.info("Cache warmup complete.")

@app.on_event("startup")
def on_startup():
    logger.info("Initializing Cache...")
    CacheFactory.get_cache()
    logger.info("Starting Batch Worker...")
    batch_worker.start()
    asyncio.create_task(warm_up_cache())

@app.on_event("shutdown")
def on_shutdown():
    logger.info("Stopping Batch Worker...")
    batch_worker.stop()

# Include routers
app.include_router(suggestions_router, tags=["Suggestions"])
app.include_router(cache_router, tags=["Cache"])
app.include_router(search_router, tags=["Search"])

@app.get("/health")
def health():
    return {"status": "healthy", "service": "typeaheadx-api", "phase": "phase-5"}

@app.get("/metrics", tags=["Metrics"])
async def unified_metrics():
    cache_data = CacheMetrics.get_metrics()
    write_snapshot = write_metrics.get_snapshot()
    
    return {
        "cache": cache_data,
        "write_buffer": {
            "searches_received": write_snapshot.searches_received,
            "flushes_executed": write_snapshot.flushes_executed,
            "db_writes_executed": write_snapshot.db_writes_executed,
            "db_writes_avoided": write_snapshot.db_writes_avoided,
            "write_reduction_percent": round(write_snapshot.write_reduction_percent, 2),
            "buffer_current_size": write_buffer.get_size()
        }
    }



@app.middleware("http")
async def add_timing_header(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    total_ms = (time.perf_counter() - start) * 1000.0
    response.headers["X-Response-Time-ms"] = f"{total_ms:.2f}"
    return response
