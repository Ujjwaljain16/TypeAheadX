import sys
import os
import random
import string

# Add the parent directory to sys.path so we can import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app.cache.consistent_hash_ring import ConsistentHashRing

def generate_random_prefix(length: int = 5) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=length))

def run_distribution_test():
    print("Initializing Consistent Hash Ring with 500 virtual nodes...")
    ring = ConsistentHashRing(virtual_nodes=500)
    
    nodes = ["redis-a", "redis-b", "redis-c"]
    for node in nodes:
        ring.add_node(node)
        
    print(f"Total positions on the ring: {len(ring.ring)}")
    
    # Generate 1,000,000 keys
    num_keys = 1000000
    print(f"\nGenerating {num_keys} distinct cache keys...")
    
    # Pre-generate distinct keys
    keys = set()
    while len(keys) < num_keys:
        keys.add(f"suggestion:{generate_random_prefix(random.randint(3, 8))}")
        
    keys = list(keys)
    
    # Test distribution
    distribution = ring.get_distribution(keys)
    
    print("\nDistribution Results:")
    print("-" * 30)
    counts = []
    for node in nodes:
        count = distribution.get(node, 0)
        counts.append(count)
        percentage = (count / num_keys) * 100
        print(f"{node}: {count} keys ({percentage:.2f}%)")
        
    mean = sum(counts) / len(counts)
    variance = sum((c - mean) ** 2 for c in counts) / len(counts)
    import math
    std_dev = math.sqrt(variance)
    std_dev_percent = (std_dev / mean) * 100
    
    print("-" * 30)
    print(f"Standard Deviation: {std_dev:.2f} keys ({std_dev_percent:.2f}% relative to mean)")
    
    if std_dev_percent < 5.0:
        print("\n✅ Distribution is highly uniform (variance < 5%). Consistent hashing is working perfectly.")
    else:
        print("\n⚠️ Distribution is slightly uneven. Consider increasing virtual nodes.")

if __name__ == "__main__":
    run_distribution_test()
