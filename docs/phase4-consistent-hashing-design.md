# Phase 4: Consistent Hashing Design

## Architecture Philosophy
TypeAheadX transitioned from a single Redis instance into a fully distributed caching tier using **Consistent Hashing**.

If we simply used naive modulo hashing (`hash(key) % N`), adding or removing a node would completely shuffle the keyspace. In a cluster of 3 nodes, adding a 4th node would invalidate ~75% of the cache, causing a "cache avalanche" that would crush PostgreSQL.

Instead, we map both **keys** and **nodes** onto a 128-bit ring using `hashlib.md5`. A key is owned by the first node found moving clockwise around the ring.

## Virtual Nodes
A core problem with consistent hashing is uneven distribution. If we only place 3 physical nodes on the ring, one node might randomly own 70% of the keyspace.

To solve this, we assign **150 Virtual Nodes** (replicas) per physical node. 
- `redis-a` generates `redis-a_replica_0` through `redis-a_replica_149`
- These 450 total points spread out evenly across the 128-bit integer space.
- This dramatically reduces standard deviation and mathematically ensures each physical node receives roughly ~33% of the cache load.

## Graceful Degradation
The `DistributedCache` class maintains the resiliency we introduced in Phase 3. 
If `redis-b` crashes:
1. Keys owned by `redis-a` and `redis-c` continue serving sub-millisecond responses.
2. Keys owned by `redis-b` encounter a connection error.
3. The system catches the error natively, increments `errors`, and silently queries PostgreSQL.
4. The user never sees a 500.

## The Debug Endpoint
To prove this architecture works transparently, we enhanced `/cache/debug`. 

Example response for `iph`:
```json
{
  "key": "suggestion:iph",
  "provider": "distributed",
  "node": "redis-a",
  "hash": 1823901283019283102,
  "virtual_node": "redis-a_replica_47",
  "exists": true,
  "ttl": 284
}
```
This single endpoint proves the entire distributed systems narrative.
