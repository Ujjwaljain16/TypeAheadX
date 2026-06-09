import os
import logging
from .base import CacheInterface
from .memory_cache import InMemoryCache
from .redis_cache import RedisCache

logger = logging.getLogger(__name__)

class CacheFactory:
    _instance: CacheInterface = None

    @classmethod
    def get_cache(cls) -> CacheInterface:
        if cls._instance is not None:
            return cls._instance

        from ..database.config import get_settings
        
        provider = get_settings().cache_provider.lower()
        
        if provider == "redis":
            logger.info("Initializing RedisCache")
            cls._instance = RedisCache()
        else:
            logger.info("Initializing InMemoryCache")
            cls._instance = InMemoryCache()
            
        return cls._instance
