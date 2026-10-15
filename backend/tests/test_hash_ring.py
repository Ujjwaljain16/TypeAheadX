import collections
import os
import subprocess
import sys

import pytest

from app.cache.consistent_hash_ring import ConsistentHashRing

NODES = ["redis-a", "redis-b", "redis-c"]
KEYS = [f"suggestion:key{i}" for i in range(20_000)]


def build(nodes=NODES, vnodes=500):
    r = ConsistentHashRing(virtual_nodes=vnodes)
    for n in nodes:
        r.add_node(n)
    return r


def test_empty_ring_returns_none():
    assert ConsistentHashRing().get_node("x") is None


def test_deterministic_across_instances_and_insertion_order():
    a, b = build(NODES), build(list(reversed(NODES)))
    assert all(a.get_node(k).physical_node == b.get_node(k).physical_node for k in KEYS[:2000])


def test_deterministic_across_processes_with_different_hash_seeds():
    """Cross-process consistency matters when several API instances route to the same Redis fleet."""
    code = ("from app.cache.consistent_hash_ring import ConsistentHashRing;"
            "r=ConsistentHashRing(500);[r.add_node(n) for n in ['redis-a','redis-b','redis-c']];"
            "print(''.join(r.get_node(f'suggestion:key{i}').physical_node[-1] for i in range(500)))")
    outs = set()
    for seed in ("1", "99", "random"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        outs.add(subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env,
                                cwd=os.path.dirname(os.path.dirname(__file__)), check=True).stdout)
    assert len(outs) == 1


def test_key_distribution_within_tolerance():
    ring = build()
    dist = collections.Counter(ring.get_node(k).physical_node for k in KEYS)
    for n in NODES:
        share = dist[n] / len(KEYS)
        assert 0.28 < share < 0.39, dist     # measured spread for 500 vnodes is about +-3 points


def test_adding_a_node_moves_roughly_one_over_n_keys_and_only_to_the_new_node():
    before, after = build(NODES), build(NODES + ["redis-d"])
    moved = [k for k in KEYS if before.get_node(k).physical_node != after.get_node(k).physical_node]
    assert all(after.get_node(k).physical_node == "redis-d" for k in moved)
    assert 0.18 < len(moved) / len(KEYS) < 0.33    # ideal is 25%


def test_removing_a_node_only_remaps_that_nodes_keys_and_is_reversible():
    full = build(NODES)
    r = build(NODES)
    r.remove_node("redis-b")
    for k in KEYS[:5000]:
        old = full.get_node(k).physical_node
        new = r.get_node(k).physical_node
        assert new != "redis-b"
        if old != "redis-b":
            assert new == old
    r.add_node("redis-b")
    assert all(r.get_node(k).physical_node == full.get_node(k).physical_node for k in KEYS[:5000])


def test_duplicate_add_is_idempotent_and_remove_unknown_is_noop():
    r = build()
    n = len(r.ring)
    r.add_node("redis-a")
    r.remove_node("nope")
    assert len(r.ring) == n == 1500 and len(set(r.ring)) == n


def test_wraparound_maps_to_first_position():
    r = build()
    k = next(k for k in KEYS if r._hash(k) > r.ring[-1] or True)
    assert r.get_node(k) is not None
    # force a hash above the last ring position
    r._hash = lambda key: r.ring[-1] + 1
    assert r.get_node("anything").hash_value == r.ring[0]
