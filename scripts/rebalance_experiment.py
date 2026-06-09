import sys
import os
import random
import string
import hashlib

# Add the parent directory to sys.path so we can import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app.cache.consistent_hash_ring import ConsistentHashRing

def generate_random_prefix(length: int = 5) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=length))

def run_rebalance_experiment():
    print("=" * 60)
    print("PHASE 4: REBALANCING EXPERIMENT (THE VIVA DEMO)")
    print("=" * 60)
    
    # 1. Generate 100,000 keys
    num_keys = 100000
    print(f"\nGenerating {num_keys} random cache keys...")
    keys = set()
    while len(keys) < num_keys:
        keys.add(f"suggestion:{generate_random_prefix(random.randint(4, 10))}")
    keys = list(keys)
    
    # ---------------------------------------------------------
    # EXPERIMENT A: NAIVE MODULO HASHING
    # ---------------------------------------------------------
    print("\n--- EXPERIMENT A: NAIVE MODULO HASHING ---")
    nodes_3 = ["redis-a", "redis-b", "redis-c"]
    nodes_4 = ["redis-a", "redis-b", "redis-c", "redis-d"]
    
    def modulo_hash(key: str, node_list: list) -> str:
        h = int(hashlib.md5(key.encode()).hexdigest(), 16)
        return node_list[h % len(node_list)]
        
    print("Mapping 100K keys across 3 nodes...")
    modulo_state_3 = {key: modulo_hash(key, nodes_3) for key in keys}
    
    print("Adding 4th node (redis-d) and remapping...")
    modulo_state_4 = {key: modulo_hash(key, nodes_4) for key in keys}
    
    modulo_keys_moved = sum(1 for key in keys if modulo_state_3[key] != modulo_state_4[key])
    modulo_percent = (modulo_keys_moved / num_keys) * 100
    
    print(f"Keys moved: {modulo_keys_moved:,} out of {num_keys:,} ({modulo_percent:.2f}%)")
    if modulo_percent > 70:
        print("❌ CATASTROPHIC CACHE AVALANCHE DETECTED.")
        
    # ---------------------------------------------------------
    # EXPERIMENT B: CONSISTENT HASHING
    # ---------------------------------------------------------
    print("\n--- EXPERIMENT B: CONSISTENT HASHING ---")
    ring = ConsistentHashRing(virtual_nodes=1000)
    for node in nodes_3:
        ring.add_node(node)
        
    print("Mapping 100K keys across 3 nodes using Hash Ring...")
    consistent_state_3 = {key: ring.get_node(key).physical_node for key in keys}
    
    print("Adding 4th node (redis-d) to the Hash Ring and remapping...")
    ring.add_node("redis-d")
    consistent_state_4 = {key: ring.get_node(key).physical_node for key in keys}
    
    consistent_keys_moved = sum(1 for key in keys if consistent_state_3[key] != consistent_state_4[key])
    consistent_percent = (consistent_keys_moved / num_keys) * 100
    
    print(f"Keys moved: {consistent_keys_moved:,} out of {num_keys:,} ({consistent_percent:.2f}%)")
    
    expected_percent = 100.0 / len(nodes_4) # roughly 25% should move to the new node
    
    print("\n--- CONCLUSION ---")
    print(f"Modulo Hashing caused {modulo_percent:.1f}% cache invalidation.")
    print(f"Consistent Hashing caused only {consistent_percent:.1f}% cache invalidation.")
    print(f"Consistent Hashing reduced cache misses by {((modulo_keys_moved - consistent_keys_moved) / modulo_keys_moved) * 100:.1f}% during topology change.")
    print("\n✅ Rebalancing Experiment Successful.")

if __name__ == "__main__":
    run_rebalance_experiment()
