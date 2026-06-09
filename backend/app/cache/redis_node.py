import redis
import logging

logger = logging.getLogger(__name__)

class RedisNode:
    def __init__(self, name: str, host: str, port: int):
        self.name = name
        self.host = host
        self.port = port
        
        # Consistent with Phase 3 Redis settings
        try:
            self.client = redis.Redis(
                host=host,
                port=port,
                decode_responses=True,
                socket_timeout=1,
                socket_connect_timeout=1,
                max_connections=50
            )
            self.client.ping()
            logger.info(f"Connected to Redis node {name} at {host}:{port}")
        except Exception as e:
            logger.error(f"Failed to connect to Redis node {name} at {host}:{port}: {e}")
            # Graceful degradation - mark as disconnected but don't crash
            self.client = None
