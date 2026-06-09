import httpx
import time
import random
import statistics

API_URL = "http://localhost:8000/suggest"

# Workload configuration
TOTAL_REQUESTS = 1000
HOT_PREFIXES = ["iph", "iphone", "sam", "air", "lap"]
COLD_PREFIXES = ["xyz", "qwerty", "random", "test", "apple", "mac", "win"]
HOT_PERCENTAGE = 0.90

def generate_workload():
    workload = []
    for _ in range(TOTAL_REQUESTS):
        if random.random() < HOT_PERCENTAGE:
            workload.append(random.choice(HOT_PREFIXES))
        else:
            workload.append(random.choice(COLD_PREFIXES))
    return workload

def run_benchmark():
    workload = generate_workload()
    latencies = []
    
    # Warmup
    print("Warming up connections...")
    try:
        httpx.get(f"{API_URL}?q=warmup")
    except Exception:
        print("API is down! Please start FastAPI on port 8000.")
        return

    print(f"Starting simulated workload of {TOTAL_REQUESTS} requests...")
    
    start_time = time.time()
    
    with httpx.Client() as client:
        for prefix in workload:
            req_start = time.perf_counter()
            resp = client.get(f"{API_URL}?q={prefix}")
            req_end = time.perf_counter()
            
            if resp.status_code == 200:
                latencies.append((req_end - req_start) * 1000)

    total_time = time.time() - start_time
    
    # Fetch metrics
    try:
        metrics_resp = httpx.get("http://localhost:8000/cache/metrics")
        metrics = metrics_resp.json()
    except Exception:
        metrics = {"error": "Could not fetch metrics"}
        
    print("\n=== Benchmark Results ===")
    print(f"Total time: {total_time:.2f} seconds")
    print(f"Requests per second: {TOTAL_REQUESTS / total_time:.2f}")
    
    if latencies:
        print("\nLatency Distribution:")
        print(f"p50: {statistics.median(latencies):.2f}ms")
        print(f"p95: {statistics.quantiles(latencies, n=100)[94]:.2f}ms")
        print(f"p99: {statistics.quantiles(latencies, n=100)[98]:.2f}ms")
        
    print("\nCache Metrics:")
    for k, v in metrics.items():
        print(f"{k}: {v}")
        
if __name__ == "__main__":
    run_benchmark()
