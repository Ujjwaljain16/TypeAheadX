# Phase 4: Distribution Analysis & Ring Audit

Initially, our Consistent Hashing implementation utilized 150 virtual nodes per physical node, as recommended by early benchmarks. However, after scaling our empirical testing to **1,000,000 keys**, we observed a distribution of `39.6% / 28.7% / 31.7%`. 

Because 1,000,000 keys eliminated statistical sampling randomness, we determined that the hash ring's underlying physical geometry (the lengths of the arcs between the 450 virtual nodes) was slightly skewed.

## The Virtual Node Sensitivity Study
Instead of accepting the skew, we authored a diagnostic script (`scripts/ring_analysis.py`) to measure the exact 128-bit arc sizes for varying numbers of virtual nodes.

### Results

| Virtual Nodes | Total Positions | Ownership (A / B / C) | Std Dev of Arc Sizes |
|---------------|-----------------|-----------------------|----------------------|
| **150**       | 450             | 39.6% / 28.6% / 31.7% | 7.62e35 |
| **500**       | 1500            | 33.8% / 34.5% / 31.5% | 2.40e35 |
| **1000**      | 3000            | 33.3% / 32.5% / 34.1% | 1.11e35 |

## Engineering Decision
By scaling the virtual node count from 150 to 1000, we reduced the standard deviation of arc sizes by nearly 7x. This yielded a near-perfect ideal distribution.

**Trade-offs of increasing to 1000 Virtual Nodes:**
- **Pros:** Vastly superior load balancing. Prevents any single Redis node from becoming a hot partition.
- **Cons:** The hash ring grows from an array of 450 elements to 3,000 elements. The `bisect` lookup time increases from `O(log 450)` to `O(log 3000)`. However, `log2(3000) ≈ 11.5` operations, meaning the lookup penalty is practically zero nanoseconds in memory.

**Conclusion:** We have permanently updated the configuration to `VIRTUAL_NODES=1000`. The distribution is now verified as optimally balanced.
