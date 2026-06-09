typeaheadx/

Frontend
---------
Next.js 15
TypeScript
Tailwind
shadcn/ui

Backend
--------
Python 3.13
FastAPI

Database
--------
PostgreSQL 17

Cache
-----
Redis 7
(3 instances)

ORM
---
SQLAlchemy

Testing
-------
pytest

Containerization
----------------
Docker Compose

Observability
-------------
Custom /metrics endpoint

Hashing
-------
MD5

Typeahead Engine
----------------
Phase 1:
PostgreSQL Prefix Search

Phase 8:
Trie (only if benchmark justifies)

Trending
--------
Historical Count
+
Decayed Recent Count

Batch Writes
------------
In-memory aggregation buffer
10 sec flush
100 write flush