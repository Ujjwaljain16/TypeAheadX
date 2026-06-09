import httpx
import time

API_URL = "http://localhost:8000"

def run_test():
    with httpx.Client() as client:
        # Request 1 (MISS -> SET)
        print("Request 1...")
        client.get(f"{API_URL}/suggest?q=ttltest")
        
        # Request 2 (HIT)
        print("\nRequest 2...")
        client.get(f"{API_URL}/suggest?q=ttltest")
        
        # Get metrics
        m1 = client.get(f"{API_URL}/cache/metrics").json()
        print(f"Metrics after Request 2: hits={m1['hits']}, misses={m1['misses']}, sets={m1['sets']}")
        
        # Wait
        print("\nWaiting 3 seconds...")
        time.sleep(3)
        
        # Request 3 (MISS -> SET)
        print("\nRequest 3...")
        client.get(f"{API_URL}/suggest?q=ttltest")
        
        m2 = client.get(f"{API_URL}/cache/metrics").json()
        print(f"Metrics after Request 3: hits={m2['hits']}, misses={m2['misses']}, sets={m2['sets']}")

if __name__ == "__main__":
    run_test()
