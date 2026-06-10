import asyncio
import aiohttp
import time
import numpy as np
import redis
import json

# Setup
URL_SUGGEST = "http://localhost:8000/suggest"
URL_METRICS_CACHE = "http://localhost:8000/cache/metrics"
URL_METRICS_WRITE = "http://localhost:8000/write/metrics"

REDIS_NODES = [
    {"host": "localhost", "port": 6379, "name": "redis-a"},
    {"host": "localhost", "port": 6380, "name": "redis-b"},
    {"host": "localhost", "port": 6381, "name": "redis-c"},
]

def flush_all_redis():
    print("Flushing all Redis nodes...")
    for node in REDIS_NODES:
        try:
            r = redis.Redis(host=node["host"], port=node["port"], db=0)
            r.flushall()
            print(f"  Flushed {node['name']} ({node['port']})")
        except Exception as e:
            print(f"  Failed to flush {node['name']}: {e}")
    time.sleep(1) # give it a moment

def generate_queries(n_queries=100_000, n_unique=10_000, alpha=1.3):
    ranks = np.random.zipf(a=alpha, size=n_queries)
    ranks = np.clip(ranks, 1, n_unique)
    
    top_queries = [
        "iphone 16", "chatgpt", "samsung galaxy s24", "macbook pro m3", 
        "python tutorial", "fastapi react tutorial", "aws certifications", 
        "docker vs kubernetes", "redis consistent hashing", "system design interview"
    ]
    for i in range(len(top_queries), n_unique):
        top_queries.append(f"query_item_{i}")
        
    return [top_queries[rank - 1] for rank in ranks]

async def fetch(session, url, params):
    start = time.perf_counter()
    try:
        async with session.get(url, params=params) as response:
            await response.read()
            latency = (time.perf_counter() - start) * 1000
            status = response.status
            return status, latency
    except Exception as e:
        print(f"Fetch error: {e}")
        latency = (time.perf_counter() - start) * 1000
        return 500, latency

async def get_metrics():
    async with aiohttp.ClientSession() as session:
        async with session.get(URL_METRICS_CACHE) as resp:
            cache_metrics = await resp.json()
        async with session.get(URL_METRICS_WRITE) as resp:
            write_metrics = await resp.json()
        return cache_metrics, write_metrics

async def experiment_1_cold_cache(queries):
    print("\n==================================================")
    print("EXPERIMENT 1: COLD CACHE BASELINE")
    print("==================================================")
    flush_all_redis()
    
    # We use 1000 unique queries to guarantee 1000 DB hits
    unique_queries = list(set(queries))[:1000]
    
    connector = aiohttp.TCPConnector(limit=200)
    latencies = []
    
    start_metrics, _ = await get_metrics()
    
    print(f"Sending {len(unique_queries)} requests to cold cache...")
    async with aiohttp.ClientSession(connector=connector) as session:
        chunk_size = 50
        for i in range(0, len(unique_queries), chunk_size):
            chunk = unique_queries[i:i+chunk_size]
            tasks = [fetch(session, URL_SUGGEST, {"q": q}) for q in chunk]
            results = await asyncio.gather(*tasks)
            for status, lat in results:
                latencies.append(lat)
                
    end_metrics, _ = await get_metrics()
    
    misses = end_metrics["misses"] - start_metrics["misses"]
    p50 = np.percentile(latencies, 50)
    p95 = np.percentile(latencies, 95)
    p99 = np.percentile(latencies, 99)
    
    print(f"Results:")
    print(f"  Requests sent: {len(unique_queries)}")
    print(f"  Cache misses (DB Reads): {misses}")
    print(f"  p50 latency: {p50:.2f}ms")
    print(f"  p95 latency: {p95:.2f}ms")
    print(f"  p99 latency: {p99:.2f}ms")
    
    return p50, p95, p99

async def experiment_2_warm_cache(queries):
    print("\n==================================================")
    print("EXPERIMENT 2, 3 & 5: WARM CACHE ZIPFIAN WORKLOAD")
    print("==================================================")
    
    # Pre-warm the cache by hitting the top queries once
    print("Warming cache with unique queries...")
    unique = list(set(queries))
    connector = aiohttp.TCPConnector(limit=200)
    async with aiohttp.ClientSession(connector=connector) as session:
        chunk_size = 200
        for i in range(0, len(unique), chunk_size):
            tasks = [fetch(session, URL_SUGGEST, {"q": q}) for q in unique[i:i+chunk_size]]
            await asyncio.gather(*tasks)
            
    print("Cache warmed. Waiting 2 seconds...")
    time.sleep(2)
    
    latencies = []
    statuses = []
    start_time = time.time()
    
    start_metrics, _ = await get_metrics()
    
    print(f"Sending {len(queries)} Zipfian requests...")
    connector = aiohttp.TCPConnector(limit=100)
    async with aiohttp.ClientSession(connector=connector) as session:
        chunk_size = 100
        for i in range(0, len(queries), chunk_size):
            chunk = queries[i:i+chunk_size]
            tasks = [fetch(session, URL_SUGGEST, {"q": q}) for q in chunk]
            results = await asyncio.gather(*tasks)
            for status, lat in results:
                statuses.append(status)
                latencies.append(lat)
            if i > 0 and i % 10000 == 0:
                print(f"  Processed {i}/{len(queries)}...")
                
    duration = time.time() - start_time
    end_metrics, _ = await get_metrics()
    
    success_count = sum(1 for s in statuses if s == 200)
    print(f"  Successes: {success_count}/{len(queries)}")
    
    hits = end_metrics["hits"] - start_metrics["hits"]
    misses = end_metrics["misses"] - start_metrics["misses"]
    total = hits + misses
    hit_rate = (hits / total * 100) if total > 0 else 0
    
    p50 = np.percentile(latencies, 50)
    p95 = np.percentile(latencies, 95)
    p99 = np.percentile(latencies, 99)
    throughput = len(queries) / duration
    
    print(f"\nExperiment 2 (Warm Cache) Results:")
    print(f"  p50 latency: {p50:.2f}ms")
    print(f"  p95 latency: {p95:.2f}ms")
    print(f"  p99 latency: {p99:.2f}ms")
    print(f"  Cache Hit Rate: {hit_rate:.2f}% ({hits} hits, {misses} misses)")
    print(f"  Throughput: {throughput:.2f} requests/sec")
    
    print("\nExperiment 3 (Distributed Cache Fairness) Results:")
    start_node_hits = start_metrics.get("node_hits", {})
    end_node_hits = end_metrics.get("node_hits", {})
    for node in REDIS_NODES:
        name = node["name"]
        node_hits = end_node_hits.get(name, 0) - start_node_hits.get(name, 0)
        pct = (node_hits / hits * 100) if hits > 0 else 0
        print(f"  {name}: {node_hits} hits ({pct:.2f}%)")
        
    return p50, p95, p99, hit_rate, throughput, end_node_hits

def write_markdown_report(cold_results, warm_results, phase1_data):
    c_p50, c_p95, c_p99 = cold_results
    w_p50, w_p95, w_p99, hit_rate, throughput, nodes = warm_results
    
    content = f"""# Phase 6: Production Performance Report

## Experiment 1: Cold Cache Baseline
Measures the penalty when Redis has no data, validating the PostgreSQL `text_pattern_ops` B-tree index.
- **p50 Latency:** {c_p50:.2f}ms
- **p95 Latency:** {c_p95:.2f}ms
- **p99 Latency:** {c_p99:.2f}ms

## Experiment 2 & 5: Warm Cache Zipfian Workload (100,000 requests)
Measures the real production path under highly skewed traffic.
- **Throughput:** {throughput:.2f} RPS
- **Cache Hit Rate:** {hit_rate:.2f}%
- **p50 Latency:** {w_p50:.2f}ms
- **p95 Latency:** {w_p95:.2f}ms
- **p99 Latency:** {w_p99:.2f}ms

## Experiment 3: Distributed Cache Fairness
Validates the consistent hashing algorithm's load distribution.
"""
    total_node_hits = sum(nodes.values())
    for node_name, hits in nodes.items():
        pct = (hits / total_node_hits * 100) if total_node_hits > 0 else 0
        content += f"- **{node_name}**: {pct:.2f}%\n"

    content += f"""
## Master Performance Table

| Architecture              |    p50 |    p95 | Cache Hit |             DB Reduction |
| ------------------------- | -----: | -----: | --------: | -----------------------: |
| Phase 1 PostgreSQL        | {phase1_data['p50']}ms | {phase1_data['p95']}ms |        0% |                       0% |
| Phase 6 Final System      |  {w_p50:.2f}ms |  {w_p95:.2f}ms |    {hit_rate:.2f}% | Reads + Writes optimized |

> **Capacity Story:** TypeAheadX sustained **{throughput:.0f} RPS** on a local laptop running a distributed cache and PostgreSQL backend.
"""
    
    with open("../docs/phase6-performance-report.md", "w") as f:
        f.write(content)
    print("\n✅ Report written to docs/phase6-performance-report.md")

async def main():
    print("Generating queries...")
    queries = generate_queries(100_000, 10_000, 1.3)
    
    cold_results = await experiment_1_cold_cache(queries)
    warm_results = await experiment_2_warm_cache(queries)
    
    phase1_data = {
        "p50": 7.48,
        "p95": 9.95
    }
    
    write_markdown_report(cold_results, warm_results, phase1_data)
    
    print("\nNow for Experiment 4, please run the benchmark while killing a Redis node manually.")

if __name__ == "__main__":
    asyncio.run(main())
