"""Selective mutation testing: re-introduce each defect found in the audit into a throw-away copy of
backend/ and check that the test-suite FAILS (mutant killed). A surviving mutant means the suite cannot
detect that regression.   python benchmarks/mutation_smoke.py   (needs the integration env, see env.sh)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"

# (id, description, file, old, new, test files that should notice)
MUTANTS = [
    ("M1", "invalidation deletes 'suggest:<p>' while reads use 'suggestion:<p>' (original F-003)", "app/write_buffer/batch_worker.py",
     "[suggestion_cache_key(prefix) for prefix in prefixes]", '[f"suggest:{prefix}" for prefix in prefixes]',
     ["tests/test_batch_worker.py", "tests/test_api_integration.py"]),
    ("M2", "LIKE input not escaped (original F-002)", "app/repositories/query_repository.py",
     'escape_like(prefix) + "%"', 'prefix + "%"', ["tests/test_repository_pg.py", "tests/test_api_integration.py"]),
    ("M3", "write path skips validation (original F-004/F-005)", "app/api/search.py",
     'query = validate_text(request.query, settings.max_query_length, what="query")',
     'query = " ".join(request.query.strip().lower().split()) or (_ for _ in ()).throw(EmptyText("x"))',
     ["tests/test_api_integration.py"]),
    ("M4", "failed flush discards events instead of re-queueing (original F-005)", "app/write_buffer/batch_worker.py",
     "lost = self.buffer.merge(pending)", "lost = sum(pending.values())", ["tests/test_batch_worker.py"]),
    ("M5", "upsert overwrites instead of accumulating (lost update class)", "app/repositories/query_repository.py",
     "historical_count = queries.historical_count + EXCLUDED.historical_count",
     "historical_count = EXCLUDED.historical_count", ["tests/test_repository_pg.py"]),
    ("M6", "circuit breaker never opens (original F-007)", "app/cache/redis_node.py",
     "if self._open_until == 0.0:\n                return True", "if True:\n                return True", ["tests/test_cache_resilience.py"]),
    ("M7", "write buffer unbounded (original F-011)", "app/write_buffer/buffer.py",
     "if query not in self._buffer and len(self._buffer) >= self.max_unique:\n                return False",
     "if False:\n                return False", ["tests/test_write_buffer.py", "tests/test_api_integration.py"]),
    ("M8", "no bisect: poison row kills the batch (original F-005)", "app/write_buffer/batch_worker.py",
     "if len(snapshot) == 1:", "if True:", ["tests/test_batch_worker.py"]),
    ("M9", "upsert rows not ordered: concurrent flushers can deadlock", "app/repositories/query_repository.py",
     "    ORDER BY t.q\n", "", ["tests/test_repository_pg.py"]),
    ("M10", "node-down-at-startup never retried (original F-008)", "app/cache/redis_node.py",
     "self._open_until = self._clock() + self.breaker_seconds * jitter", "self._open_until = float('inf')", ["tests/test_cache_resilience.py"]),
    ("M13", "redis client keeps the library's default retries (outage amplification, found during the audit)", "app/cache/redis_node.py",
     "retry=Retry(NoBackoff(), 0),", "", ["tests/test_cache_resilience.py"]),
    ("M11", "ring ignores wrap-around", "app/cache/consistent_hash_ring.py",
     "if idx == len(self.ring):\n            idx = 0", "if idx == len(self.ring):\n            idx = len(self.ring) - 1", ["tests/test_hash_ring.py"]),
    ("M12", "normalization stops lower-casing", "app/services/normalization.py",
     ".strip().lower().split()", ".strip().split()", ["tests/test_normalization.py", "tests/test_service.py", "tests/test_api_integration.py"]),
]


def main():
    results = []
    for mid, desc, rel, old, new, tests in MUTANTS:
        tmp = Path(tempfile.mkdtemp(prefix="mut_"))
        try:
            shutil.copytree(BACKEND, tmp / "backend", ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".env"))
            f = tmp / "backend" / rel
            src = f.read_text(encoding="utf-8")
            pairs = old if isinstance(old, list) else [(old, new)]
            if any(o not in src for o, _ in pairs):
                results.append({"id": mid, "desc": desc, "status": "NOT-APPLIED (pattern missing)"})
                continue
            for o, n in pairs:
                src = src.replace(o, n, 1)
            f.write_text(src, encoding="utf-8")
            args = [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *(tests or ["tests"])]
            p = subprocess.run(args, cwd=tmp / "backend", env=os.environ.copy(), capture_output=True, text=True, timeout=900)
            status = "KILLED" if p.returncode != 0 else "SURVIVED"
            last = [l for l in p.stdout.strip().splitlines() if l.strip()][-1:]
            results.append({"id": mid, "desc": desc, "status": status, "pytest_tail": last})
            print(mid, status, desc, flush=True)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    out = REPO / "audit" / "results" / "experiments"
    out.mkdir(parents=True, exist_ok=True)
    (out / "mutation_smoke.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    killed = sum(r["status"] == "KILLED" for r in results)
    print(f"killed {killed}/{len(results)}")


if __name__ == "__main__":
    main()
