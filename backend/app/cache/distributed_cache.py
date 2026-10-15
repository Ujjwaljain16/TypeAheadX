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
        self._timeout = settings.redis_timeout_seconds
        self._breaker_seconds = settings.redis_breaker_seconds
        
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
                port = int(port_str)
                name = f"redis-{chr(97 + port - 6379)}" if host == "localhost" and 6379 <= port <= 6381 else f"{host}:{port}"
                self._add_node(name, host, port)
            else:
                logger.error(f"Invalid node configuration: {node_str}")

    def _add_node(self, name: str, host: str, port: int) -> None:
        # Add physical node to the ring and create its client (never fails: connection is lazy)
        self.ring.add_node(name)
        self.nodes[name] = RedisNode(name=name, host=host, port=port, timeout=self._timeout,
                                     breaker_seconds=self._breaker_seconds)

    def _get_node_client(self, key: str) -> Optional[RedisNode]:
        position = self.ring.get_node(key)
        if not position:
            return None
        return self.nodes.get(position.physical_node)

    def _usable_node(self, key: str) -> Optional[RedisNode]:
        """The node owning ``key`` if it may be used right now; counts errors / breaker skips."""
        node = self._get_node_client(key)
        if node is None:
            CacheMetrics.record_error()
            return None
        if not node.allow():
            CacheMetrics.record_skip()
            return None
        return node

    def _get_text(self, key: str) -> Optional[str]:
        """GET with breaker/metrics accounting; returns the stored text or None (miss/error)."""
        node = self._usable_node(key)
        if node is None:
            return None

        try:
            result = node.client.get(key)
        except Exception as e:
            logger.error(f"Redis get error on {node.name} for {key}: {e}")
            node.record_failure()
            CacheMetrics.record_error()
            return None
        node.record_success()

        if result:
            CacheMetrics.record_hit()
            CacheMetrics.record_node_hit(node.name)
            return result
        CacheMetrics.record_miss()
        return None

    def get(self, key: str) -> Optional[Any]:
        text = self._get_text(key)
        if text is None:
            return None
        try:
            return json.loads(text)
        except ValueError:
            logger.error(f"Corrupt cache entry for {key}; treating as miss")
            CacheMetrics.record_error()
            return None

    def get_raw(self, key: str) -> Optional[str]:
        return self._get_text(key)

    def _set_text(self, key: str, text: str, ttl_seconds: int) -> None:
        node = self._usable_node(key)
        if node is None:
            return

        try:
            node.client.set(key, text, ex=ttl_seconds)
            node.record_success()
            CacheMetrics.record_set()
        except Exception as e:
            logger.error(f"Redis set error on {node.name} for {key}: {e}")
            node.record_failure()
            CacheMetrics.record_error()

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        try:
            text = json.dumps(value)
        except (TypeError, ValueError) as e:
            logger.error(f"Unserialisable cache value for {key}: {e}")
            CacheMetrics.record_error()
            return
        self._set_text(key, text, ttl_seconds)

    def set_raw(self, key: str, text: str, ttl_seconds: int) -> None:
        self._set_text(key, text, ttl_seconds)

    def delete(self, key: str) -> None:
        node = self._usable_node(key)
        if node is None:
            return

        try:
            node.client.delete(key)
            node.record_success()
            CacheMetrics.record_delete()
        except Exception as e:
            logger.error(f"Redis delete error on {node.name} for {key}: {e}")
            node.record_failure()
            CacheMetrics.record_error()

    def delete_many(self, keys) -> None:
        """Delete many keys with one round trip per owning node (instead of one per key)."""
        by_node: dict = {}
        for key in keys:
            node = self._get_node_client(key)
            if node is None:
                CacheMetrics.record_error()
                continue
            by_node.setdefault(node.name, (node, []))[1].append(key)
        for node, node_keys in by_node.values():
            if not node.allow():
                for _ in node_keys:
                    CacheMetrics.record_skip()
                continue
            try:
                # chunks of 100: measured 600 keys in ~2 ms, whereas a single 500-key DEL took ~95 ms on the
                # test platform (large request -> TCP ack stall via Docker Desktop's port proxy)
                for i in range(0, len(node_keys), 100):
                    node.client.delete(*node_keys[i:i + 100])
                node.record_success()
                CacheMetrics.record_delete(len(node_keys))
            except Exception as e:
                logger.error(f"Redis delete_many error on {node.name} ({len(node_keys)} keys): {e}")
                node.record_failure()
                CacheMetrics.record_error()

    def get_ttl(self, key: str) -> int:
        node = self._get_node_client(key)
        if not node or not node.allow():
            return -2

        try:
            ttl = node.client.ttl(key)
            node.record_success()
            return ttl
        except Exception as e:
            logger.error(f"Redis ttl error on {node.name} for {key}: {e}")
            node.record_failure()
            CacheMetrics.record_error()
            return -2

    def get_debug_info(self, key: str) -> dict:
        """Helper for /cache/debug endpoint to show ring routing details."""
        position = self.ring.get_node(key)
        if not position:
            return {"key": key, "provider": "distributed", "node": None, "hash": None, "virtual_node": None,
                    "exists": False, "ttl": -2}
            
        node = self.nodes.get(position.physical_node)
        status = "MISS"
        ttl = -2
        
        if node and node.allow():
            try:
                result = node.client.get(key)
                node.record_success()
                if result:
                    status = "HIT"
                    ttl = node.client.ttl(key)
            except Exception as e:
                status = "ERROR"
                node.record_failure()
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
