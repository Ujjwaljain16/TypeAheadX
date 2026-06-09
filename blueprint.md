# Search Typeahead — Staff Engineer Architecture Blueprint (v2.0)

> **Purpose:** Complete execution plan for maximum-marks submission. Every section is written to be defensible at viva level. No code. No shortcuts. No filler.
>
> **Change Log (v1.0 → v2.0):**
> - Resolved search_events vs. unified queries table debate (Feedback 1)
> - Replaced Trie-first recommendation with Option-weighted analysis and clear final choice (Feedback 2)
> - Replaced exponential decay with Historical+Decayed Recent Count as the recommended formula (Feedback 3)
> - Added complete ADR suite: docs/adrs/ (Feedback 4)
> - Added Differentiation Features with Effort vs Impact matrix (Feedback 5)
> - Added explicit "What We Are NOT Building" scope control section (Feedback 6)
> - Added Final Architecture Lock section with exact specs (Feedback 7)

---

## Table of Contents

1. [Requirement Decomposition](#section-1--requirement-decomposition)
2. [Grading Strategy](#section-2--grading-strategy)
3. [Architecture Options Analysis](#section-3--architecture-options-analysis)
4. [Final Recommended Architecture](#section-4--final-recommended-architecture)
5. [Data Model Design](#section-5--data-model-design)
6. [Cache Design Review](#section-6--cache-design-review)
7. [Consistent Hashing Design](#section-7--consistent-hashing-design)
8. [Trending System Design](#section-8--trending-system-design)
9. [Batch Write Design](#section-9--batch-write-design)
10. [Performance Plan](#section-10--performance-plan)
11. [Observability Plan](#section-11--observability-plan)
12. [ADR Strategy](#section-12--adr-strategy)
13. [Differentiation Features](#section-13--differentiation-features)
14. [What We Are Explicitly NOT Building](#section-14--what-we-are-explicitly-not-building)
15. [Implementation Roadmap](#section-15--implementation-roadmap)
16. [README Strategy](#section-16--readme-strategy)
17. [Viva Preparation](#section-17--viva-preparation)
18. [Critical Review](#section-18--critical-review)
19. [Final Architecture Lock](#section-19--final-architecture-lock)

---

## Section 1 — Requirement Decomposition

### 1.1 Explicit Requirements

| Requirement | Why It Exists | What Evaluator Tests | Possible Approaches |
|---|---|---|---|
| Prefix-matching suggestions, top 10, sorted by count | Core typeahead semantics | Can you build a read-optimised prefix lookup? | SQL LIKE, Trie, Sorted Set, Prefix Index |
| Search submission → count update | Simulates real write workload | Do you understand write paths? | Synchronous DB write, async queue, batch buffer |
| Distributed cache via consistent hashing | Tests distributed systems theory | Can you implement and explain consistent hashing? | In-process hash ring, logical nodes over single Redis, multi-instance Redis |
| Trending searches (recency-aware ranking) | Tests time-series thinking | Can you model time-decay on a popularity signal? | Fixed window, sliding window, exponential decay, historical+recent hybrid |
| Batch writes | Tests write-path optimisation | Do you understand write amplification? | Memory buffer, in-process queue, WAL-style log |
| Dataset ≥ 100,000 queries with counts | Stress tests your indexing | Will your system degrade on real data volume? | AOL query log, Amazon product search, Wikipedia page views |
| p95 latency reporting | Tests observability habits | Do you instrument your own system? | Manual timing middleware, Prometheus histogram |
| Cache hit rate reporting | Tests cache effectiveness | Is your cache actually useful? | Counter middleware on cache layer |
| `GET /cache/debug?prefix=<prefix>` | Tests understanding of routing | Can you trace which node owns a key? | Hash ring lookup + hit/miss log |

### 1.2 Hidden Requirements (Not Stated but Penalised if Missing)

- **Graceful degradation**: if the cache misses, the system still responds correctly from the database.
- **Case normalisation**: mixed-case prefix "iPHone" must hit the same bucket as "iphone". Evaluators will type weird inputs.
- **Empty/whitespace input handling**: must return empty array, not a 500.
- **Debouncing on the frontend**: easy to forget. Evaluators will check network tab.
- **Thread/concurrency safety for the batch buffer**: in-memory buffers need a lock or atomic counter.
- **Consistent hash ring explanation**: you must be able to narrate the ring, explain virtual nodes, and explain rehashing during viva.
- **Trending ≠ most popular**: the evaluator expects you to demonstrate that a query that spiked recently ranks higher than one that was popular three months ago.
- **Failure trade-off discussion for batch writes**: what happens if the server crashes before a flush? Most common viva follow-up.

### 1.3 Viva Expectations

The evaluator is not checking if your code runs. They are checking:

1. Whether you understand *why* each component exists.
2. Whether you can articulate the tradeoffs *you chose*, not just the tradeoffs in general.
3. Whether you can break your own system under questioning (crash scenarios, node failure, cold cache).

### 1.4 Common Failure Modes in Submissions

| Failure | Why It Happens | Impact |
|---|---|---|
| "Consistent hashing" is just one Redis with a hardcoded node count | Misunderstood the requirement | Heavy penalty on cache marks |
| Trending = most popular all time | Didn't implement recency | Full 20 marks gone |
| Batch write is just a counter that resets | Not actually batching DB writes | 20 marks gone |
| No evidence for cache hit rate | Collected no metrics | Performance report empty |
| Trie with no persistence | Cache cold-start kills the trie | System unusable after restart |
| Frontend makes a request on every keystroke | No debouncing | Explicitly called out in rubric |

---

## Section 2 — Grading Strategy

### 2.1 Basic Implementation (60 marks)

**Minimum for full marks:**
- Dataset loaded into PostgreSQL
- `GET /suggest` returns correct top-10 prefix-matching results sorted by count
- `POST /search` updates the count
- Cache layer sits in front of the DB
- Consistent hashing ring with ≥3 virtual nodes routes prefix keys to cache nodes
- Working UI with debounced input and dropdown

**Better implementation:**
- PostgreSQL with a B-tree index on a normalised query column
- Logical multi-node cache using a Python/Node hash ring class over a dictionary pool
- Cache miss → DB → populate cache flow with TTL
- `/cache/debug` endpoint showing ring routing live

**Exceptional implementation:**
- Prefix index (trie loaded into memory on startup, backed by DB for persistence)
- Cache warm-up: top-1000 prefixes pre-populated at startup
- Node addition/removal demo with before/after key distribution logged

### 2.2 Trending Searches (20 marks)

**Minimum for full marks:**
- Some form of recency signal (even a fixed 1-hour window)
- Scoring formula documented
- Demonstration that a recently searched query outranks an older one with higher all-time count

**Better implementation:**
- `recent_count` field counting searches in the last N hours
- Combined score = `historical_count + decay_factor × recent_count`
- Cache invalidation triggered when trending scores change

**Exceptional implementation:**
- Per-update decay on `recent_count`: each flush applies `recent_count = recent_count × e^(−λ × Δt)`
- Configurable λ and decay window
- Mathematical justification for λ in README

### 2.3 Batch Writes (20 marks)

**Minimum for full marks:**
- Writes collected in an in-memory buffer
- Flushed every N seconds OR when buffer size reaches threshold
- Demonstrated write reduction (e.g. 1000 searches → 50 DB writes shown in logs)

**Better implementation:**
- Dual-trigger flush: time-based AND size-based, whichever fires first
- Separate background thread/process for flush
- Counter tracking writes avoided

**Exceptional implementation:**
- Crash-safety discussion with append-only log as pre-flush buffer
- Recovery logic: on startup, scan log file and replay uncommitted entries
- Metrics showing: searches received, buffer flushes, writes executed, writes avoided

---

## Section 3 — Architecture Options Analysis

### 3.1 Typeahead Engine: Revised Analysis

#### Feedback 2 Addressed — Trie vs. PostgreSQL + Cache

The original blueprint strongly recommended a Trie as the primary index. This section challenges that recommendation with a rigorous comparison.

---

**Option A: PostgreSQL prefix index + Cache**

```sql
CREATE INDEX idx_query_prefix ON queries (query text_pattern_ops);
-- GET /suggest: check cache → on miss, run LIKE 'prefix%' → cache result
```

| Dimension | Verdict |
|---|---|
| Implementation complexity | Low. No extra data structure. |
| Marks impact | Good. Shows index awareness. Misses the "advanced data structure" signal. |
| Performance at 100K queries | Excellent. B-tree prefix scan is O(log n + k). Under cache, the DB is rarely hit. |
| Viva impact | Solid. Can explain text_pattern_ops, B-tree, prefix scanning. |
| Risk | Low. If cache is warm (85–95% hit rate), DB is nearly never queried. |

**Conclusion:** Sufficient for full marks if cache hit rate is demonstrably high. Leaves marks on the table for "exceptional implementation" tier.

---

**Option B: Trie + PostgreSQL**

- Trie in memory, loaded from DB at startup.
- All suggestion queries hit the Trie. DB only serves as persistence layer.

| Dimension | Verdict |
|---|---|
| Implementation complexity | Medium. Trie is 100–150 lines. Sync logic on flush adds ~50 more lines. |
| Marks impact | High. Shows CS fundamentals. Clearly "exceptional" tier. |
| Performance at 100K queries | Excellent. O(prefix_length) lookup. No network round-trip. |
| Viva impact | Excellent. You can explain O(k) lookup, prefix sharing, node structure. |
| Risk | Medium. Trie cold-start on restart (2–3 seconds load). Sync bugs if not careful. |

**Conclusion:** Best for marks and viva. The implementation risk is low for a 100K dataset.

---

**Option C: Trie + PostgreSQL + Cache**

- Trie serves all suggestion reads.
- Cache sits in front of the Trie (reduces even the O(k) lookup cost for hot prefixes).
- PostgreSQL is authoritative persistence.

| Dimension | Verdict |
|---|---|
| Implementation complexity | High. Three systems to keep in sync. |
| Marks impact | Maximum. All three systems interact and each can be explained. |
| Performance at 100K queries | Near-optimal. Cache hits return in < 2ms. Trie hits in < 5ms. |
| Viva impact | Excellent. Three-tier architecture is highly defensible. |
| Risk | Higher. Cache invalidation must work correctly for both Trie and cache. If either is stale, demo looks broken. |

**Conclusion:** Only pursue Option C if the team has clean cache invalidation logic already working from Option B. Do not add cache on top of Trie as an afterthought — the invalidation coupling is a bug surface.

---

#### If the team only has time to implement ONE advanced feature: Trie or Distributed Cache?

**Answer: Distributed Cache (consistent hashing) is the mandatory requirement. Trie is the optional enhancer.**

The assignment rubric explicitly tests distributed cache with consistent hashing. It does not explicitly require a Trie — the basic requirement is correct prefix-matching suggestions. If forced to choose, implement the cache correctly and use the PostgreSQL prefix index for lookups.

**However:** If the team can implement both (which is achievable in 5 days), Option B (Trie + PostgreSQL, with cache in front) is the correct architecture. This is the final recommendation.

**Final recommendation: Option B** (Trie + PostgreSQL). Add cache in front as part of the mandatory consistent hashing requirement. This naturally becomes Option C without extra architectural risk.

---

### 3.2 Cache Layer

#### Option A: Single Redis instance
- Does NOT satisfy the "distributed cache with consistent hashing" requirement.
- **Verdict:** Fails the requirement. Cannot use as sole cache.

#### Option B: Multiple Redis instances + consistent hashing router in application
- Actually distributed. Satisfies the requirement completely.
- Requires Docker Compose with 3 Redis containers.
- **Verdict:** Best choice. Use 3 Redis instances + Python/JS hash ring.

#### Option C: Logical distributed cache (single process, N dictionaries simulating nodes)
- Not actually distributed. Evaluator may push back during viva.
- Acceptable if labelled clearly as simulation with justification.
- **Verdict:** Acceptable fallback if Docker is not available. Label it explicitly.

**Recommended: 3 real Redis instances via Docker Compose + application-layer consistent hash ring.**

---

### 3.3 Trending Algorithm: Revised Analysis

#### Feedback 3 Addressed — Challenging Exponential Decay

The original blueprint recommended per-event exponential decay (Option D below). This section challenges that and evaluates four approaches.

---

**Option 1: Exponential decay per event**

```
trending_score = all_time_count × w_base + Σ_events e^(−λ × Δt_hours)
```

| Dimension | Verdict |
|---|---|
| Implementation effort | Medium-High. Requires scanning search_events table per trending call. |
| Correctness | Excellent. Mathematically principled. |
| Explainability | Good. But requires calculus intuition for viva. |
| Debugging complexity | High. If w_base is wrong or λ is off, the output is wrong in subtle ways. |
| Demo friendliness | Low. Hard to visually show decay in real time. Numbers change slowly. |

**Verdict:** Academically elegant. Not the best assignment-grade choice. Requires a separate `search_events` table and periodic table scans, adding complexity without proportional mark gain.

---

**Option 2: Sliding window**

```
recent_score = COUNT(*) FROM search_events WHERE searched_at > NOW() - INTERVAL '1 hour'
```

| Dimension | Verdict |
|---|---|
| Implementation effort | Low-Medium. Requires search_events table. |
| Correctness | Good. But cliff effect: a query falls off the list the instant the window ends. |
| Explainability | Easy. "Count searches in the last hour." |
| Debugging complexity | Low. |
| Demo friendliness | Medium. Cliff effect makes trending "flicker" in demo. |

**Verdict:** Too naive. Cliff effect is a known weakness the evaluator will probe.

---

**Option 3: Historical + Recent count (two fields, no decay)**

```
score = historical_count + α × recent_count
-- historical_count: all-time count
-- recent_count: count in last N hours, reset periodically
-- α: weight constant (e.g. 10)
```

| Dimension | Verdict |
|---|---|
| Implementation effort | Low. Two integer fields on the queries table. No search_events table needed. |
| Correctness | Good. Recent activity boosts score. No cliff if reset is gradual. |
| Explainability | Excellent. "We weight recent searches more heavily." Easy to whiteboard. |
| Debugging complexity | Very low. |
| Demo friendliness | High. Search a new query, watch recent_count increment, watch it rise in trending. |

**Verdict:** Strong for assignment marks. Simple to implement, easy to demo, easy to defend. The main weakness: recent_count doesn't decay smoothly — it stays constant until the next reset cycle.

---

**Option 4: Historical + Decayed recent count (RECOMMENDED)**

```
-- On each batch flush:
recent_count = recent_count × e^(−λ × hours_since_last_flush)
recent_count += delta_from_flush

-- Trending score:
score = historical_count + β × recent_count
```

| Dimension | Verdict |
|---|---|
| Implementation effort | Low-Medium. Two fields on queries table. Decay applied per flush. No search_events table. |
| Correctness | Excellent. Smooth decay without cliff. Mathematically principled. |
| Explainability | Good. "Recent searches decay over time. We multiply by a decay factor on each update." Easy to whiteboard a half-life. |
| Debugging complexity | Low-Medium. One formula, one place (the flush handler). |
| Demo friendliness | High. Search a query, it rises immediately. Stop searching, it decays over minutes. |

**Verdict: This is the correct choice.** It combines the mathematical rigour of exponential decay with the implementation simplicity of Option 3. No separate search_events table needed. No table scans. Fully contained in the queries table.

---

#### Final Recommendation: Option 4 — Historical + Decayed Recent Count

This eliminates the need for the `search_events` table entirely (see Feedback 1 resolution in Section 5). The trending formula is applied per flush, is explainable in 30 seconds, and produces a clean demo.

---

### 3.4 Batch Writes

The original analysis in v1.0 is correct. No changes to the recommendation.

**Recommended: In-memory aggregation buffer with dual-trigger flush (time + size). Discuss WAL as the crash-recovery extension in documentation.**

---

## Section 4 — Final Recommended Architecture

### 4.1 System Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                     Frontend (React/Vanilla JS)                   │
│   Search Input → Debounced (300ms) → GET /suggest                 │
│   Submit → POST /search                                           │
│   Trending Panel → GET /trending                                  │
│   Cache Ring Visualizer → GET /cache/ring (bonus)                 │
└──────────────────────┬───────────────────────────────────────────┘
                       │ HTTP
┌──────────────────────▼───────────────────────────────────────────┐
│                    FastAPI / Express Backend                       │
│                                                                    │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  Consistent Hash Router                                      │  │
│  │  hash_ring.get_node(prefix) → Redis Node 0 / 1 / 2          │  │
│  └──────────────────┬──────────────────────────────────────────┘  │
│                     │                                              │
│  ┌──────────────────▼──────────────────────────────────────────┐  │
│  │  Cache Layer (3 Redis instances)                             │  │
│  │  Key: suggest:{prefix}  Value: JSON list  TTL: 60s           │  │
│  └──────────────────┬──────────────────────────────────────────┘  │
│           HIT ──────┘    MISS                                      │
│                          │                                         │
│  ┌───────────────────────▼─────────────────────────────────────┐  │
│  │  In-process Trie (loaded from DB on startup)                 │  │
│  │  trie.search(prefix) → top-10 sorted by trending_score       │  │
│  └───────────────────────┬─────────────────────────────────────┘  │
│                          │ populate cache                          │
│                          │                                         │
│  ┌───────────────────────▼─────────────────────────────────────┐  │
│  │  Batch Write Buffer                                           │  │
│  │  {query: delta}  Flush every 10s or 100 writes               │  │
│  │  On flush: apply decay to recent_count, add delta             │  │
│  └───────────────────────┬─────────────────────────────────────┘  │
│                          │                                         │
└──────────────────────────┼─────────────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────────────┐
│              PostgreSQL                                             │
│  queries(id, query, historical_count, recent_count,                 │
│           last_decay_at, last_searched_at)                          │
│                                                                     │
│  NO search_events table  ← intentional simplification              │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.2 Request Flows

#### Suggestion Flow (GET /suggest?q=iph)
```
1. Normalise input: lowercase, strip whitespace
2. Hash router: node = hash_ring.get_node("iph")
3. Cache lookup: redis_node.get("suggest:iph")
4. HIT → return cached JSON immediately
5. MISS →
   a. Query in-process Trie for prefix "iph"
   b. Sort results by trending_score DESC (= historical_count + β × recent_count)
   c. Take top 10
   d. Serialise to JSON
   e. Write to cache: redis_node.set("suggest:iph", json, ex=60)
   f. Return response
```

#### Search Submission Flow (POST /search { query: "iphone 15" })
```
1. Normalise query
2. Return {"message": "Searched"} immediately
3. In background:
   a. batch_buffer.increment("iphone 15")
4. If batch flush triggered:
   a. Copy current buffer state, clear buffer
   b. For each (query, delta) in snapshot:
      - Compute hours_since_last_decay = (now - last_decay_at) / 3600
      - new_recent = old_recent × e^(−λ × hours_since_last_decay) + delta
      - UPSERT queries SET
          historical_count = historical_count + delta,
          recent_count = new_recent,
          last_decay_at = NOW(),
          last_searched_at = NOW()
      - Update in-process Trie node: count and trending_score
      - Invalidate all prefix cache keys: suggest:i, suggest:ip, suggest:iph, ...
```

#### Trending Flow (GET /trending)
```
1. Check Redis "trending" key (TTL 30s)
2. HIT → return cached result
3. MISS →
   a. SELECT query, historical_count, recent_count FROM queries
      ORDER BY (historical_count + β × recent_count) DESC LIMIT 10
   b. Cache under "trending" key, TTL=30s
   c. Return result
```

#### Cache Debug Flow (GET /cache/debug?prefix=iph)
```
1. Compute hash_ring.get_node("iph") → node_id, node_address
2. Check cache: hit/miss, TTL remaining if hit
3. Return: { prefix, node_id, node_address, virtual_node_responsible, cache_status, ttl_remaining }
```

### 4.3 Component Responsibilities

| Component | Owns | Does Not Own |
|---|---|---|
| Hash Ring | Key-to-node routing | Cache storage |
| Redis Node (×3) | Suggestion result cache | Source-of-truth counts |
| In-process Trie | Fast prefix lookup | Persistence |
| PostgreSQL | Authoritative counts and decay state | Suggestion assembly |
| Batch Buffer | Write aggregation and decay application | Durability |
| Trending Engine | Score computation from queries table | Raw event storage |

---

## Section 5 — Data Model Design

### 5.1 Feedback 1 Resolved: search_events vs. Unified queries Table

**The question:** Is a separate `search_events` table required, or can trending be implemented using `historical_count`, `recent_count`, and `last_decay_at` inside a single `queries` table?

#### Design A: Two-Table (queries + search_events)

```
queries: id, query, count, last_searched_at
search_events: id, query, searched_at
```

Trending engine scans `search_events WHERE searched_at > NOW() - INTERVAL '12 hours'` and computes decay per event.

| Criterion | Score |
|---|---|
| Assignment marks | Same marks. Two tables shows separation of concerns. |
| Implementation effort | Higher. Two tables, two write paths, periodic scan. |
| Viva defensibility | Good but overkill — evaluator may ask why you need both. |
| Performance | Slightly worse. Trending requires a table scan on every call (mitigated by cache). |
| Simplicity for demo | Lower. More moving parts to break. |

#### Design B: Single Table with Decayed Fields (RECOMMENDED)

```
queries: id, query, historical_count, recent_count, last_decay_at, last_searched_at
```

Decay applied in the batch flush handler. No separate table. No event scans.

| Criterion | Score |
|---|---|
| Assignment marks | Same marks. Single table with decay fields shows equivalent sophistication. |
| Implementation effort | Lower. One table, one write path. |
| Viva defensibility | Excellent. You can explain the decay formula applied per-flush. Easier to whiteboard. |
| Performance | Better. Trending query is a simple ORDER BY on two numeric fields. |
| Simplicity for demo | Higher. One system, one place where decay happens, easy to show in logs. |

**Decision: Design B. Eliminate the search_events table entirely.**

The `recent_count` field carries all the recency information needed. The decay is applied on every batch flush, meaning it is updated frequently and accurately without requiring a raw event log.

The one capability lost: you cannot retroactively recompute trending with a different λ, because the raw events are not stored. For an assignment, this is not a relevant concern. Document it as a known limitation.

---

### 5.2 Primary Table: `queries`

```sql
CREATE TABLE queries (
    id               BIGSERIAL PRIMARY KEY,
    query            TEXT NOT NULL UNIQUE,          -- normalised lowercase
    historical_count BIGINT NOT NULL DEFAULT 0,     -- all-time cumulative count
    recent_count     FLOAT NOT NULL DEFAULT 0.0,    -- decayed recency signal
    last_decay_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_searched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_query_prefix ON queries (query text_pattern_ops);
CREATE INDEX idx_trending_score ON queries (
    (historical_count + 10.0 * recent_count) DESC
);
```

**Why FLOAT for recent_count?** Decay multiplication produces fractional values. Using FLOAT avoids rounding errors while keeping the column in the same table.

**Read frequency:** Every cache miss (uncommon once warm). Every trending call (cached at 30s).
**Write frequency:** Every batch flush (every 10s or 100 writes).

---

### 5.3 In-Process Trie Node Structure

```
TrieNode {
  children: Map<char, TrieNode>
  is_end: bool
  query: string (only if is_end = true)
  historical_count: int
  recent_count: float
  trending_score: float  // = historical_count + β × recent_count
}
```

**Loading:** On startup, `SELECT query, historical_count, recent_count FROM queries ORDER BY historical_count DESC` → insert all into Trie.
**Updates:** On batch flush, update affected Trie node fields in place. No full rebuild needed.

---

### 5.4 Batch Buffer State

```
BatchBuffer {
  buffer: Map<string, int>   // query → accumulated delta since last flush
  last_flush: timestamp
  flush_interval: 10 seconds
  flush_size_threshold: 100
  writes_avoided: counter
  flushes_executed: counter
}
```

---

### 5.5 Cache Key Schema

| Key Pattern | Content | TTL | Owner Node |
|---|---|---|---|
| `suggest:{normalised_prefix}` | JSON array of top-10 results | 60s | Determined by hash ring |
| `trending` | JSON array of top-10 trending | 30s | Fixed to node 0 |
| `cache_stats` | Hit/miss counters | No TTL | Node 0 |

**Invalidation:** On batch flush, for each updated query `q`, compute all prefixes of `q` and delete their cache keys from the appropriate nodes.

---

## Section 6 — Cache Design Review

### 6.1 What to Cache

| Item | Rationale |
|---|---|
| Suggestion results per prefix | Reads vastly outnumber writes. Same prefix queried thousands of times. |
| Trending results | Trending query is ORDER BY on computed expression. Cache at 30s TTL. |

### 6.2 What NOT to Cache

| Item | Reason |
|---|---|
| Individual query counts | Write-heavy. Caching counts means double-write burden. |
| POST /search response | Always `{"message": "Searched"}`. No value in caching. |

### 6.3 Cache Key Design

```
normalise(prefix) = prefix.toLowerCase().trim()
cache_key = "suggest:" + normalise(prefix)
```

Prefix "suggest:" prevents collision with "trending" or future keys in the same Redis keyspace.

### 6.4 TTL Strategy

| Key | TTL | Justification |
|---|---|---|
| suggest:{prefix} | 60 seconds | Maximum staleness = TTL + flush_interval = 70s. Acceptable for typeahead. |
| trending | 30 seconds | More time-sensitive. Shorter TTL shows awareness of freshness tradeoff. |

### 6.5 Invalidation Strategy

**Strategy: Write-time prefix invalidation.**

When a batch flushes and updates query `q`, delete all cache keys whose prefix matches any prefix of `q`:

```
For query "iphone 15":
  Invalidate: suggest:i, suggest:ip, suggest:iph, ..., suggest:iphone_15
```

O(len(query)) cache deletes per query per flush. Completely manageable.

**Alternative rejected:** TTL-only expiry. Makes the cache look broken during a demo when you search something and it doesn't appear immediately in suggestions.

**Chosen: Active invalidation on flush + TTL as safety net.**

### 6.6 Cache Freshness vs Latency vs Complexity

| Strategy | Freshness | Latency | Complexity |
|---|---|---|---|
| TTL only (60s) | Low | Very low | Low |
| Active invalidation on flush | High | Low | Medium |
| Write-through | Very high | Medium | High |
| No cache | Perfect | High | Low |

**Chosen: Active invalidation on flush.** Best balance for demo and marks.

---

## Section 7 — Consistent Hashing Design

### 7.1 Why Consistent Hashing?

Naive modular hashing: `node = hash(key) % num_nodes`. When you add or remove a node, every key remaps. In a 3-node system adding a 4th node remaps 75% of keys — massive cache invalidation storm.

Consistent hashing places both keys and nodes on a ring of 2^32 positions. A key is owned by the first node clockwise from its position. Adding a node only remaps keys between the new node and its predecessor — O(K/N) remapping instead of O(K).

### 7.2 Virtual Nodes

Without virtual nodes, 3 physical nodes create only 3 arcs on the ring. One arc might own 60% of the keyspace.

Each physical node maps to V virtual nodes. With V=150: approximately equal key distribution. Each virtual node is keyed as `"redis_node_0_replica_47"` → `hash(...)` → position on ring.

**Justification for V=150:** At V=10, standard deviation of key distribution is ~20%. At V=150, it drops to ~2%. Include this table in your README.

| V (virtual nodes) | Distribution StdDev |
|---|---|
| 10 | ~20% |
| 50 | ~7% |
| 150 | ~2% |
| 300 | ~1.5% |

### 7.3 Hash Ring Implementation Specification

```
Ring:
  nodes: SortedMap<int, string>   // ring_position → node_id

populate_ring(physical_nodes, virtual_node_count):
  for node in physical_nodes:
    for i in range(virtual_node_count):
      key = f"{node.id}_replica_{i}"
      position = md5(key) % 2^32
      ring[position] = node.id

get_node(cache_key):
  position = md5(cache_key) % 2^32
  candidates = ring.keys_greater_than_or_equal(position)
  if candidates is empty:
    return ring.first()   // wrap around
  return ring[candidates[0]]
```

**Hash function:** MD5 via `hashlib.md5`. Not Python's built-in `hash()` — it is not consistent across processes (seed randomisation).

### 7.4 Node Configuration for Local Development

```yaml
# docker-compose.yml
services:
  redis-0:
    image: redis:7
    ports: ["6379:6379"]
  redis-1:
    image: redis:7
    ports: ["6380:6379"]
  redis-2:
    image: redis:7
    ports: ["6381:6379"]
```

### 7.5 What the Debug Endpoint Must Show

```json
GET /cache/debug?prefix=iph

{
  "prefix": "iph",
  "cache_key": "suggest:iph",
  "hash_position": 2847392847,
  "assigned_node": "redis-1",
  "node_address": "localhost:6380",
  "virtual_node_responsible": "redis-1_replica_93",
  "cache_status": "HIT",
  "ttl_remaining_seconds": 47,
  "cached_results_count": 10
}
```

This single endpoint demonstrates your entire consistent hashing understanding in one response.

### 7.6 Node Addition/Removal Behaviour for Viva

**Adding a node:** New node inserted at V positions. Keys between new node and their previous successors now route to the new node. Cache misses repopulate naturally. No other keys affected.

**Removing a node:** All keys previously owned by removed node route to the next clockwise node. These will be cache misses initially, repopulate naturally.

---

## Section 8 — Trending System Design

### 8.1 Chosen Algorithm: Historical + Decayed Recent Count

This replaces the per-event exponential decay recommended in v1.0. Rationale in Section 3.3.

#### Formula

```
-- Applied on every batch flush:
hours_elapsed = (NOW() - last_decay_at) / 3600
new_recent_count = old_recent_count × e^(−λ × hours_elapsed) + delta

-- Trending score (used for ranking):
trending_score = historical_count + β × recent_count
```

Where:
- `λ = 0.5` → half-life of 1.38 hours. A search from 1h ago contributes 60% of its weight. A search from 6h ago contributes ~5%.
- `β = 10` → a recent search counts 10× more than an all-time search for ranking purposes. Tune this to make the demo clear.

#### Why λ = 0.5?

Half-life = ln(2) / 0.5 = 1.38 hours. "Trending now" intuitively means the last 1–2 hours. λ = 0.5 captures this. It is a tunable parameter — document this in README.

#### Why β = 10?

Without a scaling factor, `recent_count` (which decays and is always small) cannot compete with `historical_count` for a query with millions of all-time searches. β = 10 amplifies recency. Set it so that a query searched 50 times in the last hour beats one with 10,000 all-time searches and no recent activity.

**Demo validation:** Include in your dataset:
- "java tutorial" — historical_count: 40,000, recent_count: 0.2 (nearly decayed)
- "iphone 16 price" — historical_count: 1,000, recent_count: 45 (searched 50 times in last hour)

With β=10:
- java tutorial score: 40,000 + 10 × 0.2 = 40,002
- iphone 16 price score: 1,000 + 10 × 45 = 1,450

Still not enough — java tutorial wins. **This is intentional.** All-time dominance is correct when the gap is 40× and recency is modest. Make the demo show a query with historical_count ≤ 2,000 being beaten by a freshly searched one.

**Viva answer for β choice:** "β amplifies the recency signal so it's competitive with historical popularity. Setting β too high makes the system purely real-time. Too low makes recency irrelevant. We chose β=10 so that a query searched 100 times in the last hour competes with one with 1,000 all-time searches. This reflects the business intuition that fresh interest matters more than old popularity."

### 8.2 Update Flow

```
POST /search received
  ↓
batch_buffer.increment(query)

Batch flush triggered (every 10s or 100 writes):
  ↓
For each (query, delta) in snapshot:
  1. hours_elapsed = (NOW() - last_decay_at) / 3600
  2. new_recent = old_recent × e^(−0.5 × hours_elapsed) + delta
  3. UPSERT queries:
       historical_count += delta
       recent_count = new_recent
       last_decay_at = NOW()
  4. Update Trie node: trending_score = historical_count + 10 × recent_count
  5. Invalidate cache keys for all prefixes of query

GET /trending:
  SELECT query, (historical_count + 10 * recent_count) AS score
  FROM queries ORDER BY score DESC LIMIT 10
  ← Cached 30s in Redis node 0
```

### 8.3 What is Eliminated vs. Original Design

| Original (v1.0) | New (v2.0) | Reason |
|---|---|---|
| search_events table | Eliminated | Decay state lives in queries table |
| Background trending recompute task (every 60s) | Eliminated | Scores are up-to-date after each flush |
| Table scan of search_events | Eliminated | Trending is a simple ORDER BY |
| Per-event decay summation | Eliminated | Single per-query decay on flush |

**Net result:** 40% less implementation work, same marks, cleaner viva explanation.

---

## Section 9 — Batch Write Design

### 9.1 Architecture

```
POST /search receives query
        │
        ▼
  batch_buffer.increment(query)     ← O(1), in-memory, thread-safe
        │
        ▼
  Is flush triggered?
  ├── Time trigger: last_flush + 10s < now()
  └── Size trigger: len(buffer) >= 100
        │
        ▼ YES
  [Background thread / async task]
  1. snapshot = copy buffer; clear buffer
  2. For each (query, delta) in snapshot:
     a. Compute decay: new_recent = old_recent × e^(−λ × hours_elapsed) + delta
     b. UPSERT INTO queries
          SET historical_count = historical_count + delta,
              recent_count = new_recent,
              last_decay_at = NOW(),
              last_searched_at = NOW()
     c. Update trie node
     d. Invalidate all prefix cache keys for query
  3. Increment metrics: writes_executed += len(snapshot), writes_avoided += Σ(delta-1)
```

### 9.2 Thread Safety

Use snapshot pattern:

```python
# Python pseudocode
with lock:
    snapshot = dict(buffer)
    buffer.clear()
# Process snapshot without holding lock
```

In Node.js: single-threaded event loop means no lock needed, but async I/O means flush must use snapshot pattern (copy-on-clear).

### 9.3 Flush Triggers

| Trigger | Value | Rationale |
|---|---|---|
| Time-based | Every 10 seconds | Bounds maximum staleness. Shows tunable parameter. |
| Size-based | Every 100 entries | Prevents unbounded memory growth under spike traffic. |

### 9.4 Failure Modes and Crash Scenarios

| Scenario | Outcome | Mitigation |
|---|---|---|
| Application crashes mid-batch, buffer not flushed | Counts lost | Bounded loss: at most 100 events or 10s of writes |
| Crash during flush (after snapshot cleared) | Partial write | PostgreSQL UPSERT is atomic per-query. Partial flush: some queries updated, some not. |
| DB write fails after snapshot cleared | Events permanently lost | Keep snapshot until write succeeds. On failure, log snapshot to disk. |

**Viva answer for "what happens if the server crashes?":** "The batch buffer is in-memory and lost on crash. The maximum data loss is bounded by the flush interval — at most 10 seconds of searches. For an assignment demo this is acceptable. In production, I would use a write-ahead log: each POST /search appends to an append-only file. On startup, the server replays the WAL file and applies uncommitted batches before resuming normal operation."

### 9.5 Demonstrating Write Reduction

After sending 1000 search requests:

```
[BatchWriter] Summary:
  Searches received:       1000
  Unique queries in buffer: 43
  Flush events:            11
  DB writes executed:      43
  DB writes avoided:       957  (96% reduction)
```

This table must appear in your README benchmark section.

---

## Section 10 — Performance Plan

### 10.1 Expected Bottlenecks

| Path | Bottleneck | Mitigation |
|---|---|---|
| GET /suggest (cache hit) | Redis RTT (~0.5ms) | Already near-optimal |
| GET /suggest (cache miss) | Trie traversal (~5ms) | Trie is O(prefix_length). Uncommon after warmup. |
| POST /search | Batch buffer write (~0.1ms) | Lock contention under high concurrency. Use snapshot pattern. |
| GET /trending | ORDER BY on queries table | Index on computed expression. Cache result 30s. |
| Trie load on startup | Full table scan at boot | Accept once. ~100K rows loads in < 3s. |

### 10.2 Latency Expectations

| Scenario | Expected p50 | Expected p95 |
|---|---|---|
| Suggest (cache hit) | < 2ms | < 5ms |
| Suggest (cache miss, trie) | < 10ms | < 25ms |
| Suggest (cache miss, DB fallback) | < 30ms | < 80ms |
| POST /search | < 5ms | < 15ms |
| GET /trending (cached) | < 3ms | < 8ms |

### 10.3 Cache Hit Rate Expectations

- After warmup: **85–95%** for warm traffic
- On cold start: **~0%** → rises to 85% within 60 seconds

### 10.4 Write Reduction Expectations

- Zipfian traffic (realistic): **~90%** write reduction
- Uniform traffic: **~50%** write reduction

### 10.5 Metrics to Collect

| Metric | How | Where |
|---|---|---|
| Suggestion latency (p50, p95) | Timing middleware on `/suggest` | Logged per request |
| Cache hit rate | Counter: hits / (hits + misses) | Suggestion handler |
| Writes avoided | (searches - db_writes) / searches | Batch writer summary |
| Trie size | Node count at startup | Startup log |
| recent_count decay sample | Log before/after decay on flush | Batch flush handler |

---

## Section 11 — Observability Plan

### 11.1 Structured Logs

```
{timestamp, request_id, endpoint, prefix, cache_node, cache_hit, latency_ms, result_count}
```

Example:
```
2024-01-15T10:23:41Z suggest prefix=iph node=redis-1 hit=true latency_ms=1.4 results=10
2024-01-15T10:23:42Z suggest prefix=goo node=redis-0 hit=false latency_ms=8.2 results=10
2024-01-15T10:23:43Z search query=iphone15 buffer_size=47 flush_triggered=false
2024-01-15T10:23:50Z flush queries=43 db_writes=43 writes_avoided=957 duration_ms=24
```

### 11.2 Metrics Endpoint

```
GET /metrics

{
  "uptime_seconds": 3642,
  "trie": {
    "nodes": 287443,
    "queries_indexed": 100000
  },
  "cache": {
    "hits": 8472,
    "misses": 312,
    "hit_rate_percent": 96.4,
    "nodes": [
      { "id": "redis-0", "keys": 412, "memory_kb": 284 },
      { "id": "redis-1", "keys": 398, "memory_kb": 271 },
      { "id": "redis-2", "keys": 407, "memory_kb": 278 }
    ]
  },
  "batch_writer": {
    "searches_received": 9284,
    "flushes_executed": 94,
    "db_writes_executed": 843,
    "db_writes_avoided": 8441,
    "write_reduction_percent": 90.9,
    "buffer_current_size": 22
  },
  "consistent_hash": {
    "virtual_nodes_per_physical": 150,
    "total_virtual_nodes": 450,
    "key_distribution": { "redis-0": 33.1, "redis-1": 33.8, "redis-2": 33.1 }
  }
}
```

### 11.3 Demo Talking Points

1. **Cache routing in action:** `/cache/debug?prefix=sea` → shows which Redis node owns it.
2. **Batch write compression:** Send 50 searches for "iphone", 50 for "samsung". Show 2 DB writes in logs.
3. **Trending vs. static:** Show a recently searched query rising in `/trending`.
4. **Key distribution:** `/metrics` showing ~33% across 3 Redis nodes.
5. **Decay in action:** Search a query 20 times. Wait 5 minutes. Show `recent_count` decaying in logs.

---

## Section 12 — ADR Strategy

### 12.1 Why ADRs Matter for This Assignment

Architecture Decision Records (ADRs) are short documents that capture *what* was decided, *why*, and *what was rejected*. They demonstrate engineering maturity that most student submissions entirely lack.

**Benefits:**
- **Professionalism:** Every Staff Engineer knows that undocumented decisions become tech debt. ADRs show you think at that level.
- **Viva performance:** When the evaluator asks "why did you use X instead of Y?", your answer is already written. You reference the ADR. You don't fumble.
- **Marks uplift:** Most rubrics award marks for "justification of design choices". ADRs are explicit, scannable justification. They make the evaluator's job easy.

### 12.2 ADR File Structure

```
docs/
└── adrs/
    ├── 001-database-schema-design.md
    ├── 002-typeahead-engine-choice.md
    ├── 003-cache-architecture.md
    ├── 004-trending-algorithm.md
    ├── 005-batch-write-strategy.md
    └── 006-scope-boundaries.md
```

Each ADR follows this template:

```markdown
# ADR-NNN: [Short Title]

**Date:** YYYY-MM-DD
**Status:** Accepted

## Problem
[One paragraph: what decision needed to be made and why it mattered]

## Alternatives Considered
[Bullet list of options evaluated]

## Decision
[What was chosen and the one-sentence reason]

## Consequences
**Positive:** [What this enables]
**Negative:** [What is lost or accepted as a tradeoff]
**Neutral:** [What must be maintained as a result]
```

---

### 12.3 ADR-001: Database Schema Design

**Date:** Day 1  
**Status:** Accepted

**Problem:** Trending requires a recency signal. Two designs are possible: a separate `search_events` table storing raw events, or additional fields (`recent_count`, `last_decay_at`) on the `queries` table. The choice affects implementation complexity, query performance, and maintenance burden.

**Alternatives Considered:**
- Design A: `queries` + `search_events` (two tables). Trending engine scans raw events.
- Design B: `queries` with decay fields. Trending engine reads pre-computed scores.

**Decision:** Design B — single `queries` table with `historical_count`, `recent_count`, and `last_decay_at`. Decay is applied per batch flush, not per event.

**Consequences:**
- Positive: No table scan required for trending. Simpler write path. Easier to explain in viva.
- Negative: Raw events are not stored. Cannot retroactively recompute with a different λ.
- Neutral: Decay logic lives in the batch flush handler. Must be tested carefully.

---

### 12.4 ADR-002: Typeahead Engine Choice

**Date:** Day 1  
**Status:** Accepted

**Problem:** The `/suggest` endpoint requires prefix-matching over 100K queries. Three engines are viable: SQL LIKE with prefix index, in-process Trie, or Redis Sorted Sets.

**Alternatives Considered:**
- Option A: PostgreSQL prefix index (`text_pattern_ops`) only
- Option B: In-process Trie backed by PostgreSQL
- Option C: Redis Sorted Sets with prefix explosion

**Decision:** Option B — In-process Trie loaded from PostgreSQL at startup.

**Consequences:**
- Positive: O(prefix_length) lookup. No network round-trip. Demonstrates CS fundamentals. High viva marks.
- Negative: Trie is in-memory only. Counts are stale by one flush interval. ~30–60MB memory overhead.
- Neutral: Trie must be updated on every batch flush. Synchronisation logic required.

---

### 12.5 ADR-003: Cache Architecture

**Date:** Day 1  
**Status:** Accepted

**Problem:** The assignment requires a distributed cache with consistent hashing. The choice of implementation (logical simulation vs. real Redis nodes) affects whether the requirement is genuinely satisfied.

**Alternatives Considered:**
- Option A: Single Redis instance (fails requirement)
- Option B: Logical multi-node simulation (single process, N dicts)
- Option C: 3 real Redis instances via Docker Compose + application hash ring

**Decision:** Option C — 3 real Redis instances via Docker Compose.

**Consequences:**
- Positive: Genuinely distributed. Evaluator can observe actual network calls to different ports during demo.
- Negative: Docker dependency. Must document setup clearly.
- Neutral: Hash ring implemented in application layer. Must use a stable hash function (MD5, not Python built-in hash()).

---

### 12.6 ADR-004: Trending Algorithm

**Date:** Day 1  
**Status:** Accepted

**Problem:** The trending system must rank queries by recency, not just all-time count. Multiple algorithms exist with different implementation costs and explainability tradeoffs.

**Alternatives Considered:**
1. All-time count only (fails requirement)
2. Fixed time window (cliff effect)
3. Sliding window with timestamp log (requires search_events table)
4. Per-event exponential decay (mathematically elegant, high implementation cost)
5. Historical + Decayed Recent Count (chosen)

**Decision:** Option 5 — `trending_score = historical_count + β × recent_count`, where `recent_count` is decayed on every batch flush via `new_recent = old_recent × e^(−λ × hours_elapsed) + delta`.

**Consequences:**
- Positive: Smooth decay without cliff. No separate table. No table scans. Easy to explain.
- Negative: Cannot retroactively adjust λ. recent_count is a pre-aggregated signal, not raw events.
- Neutral: λ and β are tunable parameters that must be calibrated with demo data.

---

### 12.7 ADR-005: Batch Write Strategy

**Date:** Day 2  
**Status:** Accepted

**Problem:** `POST /search` must update query counts without creating a 1:1 write to the database on every request. Batch aggregation is required to demonstrate write optimisation.

**Alternatives Considered:**
- Immediate synchronous write (fails requirement)
- In-memory aggregation buffer with dual-trigger flush (chosen)
- Message queue (Kafka, RabbitMQ) — overkill
- Write-ahead log file — correct approach but too complex for demo scope

**Decision:** In-memory aggregation buffer. Flush triggered by time (every 10s) or size (≥100 entries), whichever fires first.

**Consequences:**
- Positive: Simple to implement. Easy to instrument. Demonstrates write reduction clearly.
- Negative: Data lost on crash. Bounded loss: at most 10s of writes or 100 events.
- Neutral: WAL documented as the production-grade extension in README.

---

### 12.8 ADR-006: Scope Boundaries

**Date:** Day 1  
**Status:** Accepted

**Problem:** The scope of this assignment is well-defined. Overengineering — adding Kafka, Elasticsearch, Redis Cluster, or WAL persistence — increases implementation time without proportional mark gain and introduces failure modes during the demo.

**Decision:** See Section 14 — What We Are Explicitly NOT Building.

**Consequences:**
- Positive: Focused, shippable system. All components fully understood by every team member.
- Negative: System does not reflect production-scale architecture.
- Neutral: Trade-offs explicitly documented in README as known limitations.

---

## Section 13 — Differentiation Features

### 13.1 Why Differentiation Matters

Most student submissions implement: Frontend → Backend → Redis → Postgres. The evaluator has seen this template 30 times before yours. Differentiation features are visible signals that your team went one level deeper.

The filter: **Does this feature take less than half a day to build and produce a visible demo artifact?** If not, it is not a differentiation feature — it is scope creep.

---

### 13.2 Feature Evaluation Matrix

| Feature | Implementation Effort | Demo Impact | Marks Impact | Viva Value | Recommendation |
|---|---|---|---|---|---|
| Cache Ring Visualizer | Low (2–3 hours) | Very High (visible, interactive) | High | High | **Build it** |
| Batch Writer Monitor | Low (2 hours) | High (live numbers) | High | High | **Build it** |
| Metrics Dashboard (`/metrics` page) | Low (2 hours, poll /metrics) | High (impresses during demo) | Medium | Medium | **Build it** |
| Request Flow Visualizer | Medium (4–6 hours) | Very High | High | High | **Build it** |
| Architecture Evolution View | High (6+ hours) | Medium | Low | Medium | Skip |
| Virtual Node Distribution Chart | Low (1 hour) | High | High | Very High | **Build it** |

---

### 13.3 Top 5 Recommended Differentiation Features

---

**Feature 1: Cache Ring Visualizer**

A frontend panel (or standalone page) that renders the consistent hash ring as a circle, with:
- Physical nodes labelled at their virtual node positions
- The current query's hash position highlighted
- An arc showing which node owns it

**How to build:** Use the `/cache/debug?prefix=X` endpoint to get `hash_position` and `assigned_node`. Render a `<canvas>` or SVG circle. Place node labels at evenly distributed positions. Draw a dot for the current query.

**Why it works:** The evaluator sees the ring. Not a description of it. The ring. This is the most memorable demo moment.

**Effort:** 2–3 hours (frontend only, uses existing API).

---

**Feature 2: Batch Writer Monitor**

A live panel (poll `/metrics` every 2 seconds) showing:
- Searches received (increments in real time)
- DB writes executed
- DB writes avoided
- Write reduction percentage (large number, prominently displayed)
- Current buffer size

**Why it works:** The evaluator can type searches in one window and watch the write reduction number change in real time. This visually proves the batch write system is working.

**Effort:** 2 hours (frontend panel + /metrics already planned).

---

**Feature 3: Request Flow Visualizer**

A log panel on the frontend showing the last 10 requests with annotations:

```
GET /suggest?q=iph → redis-1 (HIT) → 1.4ms
GET /suggest?q=goo → redis-0 (MISS) → trie → 8.2ms → cached
POST /search iphone15 → buffer[47] → flush pending
```

**Why it works:** Makes the system internals visible without any additional backend work. Just parse and display the structured log output from the backend.

**Effort:** 2–3 hours (requires structured log output, which is already planned).

---

**Feature 4: Virtual Node Distribution Chart**

A static table (or bar chart) in the frontend or README showing key distribution across nodes. Can be generated once at startup and served as a cached JSON response from `/cache/ring`.

```
redis-0: ████████████████████ 33.1%  (412 keys)
redis-1: ████████████████████ 33.8%  (398 keys)
redis-2: ████████████████████ 33.1%  (407 keys)
```

**Why it works:** Directly answers the evaluator's most likely question: "Is your key distribution actually uniform?" The chart makes it unarguable.

**Effort:** 1–2 hours (backend: compute distribution from ring; frontend: simple bar chart).

---

**Feature 5: Trending Decay Timeline**

A table in the UI (or in the README demo section) showing a specific query's recent_count at T=0, T=+1hr, T=+2hr, T=+4hr as it decays. Pre-generate this data and include it as a screenshot or live demo.

```
Query: "iphone 16 price"
  T+0h:   recent_count = 50.0   (just searched 50 times)
  T+1h:   recent_count = 30.3   (decay applied)
  T+2h:   recent_count = 18.4
  T+4h:   recent_count =  6.8
  T+12h:  recent_count =  0.07  (effectively zero)
```

**Why it works:** This is a concrete, numeric, visual proof that the decay formula is working. It answers the evaluator's question "how does your trending decay?" better than any verbal explanation.

**Effort:** 1–2 hours (instrument flush handler to log decay before/after; screenshot or chart the output).

---

## Section 14 — What We Are Explicitly NOT Building

This section exists to prevent scope creep. Every item here was considered and intentionally rejected.

---

**Kafka / Message Queues**

*Why excluded:* Kafka requires a separate broker, producer, consumer, and topic configuration. It adds 2–3 days of setup and debugging for no additional marks. The batch buffer already solves the write aggregation problem. Evaluators do not expect Kafka.

*If asked in viva:* "We considered Kafka for the write path. It would add durability and decoupling but requires a full broker deployment. For this assignment scope, our in-memory batch buffer with documented WAL extension achieves the same write reduction with 10% of the complexity."

---

**Elasticsearch**

*Why excluded:* Elasticsearch adds a heavy infrastructure dependency (JVM, cluster configuration, index mapping). Our Trie + PostgreSQL prefix index solves the prefix matching problem correctly and is completely transparent. Elasticsearch is a black box that is harder to explain in a viva.

*If asked in viva:* "At 10M+ queries, Elasticsearch would be the correct choice. At 100K queries, our Trie is faster, requires no external service, and is fully explainable."

---

**Redis Cluster**

*Why excluded:* Redis Cluster requires at minimum 3 master + 3 replica nodes, cluster configuration, and gossip protocol management. Our 3 independent Redis instances with application-layer consistent hashing satisfy the requirement and are far simpler to set up, explain, and demo.

*If asked in viva:* "Redis Cluster is the production solution. We implement the same consistent hashing principle at the application layer, which gives us full control and full transparency into the routing decisions."

---

**WAL (Write-Ahead Log) File Implementation**

*Why excluded:* WAL persistence is the correct crash-safe extension to the batch buffer. However, implementing it correctly (atomic append, replay on startup, truncation after successful flush) adds 1–2 days of work. The marks delta does not justify the time investment. We document it as the production extension in the README and the viva answer for crash scenarios.

*If asked in viva:* "The WAL extension is documented in our README. We prioritised implementing the in-memory buffer correctly and explaining the WAL extension thoroughly over implementing it partially."

---

**Distributed Trie**

*Why excluded:* A distributed Trie would require sharding the trie across nodes, routing prefix queries to the correct shard, and merging results. This is a genuine systems engineering problem but completely out of scope for this assignment. Our in-process Trie handles 100K queries with ~50MB RAM and sub-millisecond lookups.

*If asked in viva:* "For 1 billion queries, we would shard the Trie by first character (26 shards) and route queries to the appropriate shard. For 100K queries, this level of sharding is unnecessary."

---

**Complex Stream Processing (Flink, Spark Streaming)**

*Why excluded:* Stream processing frameworks are for multi-node, high-throughput event pipelines. Our trending system — historical_count + decayed recent_count — is correctly computed in a single PostgreSQL table with no streaming infrastructure needed.

---

**Full Analytics Dashboard (Grafana + Prometheus)**

*Why excluded:* A production-grade Grafana dashboard requires Prometheus configuration, metric exporters, and dashboard JSON setup. Our `/metrics` endpoint provides all required data. Building a lightweight frontend panel (Feature 2 above) achieves 80% of the visual impact at 10% of the cost.

---

**Multi-Region / Multi-Datacenter Design**

*Why excluded:* Out of scope. Single-region deployment assumed. CAP theorem implications documented in viva prep, not implemented.

---

## Section 15 — Implementation Roadmap

### Phase 0 — Dataset and Infrastructure (Day 1)
**Goal:** Have data in DB and services running.
**Deliverables:**
- Docker Compose: PostgreSQL + 3 Redis instances
- Dataset loaded: AOL Query Log (21M queries, aggregate to 100K unique)
- `queries` table created with all columns, indexed, seeded
- Backend skeleton with health check endpoint

**Validation:** `SELECT COUNT(*) FROM queries` returns ≥ 100,000. All Redis nodes respond to PING.
**Risk:** Dataset cleaning. Budget 2 hours for normalisation.

---

### Phase 1 — Trie and Suggestion API (Day 1–2)
**Goal:** Working `/suggest` endpoint, no cache yet.
**Deliverables:**
- Trie implementation (or use `pygtrie` and understand it fully)
- Trie loaded from DB on startup
- `GET /suggest?q=prefix` returns top-10 by trending_score
- Case normalisation and empty/whitespace handling

**Validation:** Manual testing with 10 prefixes. Response time < 50ms on cold path.

---

### Phase 2 — Consistent Hash Router + Cache (Day 2–3)
**Goal:** Suggestion reads go through distributed cache.
**Deliverables:**
- HashRing class: populate, get_node, describe_ring methods
- Cache manager: get/set/delete with node routing
- Suggestion handler: check cache first, populate on miss
- `GET /cache/debug` endpoint

**Validation:** 10 requests for same prefix → 9 cache hits. Debug endpoint shows correct routing.

---

### Phase 3 — Batch Writer with Decay (Day 3)
**Goal:** `POST /search` works, counts update, writes are batched, decay applied.
**Deliverables:**
- Batch buffer with lock-safe increment
- Background flush: dual trigger (10s/100 writes)
- UPSERT with decay computation on flush
- Trie count update on flush
- Cache prefix invalidation on flush
- `/metrics` endpoint with write reduction stats

**Validation:** Send 1000 POST /search requests. Observe < 50 DB writes in logs.

---

### Phase 4 — Trending Endpoint (Day 3–4)
**Goal:** `/trending` returns recency-aware results.
**Deliverables:**
- `GET /trending`: ORDER BY (historical_count + β × recent_count) DESC LIMIT 10
- Cached in Redis node 0 with 30s TTL
- Demo dataset prepared: fresh spiker vs. all-time popular
- Decay timeline log (for Feature 5 above)

**Validation:** After searching "new_query" 20 times, it appears in `/trending` within one flush cycle (10s).

---

### Phase 5 — Frontend + Differentiation Features (Day 4)
**Goal:** Working UI with all differentiation features.
**Deliverables:**
- Debounced search input (300ms)
- Suggestion dropdown with keyboard navigation
- Trending panel
- Cache Ring Visualizer (Feature 1)
- Batch Writer Monitor (Feature 2)
- Request Flow Log panel (Feature 3)
- Virtual Node Distribution Chart (Feature 4)

**Validation:** DevTools Network tab shows ≤ 2 requests when typing "iphon" rapidly.

---

### Phase 6 — Performance Measurement (Day 5)
**Goal:** Collect evidence for performance report.
**Deliverables:**
- Run 10,000 suggestion requests via script
- Collect p50, p95 latency split by cache hit/miss
- Cache hit rate after warmup
- Write reduction percentage
- Key distribution across Redis nodes

---

### Phase 7 — ADRs, README, and Demo Prep (Day 5–6)
**Goal:** Submission-ready documentation.
**Deliverables:**
- All 6 ADRs written (see Section 12)
- README (per Section 16)
- Architecture diagram
- Performance report table
- Trending decay timeline (Feature 5)

---

## Section 16 — README Strategy

### Required Sections

1. **Project Overview** — One paragraph. What it is, what it demonstrates.

2. **Architecture Diagram** — ASCII or image. Show all components and data flows.

3. **Technology Choices and Justification** — 1–2 sentences per choice.

4. **Quick Start:**
   ```
   git clone ...
   docker-compose up -d
   python ingest.py
   python app.py
   open http://localhost:8000
   ```

5. **Dataset** — Source, download instructions, processing, final row count.

6. **API Documentation** — Table: endpoint, method, params, response shape, example curl.

7. **System Design Decisions** — Reference each ADR by number. Include the trending formula with λ and β values and their justification.

8. **Performance Report:**

| Metric | Value |
|---|---|
| p50 suggest latency (cache hit) | X ms |
| p95 suggest latency (cache hit) | X ms |
| p50 suggest latency (cache miss) | X ms |
| Cache hit rate (after warmup) | X% |
| Searches in 60s window | X |
| DB writes in same 60s | X |
| Write reduction | X% |
| Key distribution | ~33% / ~33% / ~33% |

9. **Consistent Hashing Behaviour Log** — 20 lines of actual logs showing different prefixes routing to different nodes.

10. **Trending Demonstration** — Before/after table: same query list sorted by historical_count vs. trending_score. Include decay timeline for one query.

11. **Trade-offs and Known Limitations** — Reference Section 14.

12. **ADR Index** — Table listing all 6 ADRs with one-line summaries and links.

---

## Section 17 — Viva Preparation

### Top 50 Questions, Expected Answers, and Traps

**1. Why consistent hashing instead of modular hashing?**
*Expected:* Modular hashing remaps O(K) keys on node count change. Consistent hashing remaps only O(K/N). Adding a node causes a small, bounded miss storm rather than invalidating the entire cache.
*Trap:* "But you only have 3 nodes." → The design principle scales. We implemented it correctly so the system can grow without redesign.

---

**2. What are virtual nodes and why do you need them?**
*Expected:* Without virtual nodes, 3 physical nodes create only 3 arcs on the ring. One arc might span 70% of the keyspace. Virtual nodes spread each physical node into V positions. At V=150, each physical node owns ~33% of keys.
*Trap:* "What happens to virtual nodes when a physical node goes down?" → All V virtual nodes for that physical node become unreachable. Keys route to the next physical node's virtual nodes instead.

---

**3. What hash function do you use and why?**
*Expected:* MD5 via hashlib. Not Python's built-in `hash()` — it is seed-randomised per process and not consistent across restarts.
*Trap:* "Is MD5 a good hash for this?" → Cryptographic quality is irrelevant. MD5 distributes uniformly across the ring. MurmurHash3 is also acceptable and faster.

---

**4. How does your cache invalidation work?**
*Expected:* On batch flush, for each updated query, compute all its prefixes and delete those keys from their respective cache nodes. O(len(query)) DEL operations per query per flush.

---

**5. What is the TTL on your cache keys and why?**
*Expected:* 60s for suggestion keys. Maximum staleness = TTL + flush_interval = 70s. Acceptable for a typeahead. 30s for trending — more time-sensitive.

---

**6. What happens if a Redis node crashes?**
*Expected:* Only keys owned by that node become cache misses. All other nodes unaffected. Affected keys fall back to Trie/DB and repopulate on the next available node.
*Trap:* "Thundering herd?" → Yes. Multiple clients simultaneously miss and hit the DB. In production: probabilistic early expiry or distributed locks. Documented as known limitation.

---

**7. Walk me through a complete request from user typing "ip" to seeing suggestions.**
*Expected:* Normalise → hash ring → cache lookup → HIT: return immediately / MISS: Trie query → sort by trending_score → populate cache → return.

---

**8. What is your trending formula?**
*Expected:* `trending_score = historical_count + β × recent_count`. `recent_count` decays per flush: `new_recent = old_recent × e^(−λ × hours_elapsed) + delta`. λ=0.5, β=10.

---

**9. Why did you not use a separate search_events table?**
*Expected:* The decayed recent_count field on the queries table carries all the recency information needed. Applying decay on each flush eliminates the need for event storage or table scans. See ADR-001.

---

**10. What happens to your batch buffer if the server crashes?**
*Expected:* Data lost. Bounded: at most 10s or 100 events. In production: WAL extension. Each POST /search appends to an append-only file. On startup, replay uncommitted batches.

---

**11. How many DB writes are avoided by your batch writer?**
*Expected:* ~90% under Zipfian traffic. Show the metrics table from README.

---

**12. What is a UPSERT and why do you use it?**
*Expected:* `INSERT ... ON CONFLICT (query) DO UPDATE SET ...`. Atomically inserts or increments. Avoids SELECT + INSERT/UPDATE race condition.

---

**13. Why use a Trie instead of just querying PostgreSQL every time?**
*Expected:* O(prefix_length) lookup independent of dataset size. No network round-trip. Correct data structure for prefix enumeration.
*Trap:* "What if dataset is 1 billion queries?" → Trie won't fit in memory. Shard by first character, use an external typeahead service, or Elasticsearch.

---

**14. How does your Trie stay consistent with the database after writes?**
*Expected:* On each batch flush, we update Trie node counts and trending_scores for every query in the flush snapshot. Trie is at most one flush interval behind the DB.

---

**15. Why did you choose λ=0.5?**
*Expected:* Half-life = ln(2) / 0.5 = 1.38 hours. "Trending now" should mean the last 1–2 hours of activity. λ=0.5 captures this. It is a tunable parameter — we document the sensitivity.

---

**16. Why β=10 for the trending formula?**
*Expected:* Without β, recent_count (a small decayed float) cannot compete with historical_count (can be thousands). β=10 amplifies recency so that fresh activity is competitive with long-term popularity. Calibrated with demo data.

---

**17. How does debouncing work in your frontend?**
*Expected:* Delays the API call until N milliseconds after the last keystroke. If the user types "iphone" rapidly, only one request fires after the last key + 300ms.

---

**18. What is the key distribution across your cache nodes?**
*Expected:* ~33% each, as shown in `/metrics`. 150 virtual nodes per physical node produces 450 ring positions that spread keys uniformly.

---

**19. What would happen if you added a 4th cache node?**
*Expected:* The hash ring is updated with 150 new virtual positions. Roughly 25% of existing keys now route to the new node (cache misses initially). All other keys are unaffected.

---

**20. How is your trending different from just showing most searched?**
*Expected:* Explain decay formula. Show the demo data showing a fresh query beating a historically popular one.

---

**21. What trade-offs did you make in the batch writer design?**
*Expected:* Latency vs. durability. Low latency (return immediately) at the cost of potential data loss on crash. Bounded loss. WAL as the production-grade extension.

---

**22. What index type does PostgreSQL use for text_pattern_ops?**
*Expected:* B-tree, but collation-aware for prefix patterns. Standard B-tree cannot do prefix matching for non-C locales without text_pattern_ops.

---

**23. Why 150 virtual nodes and not 10?**
*Expected:* At V=10, key distribution has ~20% standard deviation across nodes. At V=150, ~2%. Show the table from Section 7.2.

---

**24. How do you handle mixed-case input?**
*Expected:* Normalise to lowercase before all operations — at search input, at cache key construction, at Trie lookup, at DB write.

---

**25. What happens if two threads flush simultaneously?**
*Expected:* Snapshot pattern with lock prevents double-flush. Lock is held only during the copy+clear of the buffer, not during DB writes.

---

**26. Is your cache write-through or cache-aside?**
*Expected:* Cache-aside (lazy population on read). Write-through would require updating cache on every batch flush, increasing coupling.

---

**27. What is the thundering herd problem?**
*Expected:* Multiple clients simultaneously miss the same cache key and all hit the DB. Mitigated by cache locking or probabilistic early expiry. Documented as a known limitation.

---

**28. Why not use Redis sorted sets for the Trie?**
*Expected:* Storage blowup: every query must be exploded into all its prefixes. "iphone" requires 6 insertions. Doesn't scale cleanly for large datasets.

---

**29. What is your dataset and why?**
*Expected:* AOL Query Log: 21M real queries, aggregable to 100K unique, free, directly applicable domain.

---

**30. How do you measure p95 latency?**
*Expected:* Sort all response times, take 95th percentile. Or use a histogram.

---

**31. What happens to trending if nobody searches anything for 24 hours?**
*Expected:* All recent_count values decay toward 0. Trending falls back to historical_count ordering. System degrades gracefully.

---

**32. How would you scale this to 10M queries per day?**
*Expected:* Separate typeahead service. Redis Cluster instead of 3 nodes. Kafka for write path. Flink for streaming trending computation. Trie sharded across nodes.

---

**33. What is write amplification?**
*Expected:* Each user action causing multiple underlying writes. We reduce from 1 DB write per search to ~1 DB write per N searches.

---

**34. How do you handle a prefix with no matches?**
*Expected:* Return empty array `[]` with HTTP 200.

---

**35. What is the CAP theorem and how does it apply here?**
*Expected:* CP on suggestion consistency (stale cache, not wrong data). AP on write path (batch writer accepts eventual consistency in exchange for availability).

---

**36. What is the time complexity of prefix lookup in your Trie?**
*Expected:* O(k) where k = prefix length. Independent of dataset size.

---

**37. What is the space complexity of your Trie?**
*Expected:* O(ALPHABET × N × avg_query_length) worst case. Prefix sharing reduces this in practice. Measured ~30–60MB for 100K queries.

---

**38. Why is the batch flush trigger dual (time AND size)?**
*Expected:* Time trigger bounds maximum staleness (10s). Size trigger prevents unbounded memory growth under spike traffic. Both run independently.

---

**39. What would you monitor in production?**
*Expected:* p99 suggestion latency, cache hit rate, batch buffer depth, flush failure rate, queries table size, Trie rebuild time.

---

**40. What is a hash ring collision?**
*Expected:* Two keys hashing to the same ring position. Extremely unlikely with 2^32 ring and uniform hash function. Handle by routing to the next clockwise node.

---

**41. Why document ADRs?**
*Expected:* ADRs capture what was decided and why. They prevent re-litigating past decisions and make the reasoning transparent to any engineer (or evaluator) reading the codebase.

---

**42. Which of your differentiation features are you most proud of?**
*Expected:* Cache Ring Visualizer — it makes the consistent hashing concept visible and tangible during the demo. No other submission will have this.

---

**43. What is cache stampede?**
*Expected:* Same as thundering herd. First miss triggers many simultaneous DB reads for the same key. Prevented by locking the first miss.

---

**44. What is your cache eviction policy?**
*Expected:* Keys expire via TTL. Redis evicts under memory pressure using LRU policy (`maxmemory-policy allkeys-lru`).

---

**45. How does your system behave during an offline demo?**
*Expected:* All components run locally via Docker. No external dependencies. Fully offline-capable.

---

**46. What is the difference between invalidation and expiry?**
*Expected:* Invalidation is proactive (delete the key now because it is stale). Expiry is passive (let it expire after TTL). We use both: active invalidation on flush, TTL as safety net.

---

**47. How long does Trie startup take?**
*Expected:* Benchmark this. Expected < 3 seconds for 100K queries at average length 15 chars.

---

**48. What is the maximum memory your Trie uses?**
*Expected:* Measure and report. Expected 30–100MB for 100K queries.

---

**49. If you had to redesign this with a 1-week timeline, what would you change?**
*Expected:* Add Redis Cluster, WAL for batch writes, Kafka for event stream, replace in-process Trie with a Trie service, add circuit breakers between cache and DB.

---

**50. What is the single most important thing you learned building this system?**
*Expected:* [Team's genuine answer. Prepare one. Evaluators remember authentic answers.]

---

## Section 18 — Critical Review

### 18.1 Identified Weaknesses

**W1: Trie + Batch flush consistency window**
- Problem: Between flush completing and cache being repopulated, concurrent cache miss reads from Trie. If Trie update is mid-flight, reader gets stale data.
- Severity: Low at demo scale.
- Mitigation: Apply Trie updates atomically with a brief lock. O(1) per node, negligible hold time.

**W2: Cold start performance**
- Problem: On startup, cache is empty. First 60 seconds of traffic hits Trie or DB.
- Mitigation: Cache warm-up after Trie loads: pre-compute suggestions for top 1000 single-character and two-character prefixes.

**W3: recent_count sensitivity to flush interval**
- Problem: If flush interval is 10s, decay is applied at most every 10 seconds. Between flushes, recent_count is not decayed. Minor inaccuracy.
- Severity: Low. Acceptable for assignment scope.
- Mitigation: Document as known approximation.

**W4: β calibration is demo-dependent**
- Problem: If β is wrong, the trending demo looks broken (fresh query never beats historical one, or junk always surfaces).
- Mitigation: Pre-calibrate with demo dataset. Include calibration reasoning in README.

**W5: Virtual node count not justified empirically**
- Problem: Evaluator may ask why 150 specifically.
- Mitigation: Include distribution table (Section 7.2) in README. Show simulation output.

**W6: No retry logic on DB write failure during flush**
- Problem: If flush snapshot is cleared and DB write fails, data is permanently lost.
- Mitigation: Keep snapshot in variable until write succeeds. On failure, log snapshot to disk. Increment `flush_failure_count` metric.

### 18.2 Overengineering Risks

- **Don't implement a real WAL file.** Document it.
- **Don't use Kafka.** Out of scope.
- **Don't implement a persistent distributed Trie.** In-memory + DB persistence is sufficient.
- **Don't build a full Grafana dashboard.** The `/metrics` frontend panel is sufficient.

### 18.3 Underengineering Risks

- **You MUST have actual data in 3 real Redis instances** (not simulated) OR clearly label and justify the simulation.
- **You MUST demonstrate trending vs. static ranking with real data.** The demo must show a query rising.
- **You MUST measure and report latency.** A performance report without actual numbers is penalised.
- **The debug endpoint MUST work during the demo.**

---

## Section 19 — Final Architecture Lock

> This section is the single source of truth for implementation. All decisions below are final. No further deliberation during implementation.

---

### 19.1 Exact Tech Stack

| Layer | Technology | Version | Notes |
|---|---|---|---|
| **Frontend** | Vanilla JS or React | Any | React preferred for component reuse (Ring Visualizer, Monitor panels) |
| **Backend** | FastAPI (Python) or Express (Node.js) | FastAPI 0.110+ / Express 4+ | FastAPI preferred: async support, auto-generated docs |
| **Database** | PostgreSQL | 15+ | Single instance, local or Docker |
| **Cache** | Redis | 7+ | 3 separate instances via Docker Compose |
| **Containerisation** | Docker Compose | v2 | Single `docker-compose.yml` for Postgres + 3 Redis |
| **Hash Function** | hashlib.md5 (Python) / crypto.createHash('md5') (Node) | stdlib | Do NOT use built-in `hash()` in Python |
| **Metrics** | Custom `/metrics` JSON endpoint | — | No Prometheus/Grafana |
| **Dataset** | AOL Query Log | 2006 | Pre-cleaned to 100K unique normalised queries |

---

### 19.2 Exact Data Model

```sql
-- Single table. No search_events.
CREATE TABLE queries (
    id                BIGSERIAL       PRIMARY KEY,
    query             TEXT            NOT NULL UNIQUE,
    historical_count  BIGINT          NOT NULL DEFAULT 0,
    recent_count      FLOAT           NOT NULL DEFAULT 0.0,
    last_decay_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    last_searched_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    created_at        TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- For /suggest: prefix scan
CREATE INDEX idx_query_prefix
    ON queries (query text_pattern_ops);

-- For /trending: sort by precomputed trending score
-- β=10 is baked into the index expression; change only if β changes
CREATE INDEX idx_trending_score
    ON queries ((historical_count + 10.0 * recent_count) DESC);
```

**No other tables.**

---

### 19.3 Exact APIs

Only the APIs that will actually be implemented:

| Method | Path | Params | Response | Notes |
|---|---|---|---|---|
| GET | `/suggest` | `?q=<prefix>` | `{ "results": [{"query": str, "score": float}] }` | Top 10, sorted by trending_score DESC |
| POST | `/search` | `{ "query": str }` body | `{ "message": "Searched" }` | Normalises query, increments buffer |
| GET | `/trending` | — | `{ "results": [{"query": str, "score": float}] }` | Top 10 by trending_score, cached 30s |
| GET | `/cache/debug` | `?prefix=<prefix>` | See 7.5 | Shows hash ring routing for given prefix |
| GET | `/cache/ring` | — | `{ "nodes": [...], "virtual_nodes": [...] }` | For Cache Ring Visualizer |
| GET | `/metrics` | — | See 11.2 | All observability data |
| GET | `/health` | — | `{ "status": "ok" }` | Liveness check |

**Not building:** `/search/results`, `/auth`, `/admin`, `/users`, any CRUD beyond the above.

---

### 19.4 Exact Cache Strategy

**Key schema:**

| Key | TTL | Node |
|---|---|---|
| `suggest:{lowercase_prefix}` | 60s | Determined by hash ring |
| `trending` | 30s | Fixed: redis-0 |
| `ring_state` | No TTL | Fixed: redis-0 |

**TTL:** 60s for suggestions, 30s for trending. No exceptions.

**Invalidation:** Write-time prefix invalidation on every batch flush.
- For each (query, delta) in flush snapshot:
  - Compute all prefixes of query: `["i", "ip", "iph", ..., "iphone_15"]`
  - For each prefix, compute `cache_key = "suggest:" + prefix`
  - Compute `node = hash_ring.get_node(cache_key)`
  - `redis_connections[node].delete(cache_key)`

**Routing:** Application-layer consistent hash ring. MD5 hash. 150 virtual nodes per physical node.

**Cold-start warm-up:** After Trie loads, pre-populate cache for all single-character and two-character prefixes (a–z, aa–zz). This is ~700 cache entries and covers ~90% of real traffic prefixes.

---

### 19.5 Exact Trending Strategy

**Formula:**
```
trending_score = historical_count + β × recent_count

β = 10  (amplifies recency signal)
```

**Decay (applied per batch flush):**
```
hours_elapsed = (NOW() - last_decay_at).total_seconds() / 3600
new_recent_count = old_recent_count × e^(−λ × hours_elapsed) + delta

λ = 0.5   (half-life = 1.38 hours)
```

**Fields updated on flush:**
- `historical_count += delta`
- `recent_count = new_recent_count`
- `last_decay_at = NOW()`
- `last_searched_at = NOW()`

**Trending query:**
```sql
SELECT query, (historical_count + 10.0 * recent_count) AS score
FROM queries
ORDER BY score DESC
LIMIT 10;
```

**Cached:** 30s TTL on Redis node 0, key `trending`. Invalidated after every batch flush.

**Demo calibration:** Ensure demo dataset contains at least one query with:
- `historical_count` ≤ 2,000
- `recent_count` ≥ 100 (searched 100+ times in the last hour)

This guarantees the trending demo shows visible rank change.

---

### 19.6 Exact Batch Strategy

**Buffer:** In-memory dictionary `{query: int}` mapping query to accumulated delta.

**Flush interval:** 10 seconds (time trigger).

**Flush threshold:** 100 unique queries in buffer (size trigger).

**Flush procedure:**
```
1. Acquire lock
2. snapshot = copy(buffer)
3. buffer.clear()
4. last_flush = NOW()
5. Release lock
6. For each (query, delta) in snapshot:
   a. Load current recent_count, last_decay_at from DB (or Trie)
   b. Compute decay and new_recent_count
   c. UPSERT with new values
   d. Update Trie node
   e. Invalidate prefix cache keys
7. Increment metrics: flushes_executed += 1, db_writes_executed += len(snapshot)
8. Log flush summary
```

**Failure handling:** If DB write fails, log snapshot to stderr and increment `flush_failure_count`. Do not silently discard.

**Metrics tracked:**
- `searches_received`
- `flushes_executed`
- `db_writes_executed`
- `db_writes_avoided = searches_received - db_writes_executed`
- `flush_failure_count`
- `buffer_current_size` (real-time)

---

### 19.7 Final Repository Structure

```
search-typeahead/
├── docker-compose.yml              # Postgres + 3 Redis instances
├── README.md                       # Full documentation per Section 16
│
├── docs/
│   └── adrs/
│       ├── 001-database-schema-design.md
│       ├── 002-typeahead-engine-choice.md
│       ├── 003-cache-architecture.md
│       ├── 004-trending-algorithm.md
│       ├── 005-batch-write-strategy.md
│       └── 006-scope-boundaries.md
│
├── scripts/
│   ├── ingest.py                   # Load AOL dataset into PostgreSQL
│   ├── benchmark.py                # Send 10K requests, collect latency
│   └── seed_demo.py                # Inject demo trending data
│
├── backend/
│   ├── main.py                     # FastAPI app, route definitions
│   ├── config.py                   # λ, β, flush_interval, node config
│   │
│   ├── trie/
│   │   ├── __init__.py
│   │   ├── node.py                 # TrieNode class
│   │   └── trie.py                 # Trie class: insert, search, update
│   │
│   ├── cache/
│   │   ├── __init__.py
│   │   ├── hash_ring.py            # HashRing class: populate, get_node
│   │   └── cache_manager.py        # get/set/delete with ring routing
│   │
│   ├── batch/
│   │   ├── __init__.py
│   │   └── batch_writer.py         # BatchBuffer: increment, flush, metrics
│   │
│   ├── trending/
│   │   ├── __init__.py
│   │   └── engine.py               # trending_score computation, /trending endpoint
│   │
│   ├── db/
│   │   ├── __init__.py
│   │   ├── connection.py           # PostgreSQL connection pool
│   │   └── queries.py              # UPSERT, SELECT functions
│   │
│   └── middleware/
│       ├── __init__.py
│       └── timing.py               # p50/p95 latency collection
│
└── frontend/
    ├── index.html
    ├── app.js                      # Main app: debounced suggest, trending panel
    ├── ring_visualizer.js          # Cache Ring Visualizer (Feature 1)
    ├── batch_monitor.js            # Batch Writer Monitor (Feature 2)
    ├── request_flow.js             # Request Flow Log panel (Feature 3)
    └── styles.css
```

---

### 19.8 Final Implementation Sequence

Ordered by dependency. Do not begin a phase before validating the previous one.

| # | Task | Owner | Day | Validation |
|---|---|---|---|---|
| 1 | Write `docker-compose.yml` with Postgres + 3 Redis | Anyone | 1 | All containers start. Redis PING responds on ports 6379/6380/6381. |
| 2 | Create `queries` table with all columns and indexes | Anyone | 1 | `\d queries` shows all columns and indexes. |
| 3 | Write `ingest.py`, load 100K AOL queries | Anyone | 1 | `SELECT COUNT(*) FROM queries` = 100,000. |
| 4 | Implement `TrieNode` and `Trie` classes | Dev A | 1–2 | Unit test: insert 5 queries, search prefix, get correct top-3. |
| 5 | Load Trie from DB on startup | Dev A | 2 | Startup log shows "Loaded 100000 queries into Trie in X seconds." |
| 6 | Implement `GET /suggest` using Trie (no cache) | Dev A | 2 | `curl /suggest?q=iph` returns 10 results, correct prefix match. |
| 7 | Implement `HashRing` class | Dev B | 2 | Unit test: 1000 random keys, verify ~33% distribution per node. |
| 8 | Implement `CacheManager` with ring routing | Dev B | 2–3 | Set key, verify it lands on correct node via debug. |
| 9 | Wire cache into `/suggest`: check-miss-populate | Dev B | 3 | 10 identical requests → 9 hits logged. |
| 10 | Implement `GET /cache/debug` endpoint | Dev B | 3 | Response matches schema in 7.5. |
| 11 | Implement `BatchWriter` with increment + snapshot flush | Dev A | 3 | 1000 POST /search → < 50 DB writes in logs. |
| 12 | Add decay computation to flush handler | Dev A | 3 | Log shows `recent_count` before and after decay on each flush. |
| 13 | Wire Trie update and cache invalidation into flush | Dev A | 3 | After flush, new query appears in `/suggest` for its prefix. |
| 14 | Implement `GET /trending` endpoint with cache | Dev B | 3–4 | After seeding demo data, trending returns fresh query above historical one. |
| 15 | Implement `GET /metrics` endpoint | Anyone | 4 | All fields present. Write reduction > 50% during benchmark. |
| 16 | Implement cache warm-up on startup | Dev A | 4 | After startup, hit rate > 50% immediately (no cold period). |
| 17 | Build frontend: debounced search + dropdown | Dev C | 4 | Network tab shows ≤2 requests for rapid typing of "iphon". |
| 18 | Build Trending panel | Dev C | 4 | Trending list updates after searching new query 20 times. |
| 19 | Build Cache Ring Visualizer | Dev C | 4–5 | Ring renders correctly. Typing a prefix shows the owning node highlighted. |
| 20 | Build Batch Writer Monitor | Dev C | 5 | Real-time numbers update. Write reduction visible. |
| 21 | Build Request Flow Log panel | Dev C | 5 | Log shows cache node, hit/miss, latency per request. |
| 22 | Run benchmark script (10K requests) | Anyone | 5 | Collect p50, p95 latency. Cache hit rate. Write reduction. |
| 23 | Calibrate β with demo dataset | Dev A | 5 | Fresh query (100 recent searches) beats historical (2000 all-time) in trending. |
| 24 | Write all 6 ADRs | Dev B | 5–6 | Each ADR follows the template in Section 12.2. |
| 25 | Write README | Anyone | 6 | All sections in 16 present. Quick Start works in one copy-paste. |
| 26 | Demo dry run | All | 6 | All viva questions in Section 17 answered correctly without notes. |

---

*Blueprint version 2.0 — Reviewed by Staff Engineer persona. All 7 feedback items addressed. No wholesale rewrites. Only high-value targeted changes.*

*Every recommendation answers: "Does this increase marks, improve viva performance, or reduce implementation risk?" If not, it was rejected.*