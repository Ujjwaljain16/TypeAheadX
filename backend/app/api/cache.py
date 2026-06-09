from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from typing import Optional, Dict
import os

from ..cache.factory import CacheFactory
from ..cache.metrics import CacheMetrics
from ..database.config import get_settings

router = APIRouter(prefix="/cache", tags=["cache"])

class CacheDebugResponse(BaseModel):
    prefix: str
    key: str
    exists: bool
    ttl_seconds: int
    provider: str
    node: Optional[str] = None
    hash: Optional[int] = None
    virtual_node: Optional[str] = None

class CacheMetricsResponse(BaseModel):
    provider: str
    hits: int
    misses: int
    sets: int
    deletes: int
    errors: int
    hit_rate: float
    node_hits: Dict[str, int] = {}

@router.get("/debug", response_model=CacheDebugResponse)
def cache_debug(prefix: str = Query(..., description="Prefix to check in cache")):
    cache = CacheFactory.get_cache()
    key = f"suggestion:{prefix}"
    provider = get_settings().cache_provider
    
    # If using distributed cache, we have rich debug info
    if hasattr(cache, "get_debug_info"):
        debug_info = cache.get_debug_info(key)
        return CacheDebugResponse(
            prefix=prefix,
            key=debug_info["key"],
            exists=debug_info["exists"],
            ttl_seconds=debug_info["ttl"],
            provider=debug_info["provider"],
            node=debug_info["node"],
            hash=debug_info["hash"],
            virtual_node=debug_info["virtual_node"]
        )
    else:
        # Fallback for redis or memory cache
        ttl = cache.get_ttl(key)
        exists = ttl != -2
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
