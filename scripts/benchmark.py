import time
import requests
import statistics

URL = "http://127.0.0.1:8000/suggest?q=iph"
NUM_REQUESTS = 1000

print(f"Warming up...")
for _ in range(10):
    requests.get(URL)

print(f"Running {NUM_REQUESTS} requests...")
latencies = []
for _ in range(NUM_REQUESTS):
    start = time.perf_counter()
    resp = requests.get(URL)
    end = time.perf_counter()
    if resp.status_code == 200:
        latencies.append((end - start) * 1000)

p50 = statistics.quantiles(latencies, n=100)[49]
p95 = statistics.quantiles(latencies, n=100)[94]
p99 = statistics.quantiles(latencies, n=100)[98]

print(f"p50: {p50:.2f} ms")
print(f"p95: {p95:.2f} ms")
print(f"p99: {p99:.2f} ms")
