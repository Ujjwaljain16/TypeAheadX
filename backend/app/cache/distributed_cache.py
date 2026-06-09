import json
import logging
from typing import Optional, Any

from app.database.config import get_settings
from .base import CacheInterface
from .metrics import CacheMetrics
from .consistent_hash_ring import ConsistentHashRing
from .redis_node import RedisNode

logger = logging.getLogger(__name__)

class DistributedCache(CacheInterface):
    def __init__(self):
        settings = get_settings()
        
        # Determine virtual nodes
        virtual_nodes = getattr(settings, "virtual_nodes", 150)
        
        self.ring = ConsistentHashRing(virtual_nodes=virtual_nodes)
        self.nodes = {}
        
        # Expected format: "redis-a:6379,redis-b:6380,redis-c:6381"
        nodes_config = getattr(settings, "redis_nodes", "localhost:6379,localhost:6380,localhost:6381")
        if not nodes_config:
            logger.warning("REDIS_NODES is empty. DistributedCache will operate with 0 nodes.")
            return

        for node_str in nodes_config.split(","):
            node_str = node_str.strip()
            if not node_str:
                continue
                
            parts = node_str.split(":")
            if len(parts) == 2:
                host, port_str = parts
                name = host # Simplify name to host for now, or could use host:port
                port = int(port_str)
                
                # Add physical node to the ring
                self.ring.add_node(name)
                
                # Create Redis client abstraction
                self.nodes[name] = RedisNode(name=name, host=host, port=port)
            else:
                logger.error(f"Invalid node configuration: {node_str}")

    def _get_node_client(self, key: str) -> Optional[RedisNode]:
        position = self.ring.get_node(key)
        if not position:
            return None
        return self.nodes.get(position.physical_node)

    def get(self, key: str) -> Optional[Any]:
        node = self._get_node_client(key)
        if not node or not node.client:
            CacheMetrics.record_error()
            return None

        try:
            result = node.client.get(key)
            if result:
                CacheMetrics.record_hit()
                CacheMetrics.record_node_hit(node.name)
                return json.loads(result)
            CacheMetrics.record_miss()
            return None
        except Exception as e:
            logger.error(f"Redis get error on {node.name} for {key}: {e}")
            CacheMetrics.record_error()
            return None

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        node = self._get_node_client(key)
        if not node or not node.client:
            CacheMetrics.record_error()
            return

        try:
            serialized = json.dumps(value)
            node.client.setex(key, ttl_seconds, serialized)
            CacheMetrics.record_set()
        except Exception as e:
            logger.error(f"Redis set error on {node.name} for {key}: {e}")
            CacheMetrics.record_error()

    def delete(self, key: str) -> None:
        node = self._get_node_client(key)
        if not node or not node.client:
            CacheMetrics.record_error()
            return

        try:
            node.client.delete(key)
            CacheMetrics.record_delete()
        except Exception as e:
            logger.error(f"Redis delete error on {node.name} for {key}: {e}")
            CacheMetrics.record_error()

    def get_ttl(self, key: str) -> int:
        node = self._get_node_client(key)
        if not node or not node.client:
            return -2

        try:
            return node.client.ttl(key)
        except Exception as e:
            logger.error(f"Redis ttl error on {node.name} for {key}: {e}")
            CacheMetrics.record_error()
            return -2

    def get_debug_info(self, key: str) -> dict:
        """Helper for /cache/debug endpoint to show ring routing details."""
        position = self.ring.get_node(key)
        if not position:
            return {"error": "No nodes available in hash ring"}
            
        node = self.nodes.get(position.physical_node)
        status = "MISS"
        ttl = -2
        
        if node and node.client:
            try:
                result = node.client.get(key)
                if result:
                    status = "HIT"
                    ttl = node.client.ttl(key)
            except Exception as e:
                status = "ERROR"
                logger.error(f"Debug info error: {e}")
                
        return {
            "key": key,
            "provider": "distributed",
            "node": position.physical_node,
            "hash": position.hash_value,
            "virtual_node": position.virtual_node,
            "exists": status == "HIT",
            "ttl": ttl
        }
