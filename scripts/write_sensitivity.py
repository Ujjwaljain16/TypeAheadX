import numpy as np
from collections import defaultdict

def generate_zipf_queries(n_queries=100_000, n_unique=10_000, alpha=1.2):
    # Same generation logic as benchmark
    ranks = np.random.zipf(a=alpha, size=n_queries)
    ranks = np.clip(ranks, 1, n_unique)
    return ranks

def simulate_buffer(queries, max_size):
    """
    Simulates the write buffer filling up and flushing.
    Returns (db_writes_executed, total_flushes)
    """
    buffer = defaultdict(int)
    db_writes = 0
    flushes = 0
    
    for q in queries:
        buffer[q] += 1
        # When buffer hits max_size unique queries, flush
        if len(buffer) >= max_size:
            db_writes += len(buffer)
            flushes += 1
            buffer.clear()
            
    # Final flush
    if buffer:
        db_writes += len(buffer)
        flushes += 1
        
    return db_writes, flushes

def run_experiment():
    n_queries = 100_000
    n_unique = 10_000
    
    # alphas:
    # 1.1 -> Low skew
    # 1.3 -> Medium skew
    # 1.8 -> High skew (highly viral)
    alphas = [1.1, 1.3, 1.8]
    buffer_sizes = [100, 500, 1000, 5000]
    
    print("======================================================")
    print("WRITE BUFFER SENSITIVITY STUDY")
    print("======================================================\n")
    
    for alpha in alphas:
        print(f"--- Zipfian Skew: Alpha = {alpha} ---")
        queries = generate_zipf_queries(n_queries, n_unique, alpha)
        
        print(f"{'Buffer Size':<15} | {'DB Writes':<15} | {'Write Reduction':<20} | {'Flushes':<10}")
        print("-" * 65)
        for size in buffer_sizes:
            writes, flushes = simulate_buffer(queries, size)
            reduction = ((n_queries - writes) / n_queries) * 100
            print(f"{size:<15} | {writes:<15} | {reduction:>18.2f}% | {flushes:<10}")
        print("\n")

if __name__ == "__main__":
    run_experiment()
