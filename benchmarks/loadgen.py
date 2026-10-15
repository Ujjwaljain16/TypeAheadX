"""Open-loop HTTP load generator (asyncio + aiohttp).

Requests are *scheduled* at a fixed (or Poisson) arrival rate regardless of
whether earlier requests have completed. Latency is measured from the
**intended** send time, so queueing delay inside an overloaded server (or
inside this generator) is charged to the request instead of silently slowing
the offered load (coordinated omission). ``send_lag`` records how late requests
were actually dispatched: if it is large the *generator* is the bottleneck and
the run is invalid for that rate.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Callable

import aiohttp
import numpy as np

try:  # Windows: timer tick can be 8-15.6 ms and Win11 throttles background processes; ask for 1 ms.
    import ctypes
    ctypes.windll.winmm.timeBeginPeriod(1)
except Exception:
    pass
# NOTE: because the above is not reliable, the dispatch loop below spins (sleep(0)) during the
# last few ms before each scheduled send instead of trusting asyncio.sleep() granularity.


@dataclass
class Result:
    rate: float
    duration: float
    warmup: float
    scheduled: int
    # records for measured window: (t_rel_s, latency_ms, status, send_lag_ms)
    records: list = field(default_factory=list)
    wall_seconds: float = 0.0

    def arrays(self):
        if not self.records:
            return np.zeros(0), np.zeros(0), [], np.zeros(0)
        t = np.asarray([r[0] for r in self.records])
        lat = np.asarray([r[1] for r in self.records])
        st = [r[2] for r in self.records]
        lag = np.asarray([r[3] for r in self.records])
        return t, lat, st, lag

    def summary(self) -> dict:
        t, lat, st, lag = self.arrays()
        ok_mask = np.asarray([s.startswith("2") for s in st], dtype=bool) if st else np.zeros(0, bool)
        ok_lat = lat[ok_mask]
        status_counts: dict[str, int] = {}
        for s in st:
            status_counts[s] = status_counts.get(s, 0) + 1
        n_to = status_counts.get("timeout", 0)
        n_ok = int(ok_mask.sum())

        def pct(a, q):
            return round(float(np.percentile(a, q)), 3) if len(a) else None

        return {
            "offered_rps": self.rate,
            "measured_window_s": self.duration,
            "scheduled": self.scheduled,
            "completed": len(st),
            "ok": n_ok,
            "errors": len(st) - n_ok,
            "timeouts": n_to,
            "status_counts": status_counts,
            "achieved_ok_rps": round(n_ok / self.duration, 2) if self.duration else None,
            "error_rate": round((len(st) - n_ok) / max(1, self.scheduled), 5),
            "unfinished": self.scheduled - len(st),
            "n_latency_samples": int(len(ok_lat)),
            "p50_ms": pct(ok_lat, 50), "p90_ms": pct(ok_lat, 90), "p95_ms": pct(ok_lat, 95),
            "p99_ms": pct(ok_lat, 99), "p99_9_ms": pct(ok_lat, 99.9),
            "max_ms": round(float(ok_lat.max()), 3) if len(ok_lat) else None,
            "mean_ms": round(float(ok_lat.mean()), 3) if len(ok_lat) else None,
            "all_p99_ms_incl_errors": pct(lat, 99),
            "send_lag_p99_ms": pct(lag, 99),
            "send_lag_max_ms": round(float(lag.max()), 3) if len(lag) else None,
        }

    def timeline(self, bucket_s: float = 1.0) -> list[dict]:
        """Per-bucket latency/error series (used by failure scenarios)."""
        t, lat, st, _ = self.arrays()
        out = []
        if not len(t):
            return out
        ok = np.asarray([s.startswith("2") for s in st], dtype=bool)
        b = np.floor(t / bucket_s).astype(int)
        for k in range(int(b.min()), int(b.max()) + 1):
            m = b == k
            if not m.any():
                continue
            okm = m & ok
            out.append({
                "t": k * bucket_s, "n": int(m.sum()), "ok": int(okm.sum()),
                "err": int(m.sum() - okm.sum()),
                "p50_ms": round(float(np.percentile(lat[okm], 50)), 2) if okm.any() else None,
                "p99_ms": round(float(np.percentile(lat[okm], 99)), 2) if okm.any() else None,
                "max_ms": round(float(lat[m].max()), 2),
            })
        return out


async def run_open_loop(
    base_url: str,
    ops: list[tuple],           # ("GET", prefix) or ("POST", query)
    rate: float,
    duration: float,
    warmup: float = 3.0,
    timeout_s: float = 5.0,
    poisson_seed: int | None = None,
    connector_limit: int = 4000,
    on_measure_start: Callable[[], None] | None = None,
    events: list[tuple[float, Callable[[], None]]] | None = None,  # (t_rel_s since start of run, fn)
    offsets_override: np.ndarray | None = None,  # explicit arrival times (burst profiles)
) -> Result:
    """Offer ``rate`` req/s for ``warmup+duration`` seconds; only requests whose
    intended time falls in the measured window (after warmup) are recorded.
    ``events`` fire (in a worker thread) at the given time offsets from run start."""
    total = int((warmup + duration) * rate) if offsets_override is None else len(offsets_override)
    if total > len(ops):
        raise ValueError(f"workload has {len(ops)} ops but {total} needed")
    if offsets_override is not None:
        offsets = np.asarray(offsets_override, dtype=float)
    elif poisson_seed is None:
        offsets = np.arange(total) / rate
    else:
        rng = np.random.default_rng(poisson_seed)
        offsets = np.cumsum(rng.exponential(1.0 / rate, size=total))

    conn = aiohttp.TCPConnector(limit=connector_limit, limit_per_host=connector_limit)
    tmo = aiohttp.ClientTimeout(total=timeout_s)
    records: list = []
    loop = asyncio.get_running_loop()
    pending_events = sorted(events or [], key=lambda e: e[0])
    measure_hook_fired = False

    async with aiohttp.ClientSession(connector=conn, timeout=tmo) as session:
        start = time.perf_counter() + 0.25
        pending: set[asyncio.Task] = set()

        async def one(i: int, intended: float, measured: bool):
            kind, arg = ops[i]
            sent = time.perf_counter()
            try:
                if kind == "HEALTH":
                    async with session.get(f"{base_url}/health") as r:
                        await r.read()
                        status = str(r.status)
                elif kind == "GET":
                    async with session.get(f"{base_url}/suggest", params={"q": arg}) as r:
                        await r.read()
                        status = str(r.status)
                else:
                    async with session.post(f"{base_url}/search", json={"query": arg}) as r:
                        await r.read()
                        status = str(r.status)
            except asyncio.TimeoutError:
                status = "timeout"
            except Exception as e:  # connection reset etc.
                status = "exc:" + type(e).__name__
            end = time.perf_counter()
            if measured:
                records.append((intended - start, (end - intended) * 1000.0, status, (sent - intended) * 1000.0))

        i = 0
        while i < total or pending_events:
            now = time.perf_counter()
            while pending_events and start + pending_events[0][0] <= now:
                _, fn = pending_events.pop(0)
                loop.run_in_executor(None, fn)
            while i < total and start + offsets[i] <= now:
                measured = offsets[i] >= warmup
                if measured and not measure_hook_fired:
                    measure_hook_fired = True
                    if on_measure_start:
                        loop.run_in_executor(None, on_measure_start)  # never block the dispatch loop
                t = asyncio.create_task(one(i, start + offsets[i], measured))
                pending.add(t)
                t.add_done_callback(pending.discard)
                i += 1
            if i >= total and not pending_events:
                break
            nxt = start + (offsets[i] if i < total else 0.0)
            if pending_events:
                nxt = min(nxt, start + pending_events[0][0]) if i < total else start + pending_events[0][0]
            await asyncio.sleep(0.001 if nxt - time.perf_counter() > 0.025 else 0)  # sleep may overshoot by a full ~15.6 ms tick
        if pending:
            await asyncio.wait(pending, timeout=timeout_s + 1)
        wall = time.perf_counter() - start

    # re-base record times to measured-window origin
    recs = [(r[0] - warmup, r[1], r[2], r[3]) for r in records]
    n_measured = int(np.sum(offsets >= warmup))
    return Result(rate=rate, duration=duration, warmup=warmup, scheduled=n_measured,
                  records=recs, wall_seconds=wall)
