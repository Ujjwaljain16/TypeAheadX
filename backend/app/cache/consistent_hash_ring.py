import hashlib
import bisect
from dataclasses import dataclass
from typing import Dict, List, Optional

@dataclass
class RingPosition:
    hash_value: int
    physical_node: str
    virtual_node: str

class ConsistentHashRing:
    def __init__(self, virtual_nodes: int = 150):
        self.virtual_nodes = virtual_nodes
        self.ring: List[int] = []  # Sorted list of hash values
        self.positions: Dict[int, RingPosition] = {}  # hash -> RingPosition
        self.nodes: set[str] = set()

    def _hash(self, key: str) -> int:
        """
        MD5 hashing provides deterministic, uniform distribution across 128 bits.
        Converted to integer for fast ring traversal via bisect.
        """
        return int(hashlib.md5(key.encode()).hexdigest(), 16)

    def add_node(self, physical_node: str):
        if physical_node in self.nodes:
            return
        
        self.nodes.add(physical_node)
        for i in range(self.virtual_nodes):
            virtual_node = f"{physical_node}_replica_{i}"
            h = self._hash(virtual_node)
            
            # Handle potential hash collisions (very rare with 128-bit MD5)
            while h in self.positions:
                h += 1
                
            bisect.insort(self.ring, h)
            self.positions[h] = RingPosition(
                hash_value=h,
                physical_node=physical_node,
                virtual_node=virtual_node
            )

    def remove_node(self, physical_node: str):
        if physical_node not in self.nodes:
            return
            
        self.nodes.remove(physical_node)
        for i in range(self.virtual_nodes):
            virtual_node = f"{physical_node}_replica_{i}"
            h = self._hash(virtual_node)
            
            # Since we handle collisions by h+=1, we might need to search
            # But practically we can just rebuild or use a proper lookup
            # Let's iterate linearly over positions to remove matches if needed
            # For simplicity, we can do a dict comprehension to rebuild
            pass
            
        # Rebuild is safer to handle collision offsets
        self.ring = []
        self.positions = {}
        remaining_nodes = list(self.nodes)
        self.nodes = set()
        for node in remaining_nodes:
            self.add_node(node)

    def get_node(self, key: str) -> Optional[RingPosition]:
        if not self.ring:
            return None
            
        h = self._hash(key)
        idx = bisect.bisect_left(self.ring, h)
        
        # If we hit the end of the ring, wrap around to the first node
        if idx == len(self.ring):
            idx = 0
            
        return self.positions[self.ring[idx]]

    def get_distribution(self, keys: List[str]) -> Dict[str, int]:
        distribution = {node: 0 for node in self.nodes}
        for key in keys:
            pos = self.get_node(key)
            if pos:
                distribution[pos.physical_node] += 1
        return distribution
