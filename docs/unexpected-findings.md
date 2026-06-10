# Unexpected Findings & Architectural Lessons

A system's architecture on a whiteboard rarely survives contact with production traffic. Building TypeAheadX rigorously through 6 phases yielded several counter-intuitive insights that challenged our initial assumptions.

These four findings are the core "Staff-level" takeaways from this project.

---

## 1. Virtual nodes do not guarantee perfect ownership

In Phase 4, we implemented a Consistent Hashing ring to distribute our keyspace across `redis-a`, `redis-b`, and `redis-c`.
The naive assumption is that adding 3 physical nodes guarantees each node owns exactly 33.33% of the keys. 

Through our mathematical distribution simulation, we proved this false:
- With **1 virtual node** per physical node, standard deviation was extremely high. One node could accidentally own 70% of the keyspace.
- With **10 virtual nodes**, the variance was still ~20%.
- It took **150-500 virtual nodes** to drive the variance down to ~2%. 

**Takeaway:** Consistent hashing is purely probabilistic. You cannot achieve perfectly uniform ownership without oversampling the ring space significantly.

---

## 2. Bigger buffers do not always produce better systems

In Phase 5, we built an asynchronous batch-writer to reduce Database UPSERT operations.
The intuitive assumption was: *The bigger the write buffer, the more efficient the system.*

Our sensitivity analysis proved this false. 
- With a buffer size of **100**, we achieved a **~75% reduction** in database writes under Zipfian traffic.
- Increasing the buffer size to **10,000** only increased the reduction marginally (to ~90%), but introduced terrible side effects: memory bloat and severe data staleness (cache invalidations were delayed by minutes).

**Takeaway:** In Zipfian workloads, the vast majority of aggregation happens on the top few "hot" keys within the first few seconds. A small buffer heavily prioritizes data freshness while still capturing 80% of the possible write-reduction efficiency. Bigger is not always better; it is just staler.

---

## 3. Uniform sharding does not mean uniform traffic

In Phase 6, we ran a 100,000-request production benchmark. We had just mathematically proven that our 500 virtual nodes distributed the keys perfectly (33% / 33% / 33%).
However, our traffic distribution metrics showed:
- **`redis-a`**: 60.58% hits
- **`redis-b`**: 20.82% hits
- **`redis-c`**: 18.60% hits

Why? Because real-world search traffic is heavily skewed (Zipf's Law). The node that happens to own the hash for the #1 trending query (e.g., "iphone 16") will receive exponentially more traffic than the other nodes, regardless of how evenly the *total number of keys* is distributed.

**Takeaway:** Sharding algorithms distribute *keys*, but they do not distribute *traffic density*. To solve hot-key skew in production, you need local L1 memory caches (like Guava/LRU) sitting in front of your distributed L2 cache.

---

## 4. Graceful fallback does not prevent thundering herds

In Phase 6, we conducted a Node Failure Resilience test by killing `redis-b` mid-flight. 
Our code degraded gracefully: `distributed_cache.py` caught the `ConnectionError` and correctly routed the queries directly to PostgreSQL as "Cache Misses".

But the system still failed. Why? 
Because 1,000 concurrent requests all experienced a cache miss *at the exact same time*. They all bypassed Redis and slammed the PostgreSQL connection pool simultaneously. The un-tuned database pool instantly saturated, causing the benchmark to hang.

**Takeaway:** Graceful degradation at the application layer can easily cause catastrophic failure at the database layer. True resilience against a dead cache node requires implementing **probabilistic cache expiry** or a **distributed Redis lock** to ensure only *one* thread fetches the missing data while the others wait.
