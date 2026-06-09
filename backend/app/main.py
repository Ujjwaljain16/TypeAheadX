from __future__ import annotations
import time
import logging

from fastapi import FastAPI
from fastapi.requests import Request
from fastapi.middleware.cors import CORSMiddleware

from .api.suggestions import router as suggestions_router
from .api.cache import router as cache_router
from .api.search import router as search_router
from .cache.factory import CacheFactory
from .write_buffer.batch_worker import batch_worker

logger = logging.getLogger(__name__)

app = FastAPI(title="TypeAheadX", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def on_startup():
    logger.info("Initializing Cache...")
    CacheFactory.get_cache()
    logger.info("Starting Batch Worker...")
    batch_worker.start()

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

@app.middleware("http")
async def add_timing_header(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    total_ms = (time.perf_counter() - start) * 1000.0
    response.headers["X-Response-Time-ms"] = f"{total_ms:.2f}"
    return response
