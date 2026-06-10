# TypeAheadX Backend

This is the core engine of TypeAheadX. It is a high-performance Python application built with **FastAPI**, designed to handle massive read concurrency while absorbing viral write spikes safely.

---

## 1. Architecture Overview

The backend is built around a CQRS (Command Query Responsibility Segregation) philosophy, strictly separating the Read and Write paths:

- **The Read Path** is completely shielded by a custom **Distributed Caching Engine** implementing a 128-bit MD5 Consistent Hash Ring across multiple Redis nodes.
- **The Write Path** is decoupled from the API via an **Asynchronous Write Buffer** that aggregates Zipfian traffic in-memory and flushes to PostgreSQL in the background.

---

## 2. Codebase Structure

The backend is organized by domain responsibilities:

### `/app`
- `/api`: FastAPI routers (`/suggest`, `/search`, `/metrics`, `/cache/debug`).
- `/cache`: The core distributed cache logic. Contains the `CacheInterface`, `ConsistentHashRing`, `RedisNode` connections, and `CacheMetrics` singleton.
- `/write_buffer`: The asynchronous daemon thread that utilizes a "Lock and Swap" in-memory dictionary to protect PostgreSQL from connection exhaustion.
- `/services`: Contains `trending_calculator.py`, which executes the inline exponential decay mathematics for calculating query popularity.
- `/repositories`: Data access layer for executing optimized PostgreSQL B-Tree queries and bulk `UPSERT` statements.

### `Root Level`
- `schema.sql`: Defines the `queries` table, the `text_pattern_ops` B-Tree prefix index, and the composite trending index.
- `migrate.py`: Simple migration script to add columns and indexes.
- `ingest.py`: High-performance bulk ingestion script that safely loads 150,000 queries from `data/processed/queries.csv`.

---

## 3. Storage Foundation

The source of truth is PostgreSQL. While Tries are the textbook data structure for autocomplete, they lack durable persistence and clustering. By leveraging PostgreSQL's B-Tree index with `text_pattern_ops`, we achieved exceptional performance for prefix matching (`LIKE 'prefix%'`). 

Because our caching hit rate averages **97%+**, PostgreSQL's primary job is acting as a highly durable cold-storage engine and asynchronous trending aggregator, not a real-time read replica.

---

## 4. Development Setup

**1. Environment Variables:**
```bash
cp .env.example .env
```

**2. Virtual Environment:**
```bash
python -m venv .venv
# Activate: .venv\Scripts\activate (Windows) or source .venv/bin/activate (Mac/Linux)
pip install -r requirements.txt
```

**3. Initialize Database:**
Assuming your PostgreSQL instance is running on port 5432 (via `docker-compose up -d` at the project root):
```bash
python migrate.py
python ingest.py
```

**4. Start API:**
```bash
uvicorn app.main:app --reload --port 8000
```
