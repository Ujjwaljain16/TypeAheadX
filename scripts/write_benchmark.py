import asyncio
import aiohttp
import time
import random
import numpy as np

# Use numpy for zipfian distribution
# Zipfian parameter typically slightly > 1, e.g., 1.5
def generate_zipf_queries(n_queries=100_000, n_unique=10_000, alpha=1.2):
    print(f"Generating {n_queries} queries from {n_unique} unique items (Zipfian alpha={alpha})...")
    
    # Generate zipf distribution
    ranks = np.random.zipf(a=alpha, size=n_queries)
    
    # Cap ranks to our unique items and ensure it's 1-indexed
    ranks = np.clip(ranks, 1, n_unique)
    
    # Map ranks to queries
    top_queries = [
        "iphone 16", "chatgpt", "samsung galaxy s24", "macbook pro m3", 
        "python tutorial", "fastapi react tutorial", "aws certifications", 
        "docker vs kubernetes", "redis consistent hashing", "system design interview"
    ]
    
    # Pad out the rest with generic terms
    for i in range(len(top_queries), n_unique):
        top_queries.append(f"query_item_{i}")
        
    # Map the zipf ranks to the actual query strings
    # Zipf returns 1-indexed integers, so we subtract 1 for 0-indexed python arrays
    return [top_queries[rank - 1] for rank in ranks]

async def send_search(session, url, query):
    try:
        async with session.post(url, json={"query": query}) as response:
            return response.status
    except Exception as e:
        return 500

async def run_benchmark():
    print("==================================================")
    print("PHASE 5: BATCH WRITE BUFFER BENCHMARK")
    print("==================================================")
    
    URL = "http://localhost:8000/search"
    METRICS_URL = "http://localhost:8000/write/metrics"
    
    queries = generate_zipf_queries(100_000, 10_000, 1.3)
    
    print("\nStarting asynchronous request flood...")
    start_time = time.time()
    
    # Use a TCPConnector with lower limit to avoid Windows select() 512 FD limit
    connector = aiohttp.TCPConnector(limit=200)
    async with aiohttp.ClientSession(connector=connector) as session:
        # Process in smaller chunks to avoid too many concurrent connections
        chunk_size = 200
        for i in range(0, len(queries), chunk_size):
            chunk = queries[i:i+chunk_size]
            tasks = [send_search(session, URL, q) for q in chunk]
            await asyncio.gather(*tasks)
            print(f"  Processed {min(i+chunk_size, len(queries))}/{len(queries)} requests...")

    duration = time.time() - start_time
    print(f"\nCompleted 100,000 requests in {duration:.2f} seconds.")
    print(f"Throughput: {100_000 / duration:.2f} req/sec")
    
    print("\nWaiting 12 seconds for final background flush to trigger...")
    time.sleep(12)
    
    print("\nFetching final metrics from API...")
    async with aiohttp.ClientSession() as session:
        async with session.get(METRICS_URL) as response:
            if response.status == 200:
                metrics = await response.json()
                print("\n--- WRITE REDUCTION RESULTS ---")
                print(f"Searches Received:      {metrics['searches_received']}")
                print(f"Background Flushes:     {metrics['flushes_executed']}")
                print(f"DB Writes Executed:     {metrics['db_writes_executed']}")
                print(f"DB Writes Avoided:      {metrics['db_writes_avoided']}")
                print(f"WRITE REDUCTION:        {metrics['write_reduction_percent']}%")
            else:
                print("Failed to fetch metrics.")
                
    print("\n✅ Benchmark Complete.")

if __name__ == "__main__":
    asyncio.run(run_benchmark())
