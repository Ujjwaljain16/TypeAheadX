"""Shared helpers: server lifecycle, infrastructure counters, environment metadata."""
from __future__ import annotations

import gzip
import json
import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil
import psycopg
import redis
import requests

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable
PG_DSN = os.environ.get("PG_DSN", "postgresql://postgres:postgres@localhost:47433/typeaheadx")
REDIS_PORTS = [47379, 47380, 47381]
CONTAINERS = {"pg": "taxaudit-postgres", "redis-a": "taxaudit-redis-a",
              "redis-b": "taxaudit-redis-b", "redis-c": "taxaudit-redis-c"}
BASE_URL = "http://127.0.0.1:8000"


def audit_env(extra: dict | None = None) -> dict:
    env = os.environ.copy()
    env.update({
        "DATABASE_URL": PG_DSN.replace("postgresql://", "postgresql+psycopg://"),
        "REDIS_NODES": ",".join(f"localhost:{p}" for p in REDIS_PORTS),
        "REDIS_URL": f"redis://localhost:{REDIS_PORTS[0]}",
        "CACHE_PROVIDER": "distributed", "VIRTUAL_NODES": "500",
        "PYTHONUNBUFFERED": "1",
    })
    env.update(extra or {})
    return env


# ---------------------------------------------------------------- server
class Server:
    def __init__(self, code_dir: Path, workers: int = 1, extra_env: dict | None = None,
                 log_path: Path | None = None, extra_args: list[str] | None = None):
        self.code_dir = Path(code_dir)
        self.workers = workers
        self.extra_env = extra_env or {}
        self.log_path = log_path or (Path(os.environ.get("TEMP", ".")) / "taxaudit_server.log")
        self.extra_args = extra_args or []
        self.proc: subprocess.Popen | None = None

    def start(self, timeout=45):
        self.stop()
        log = open(self.log_path, "wb")
        cmd = [PY, "-m", "uvicorn", "app.main:app", "--port", "8000", "--host", "127.0.0.1",
               "--log-level", "warning", "--workers", str(self.workers), *self.extra_args]
        self.proc = subprocess.Popen(cmd, cwd=str(self.code_dir / "backend"),
                                     env=audit_env(self.extra_env), stdout=log, stderr=subprocess.STDOUT)
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                if requests.get(BASE_URL + "/health", timeout=1).status_code == 200:
                    time.sleep(1.0)
                    return
            except Exception:
                time.sleep(0.3)
        raise RuntimeError("server did not become healthy; see " + str(self.log_path))

    def tree(self) -> list[psutil.Process]:
        if not self.proc:
            return []
        try:
            p = psutil.Process(self.proc.pid)
            return [p] + p.children(recursive=True)
        except psutil.NoSuchProcess:
            return []

    def stop(self):
        if self.proc is None:
            return
        for p in self.tree():
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass
        try:
            self.proc.wait(timeout=10)
        except Exception:
            pass
        self.proc = None
        time.sleep(0.5)


class ResourceSampler(threading.Thread):
    """Samples CPU% (of one core, summed over the server process tree) and RSS."""

    def __init__(self, server: Server, interval=0.5):
        super().__init__(daemon=True)
        self.server, self.interval = server, interval
        self.samples: list[tuple[float, float, int, int]] = []
        self._stop_evt = threading.Event()

    def run(self):
        procs: dict[int, psutil.Process] = {}
        last_refresh = 0.0
        while not self._stop_evt.is_set():
            now = time.time()
            if now - last_refresh > 5.0:  # enumerating the tree is slow on Windows; do it rarely
                for p in self.server.tree():
                    procs.setdefault(p.pid, p)
                last_refresh = now
            cpu, rss, thr = 0.0, 0, 0
            for pr in list(procs.values()):
                try:
                    cpu += pr.cpu_percent(interval=None)
                    rss += pr.memory_info().rss
                except psutil.Error:
                    pass
            self.samples.append((now, cpu, rss, thr))
            time.sleep(self.interval)

    def stop(self) -> dict:
        self._stop_evt.set()
        self.join(timeout=3)
        s = self.samples[2:] or self.samples  # drop first (cpu_percent primes at 0)
        if not s:
            return {}
        cpus = [x[1] for x in s]
        return {"server_cpu_pct_mean": round(sum(cpus) / len(cpus), 1), "server_cpu_pct_max": round(max(cpus), 1),
                "server_rss_mb_max": round(max(x[2] for x in s) / 2**20, 1),
                "server_threads_max": max(x[3] for x in s), "n_samples": len(s)}


def docker_stats() -> dict:
    """One-shot CPU%/mem of the four containers (docker stats --no-stream)."""
    try:
        out = subprocess.run(["docker", "stats", "--no-stream", "--format",
                              "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}"], capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return {}
    res = {}
    for line in out.splitlines():
        n, c, m = line.split("|")
        if n.startswith("taxaudit-"):
            res[n] = {"cpu": c, "mem": m}
    return res


# ---------------------------------------------------------------- infra counters
def pg_conn():
    return psycopg.connect(PG_DSN, autocommit=True)


_PG = None
_REDIS = None
_HTTP = requests.Session()


def _pg_persistent():
    global _PG
    if _PG is None or _PG.closed:
        _PG = pg_conn()
    return _PG


def pg_snapshot() -> dict:
    # persistent connection: opening one inside the load generator process perturbs dispatch timing
    if True:
        c = _pg_persistent()
        r = c.execute("""SELECT xact_commit+xact_rollback, blks_hit, blks_read, tup_returned, tup_fetched,
                                tup_inserted, tup_updated, deadlocks, temp_files
                           FROM pg_stat_database WHERE datname = current_database()""").fetchone()
        act = c.execute("SELECT count(*) FILTER (WHERE state='active'), count(*) FROM pg_stat_activity "
                        "WHERE datname = current_database()").fetchone()
    return {"xacts": r[0], "blks_hit": r[1], "blks_read": r[2], "tup_returned": r[3], "tup_fetched": r[4],
            "tup_inserted": r[5], "tup_updated": r[6], "deadlocks": r[7], "temp_files": r[8],
            "active_conns": act[0], "total_conns": act[1]}


def redis_clients():
    global _REDIS
    if _REDIS is None:
        _REDIS = [redis.Redis(port=p, decode_responses=True, socket_timeout=2) for p in REDIS_PORTS]
    return _REDIS


def redis_snapshot() -> dict:
    out = {}
    for name, c in zip("abc", redis_clients()):
        try:
            st, mem = c.info("stats"), c.info("memory")
            out[name] = {"hits": st["keyspace_hits"], "misses": st["keyspace_misses"],
                         "cmds": st["total_commands_processed"], "evicted": st["evicted_keys"],
                         "expired": st["expired_keys"], "mem_mb": round(mem["used_memory"] / 2**20, 2),
                         "keys": c.dbsize()}
        except Exception as e:
            out[name] = {"error": type(e).__name__}
    return out


def diff_snap(a: dict, b: dict) -> dict:
    out = {}
    for k, v in b.items():
        if isinstance(v, dict):
            out[k] = diff_snap(a.get(k, {}), v)
        elif isinstance(v, (int, float)) and isinstance(a.get(k), (int, float)):
            out[k] = round(v - a[k], 3)
    return out


def flush_redis():
    for c in redis_clients():
        try:
            c.flushall()
        except Exception:
            pass


def reset_pg_stats():
    with pg_conn() as c:
        c.execute("SELECT pg_stat_reset()")


def reload_dataset():
    """Restore the DB to the pristine 150k-row dataset (disposable DB only)."""
    with pg_conn() as c:
        c.execute("TRUNCATE queries RESTART IDENTITY")
    subprocess.run([PY, str(REPO / "backend" / "ingest.py"), "--dsn", PG_DSN],
                   check=True, capture_output=True)
    with pg_conn() as c:
        c.execute("ANALYZE queries")


# ---------------------------------------------------------------- metadata
def environment_metadata(code_dir: Path) -> dict:
    def sh(cmd, cwd=None):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=20, cwd=cwd).stdout.strip()
        except Exception as e:
            return f"<{type(e).__name__}>"

    def pkgver(n):
        try:
            from importlib.metadata import version
            return version(n)
        except Exception:
            return None

    git = sh(["git", "rev-parse", "HEAD"], cwd=REPO)
    status = sh(["git", "status", "--porcelain"], cwd=REPO)
    return {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "os": platform.platform(), "machine": platform.machine(),
        "cpu_logical": psutil.cpu_count(), "cpu_physical": psutil.cpu_count(logical=False),
        "ram_gb": round(psutil.virtual_memory().total / 2**30, 1),
        "python": sys.version.split()[0],
        "node": sh(["node", "--version"]), "docker": sh(["docker", "--version"]),
        "packages": {n: pkgver(n) for n in ["fastapi", "uvicorn", "starlette", "sqlalchemy", "psycopg", "redis",
                                              "pydantic", "pydantic-settings", "aiohttp", "numpy"]},
        "images": sh(["docker", "ps", "--filter", "name=taxaudit", "--format", "{{.Names}}={{.Image}}"]).replace("\n", ", "),
        "pg_version": _pg_scalar("SELECT version()"),
        "pg_settings": {k: _pg_scalar(f"SHOW {k}") for k in
                        ["shared_buffers", "work_mem", "max_connections", "effective_cache_size", "synchronous_commit"]},
        "container_limits": "postgres: 2 CPU / 2g; each redis: 1 CPU / 512m (benchmarks/docker-compose.bench.yml)",
        "git_commit_repo": git, "git_dirty_files_in_repo": status.splitlines()[:30],
        "code_under_test": str(code_dir),
        "network": "loopback (127.0.0.1) via Docker Desktop port-forwarding on Windows; "
                   "load generator, API server, and containers share ONE physical machine",
    }


def _pg_scalar(sql):
    try:
        with pg_conn() as c:
            return c.execute(sql).fetchone()[0]
    except Exception as e:
        return f"<{type(e).__name__}>"


def write_raw(path: Path, header: str, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(header + "\n")
        for r in rows:
            fh.write(",".join(str(x) for x in r) + "\n")


def save_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")
