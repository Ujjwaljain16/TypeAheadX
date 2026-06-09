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
        
        provider_name = get_settings().cache_provider.lower()
        
        if provider_name == "redis":
            from .redis_cache import RedisCache
            logger.info("CacheFactory: Using Redis cache")
            cls._instance = RedisCache()
        elif provider_name == "distributed":
            from .distributed_cache import DistributedCache
            logger.info("CacheFactory: Using Distributed Redis cache")
            cls._instance = DistributedCache()
        else:
            logger.warning(f"CacheFactory: Unknown provider '{provider_name}', falling back to InMemoryCache")
            cls._instance = InMemoryCache()
            
        return cls._instance
