from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
import os

from ..cache.factory import CacheFactory
from ..cache.metrics import CacheMetrics

router = APIRouter(prefix="/cache", tags=["cache"])

class CacheDebugResponse(BaseModel):
    prefix: str
    key: str
    exists: bool
    ttl_seconds: int
    provider: str

class CacheMetricsResponse(BaseModel):
    provider: str
    hits: int
    misses: int
    sets: int
    deletes: int
    errors: int
    hit_rate: float

from ..database.config import get_settings

@router.get("/debug", response_model=CacheDebugResponse)
def cache_debug(prefix: str = Query(..., description="Prefix to check in cache")):
    cache = CacheFactory.get_cache()
    key = f"suggestion:{prefix}"
    
    # We don't want to increment metrics on debug endpoints, so we just check ttl
    ttl = cache.get_ttl(key)
    exists = ttl != -2
    
    provider = get_settings().cache_provider
    
    return CacheDebugResponse(
        prefix=prefix,
        key=key,
        exists=exists,
        ttl_seconds=ttl if exists else 0,
        provider=provider
    )

@router.get("/metrics", response_model=CacheMetricsResponse)
def cache_metrics():
    metrics = CacheMetrics.get_metrics()
    provider = get_settings().cache_provider
    
    return CacheMetricsResponse(
        provider=provider,
        **metrics
    )
