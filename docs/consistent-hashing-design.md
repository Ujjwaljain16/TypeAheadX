# Architecture Deep Dive: Consistent Hashing Engine

This document provides a highly detailed architectural review of the TypeAheadX Consistent Hashing Engine, implemented in `backend/app/cache/consistent_hash_ring.py`. 

It details the mechanics of how we distribute search queries across a horizontal cluster of Redis nodes, avoiding catastrophic database failures during scaling events.

---

## 1. The Core Problem: Modulo Hashing

In a naive distributed system, keys are assigned to cache nodes using Modulo Hashing:
```python
node_index = hash("iphone") % N
```
Where `N` is the number of active Redis nodes.

**The Catastrophe**: If traffic spikes and we scale from 3 nodes to 4 nodes (`N=3` → `N=4`), the mathematical result for the modulo changes for **~75% of all keys**. 

Instantly, 75% of the global cache becomes functionally invalid. All subsequent read requests for those keys will cache-miss, slamming PostgreSQL concurrently. This is a classic **Thundering Herd** failure that will immediately exhaust database connection pools.

---

## 2. The Solution: Consistent Hashing (The "What" and "Why")

Consistent Hashing decouples the hash space from the number of servers. Instead of mapping keys directly to an index of servers, we project both the servers and the keys onto a fixed, massive integer circle (The Hash Ring).

### A. The 128-Bit MD5 Ring
In `consistent_hash_ring.py`, we use the `MD5` hashing algorithm.
```python
# Hash keys into a massive 128-bit integer space
return int(hashlib.md5(key.encode()).hexdigest(), 16)
```
- **Why MD5?** We do not need cryptographic security. We need deterministic, highly uniform, fast distribution across a massive 128-bit integer space. MD5 is perfectly suited for this compared to Python's built-in `hash()` which is salted randomly per-process.

### B. O(log N) Routing via Binary Search
When a user searches for `"iph"`, we need to find the node that owns it.
1. Hash `"iph"` to an integer $H$.
2. We maintain a sorted Python List of all node hashes on the ring.
3. We use `bisect.bisect_left(self.ring, H)` to perform a rapid $O(\log N)$ binary search to find the nearest node placed clockwise to $H$.
4. **Ring Wrap-Around**: If `bisect` returns an index equal to the length of the ring, it means $H$ is past the final node. We simply route it to index `0` (closing the circle).

### C. The Blast Radius of Scaling
When we add a 4th Redis node using this architecture, the node is inserted into a specific point on the ring. It only steals keys from its immediate clockwise neighbor.
- **Modulo Invalidation**: `75.00%`
- **Consistent Hashing Invalidation**: `~26.44%` (as proven by our `rebalance_experiment.py` simulation).

---

## 3. The Skew Problem: Virtual Nodes

A raw Consistent Hash Ring places physical nodes (e.g., `redis-a`, `redis-b`) randomly on the 128-bit integer circle. 
**The Problem**: By pure random chance, `redis-a` might land directly next to `redis-b`, giving it almost 0% of the ring's area, while `redis-c` sits alone and captures 80% of the traffic.

### The Mathematics of Virtual Nodes
We solved this by implementing **Virtual Nodes**. Instead of adding `redis-a` to the ring once, we add `redis-a_replica_0` through `redis-a_replica_N`.

How many virtual nodes do we need? We ran an empirical sensitivity study (`scripts/ring_analysis.py`):
- `10` Virtual Nodes: ~30% Standard Deviation (Unacceptable traffic skew).
- `150` Virtual Nodes: ~10% Standard Deviation (Common default, but still a risk for hot shards).
- **`500` Virtual Nodes**: `< 2.0%` Standard Deviation.

We hardcoded `VIRTUAL_NODES=500` via our `.env`. This guarantees mathematically uniform load distribution across the 3 physical Redis nodes at the cost of less than a kilobyte of memory overhead for the sorted array.

---

## 4. Failure and Resiliency

If a Redis node crashes (e.g., `redis-b` dies):
1. The Orchestrator (`distributed_cache.py`) handles the connection timeout gracefully.
2. The 500 virtual nodes belonging to `redis-b` are instantly deleted from the `self.ring` array.
3. The `bisect` binary search immediately and naturally begins routing traffic intended for `redis-b` to the next closest surviving physical nodes (`redis-a` or `redis-c`).
4. **Result**: The system remains 100% available. Only the keys previously owned by `redis-b` suffer a cache miss.

---

## 5. Observability (The "Where")

Distributed systems are notorious for hiding logic errors. To prove our math works in production, we implemented the `/cache/debug?q={prefix}` endpoint.

When called, it completely unrolls the hash ring logic for that specific key:
```json
{
  "key": "iphone 15",
  "provider": "distributed",
  "node": "redis-c",
  "hash": 12839182309182039812,
  "virtual_node": "redis-c_replica_219",
  "exists": true,
  "ttl": -1
}
```
This guarantees absolute transparency. An engineer can calculate the MD5 hash manually and verify that `bisect` correctly placed the query onto `redis-c_replica_219`.
