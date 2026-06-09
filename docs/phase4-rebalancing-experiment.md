# Phase 4: Rebalancing Experiment

The true test of a distributed cache is how it handles topology changes. 
When scaling up for high traffic events, adding a new cache server is essential. 

We ran a controlled experiment placing **100,000 distinct keys** across 3 nodes, and then measured the catastrophic impact of adding a 4th node using naive Modulo Hashing vs our implementation of Consistent Hashing.

## Experiment A: Naive Modulo Hashing
`hash(key) % N` where N transitions from 3 to 4.

- **Keys Moved:** 75,002 out of 100,000 
- **Invalidation Impact:** **75.00%**

Adding one node essentially destroyed the cache. The resulting 75% cache miss spike would hit the database exactly when it is already under heavy load.

## Experiment B: Consistent Hashing
`bisect` lookup across 128-bit ring with **1000 virtual nodes** (our tuned production configuration).

- **Keys Moved:** 24,636 out of 100,000
- **Invalidation Impact:** **24.64%**

By utilizing the hash ring, only the keys belonging to the physical segments that the 4th node interrupted were moved. Theoretically, adding a 4th node should claim exactly 25% of the total ring ownership (`1 / (old + new)`). Our empirical measurement of 24.64% demonstrates that the 1000-virtual-node configuration converges almost perfectly onto the theoretical ideal.

## Conclusion
Our Consistent Hashing implementation successfully **reduced cache invalidation by 67.2%** compared to modulo hashing during a topology change. 

Adding cache nodes is now completely safe. The new node will simply incur a ~25% cold-start miss rate while the remaining 3 nodes retain their 75% warm caches entirely intact.
