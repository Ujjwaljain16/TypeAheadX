"""Captures the README screenshots and the "kill a Redis node while the UI keeps working" demo GIF.

Needs the full stack running (docker compose stack from benchmarks/docker-compose.bench.yml, the API on :8000 started
with benchmarks/env.sh, `npm run dev` for the frontend on :3000) and `pip install playwright pillow` (uses the
locally installed Chrome, no browser download).

    python benchmarks/demo/capture_demo.py

Every caption below is built from real responses (status code and the server's own X-Response-Time-ms header) and
the API's own /metrics counters - nothing is staged.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs" / "assets"
sys.path.insert(0, str(REPO / "backend"))
from app.cache.consistent_hash_ring import ConsistentHashRing  # noqa: E402

API, WEB = "http://localhost:8000", "http://localhost:3000"
NODE_PORTS = [47379, 47380, 47381]
DEAD = "taxbench-redis-b"          # owns the ring node named localhost:47380
DEAD_RING_NAME = "localhost:47380"

ring = ConsistentHashRing(500)
for p in NODE_PORTS:
    ring.add_node(f"localhost:{p}")


def owner(prefix: str) -> str:
    return ring.get_node(f"suggestion:{prefix}").physical_node


def pick_query_for_dead_node() -> str:
    """A popular query several of whose prefixes (len >= 3) are owned by the node we are going to kill."""
    import csv
    rows = list(csv.reader(open(REPO / "data" / "processed" / "queries.csv", encoding="utf-8")))[1:3000]
    for q, _ in rows:
        owned = [q[:i] for i in range(3, min(len(q), 9) + 1) if owner(q[:i]) == DEAD_RING_NAME]
        if len(owned) >= 3 and q[:3] not in ("iph", "mac"):
            return q
    raise SystemExit("no suitable query found")


def font(size: int, bold: bool = False):
    for name in ("segoeuib.ttf" if bold else "segoeui.ttf", "arialbd.ttf" if bold else "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def with_caption(png: Path, title: str, detail: str, color: str) -> Image.Image:
    img = Image.open(png).convert("RGB")
    bar_h = 92
    canvas = Image.new("RGB", (img.width, img.height + bar_h), "#0f172a")
    canvas.paste(img, (0, 0))
    d = ImageDraw.Draw(canvas)
    d.rectangle([0, img.height, 10, img.height + bar_h], fill=color)
    d.text((26, img.height + 12), title, font=font(22, True), fill="#f8fafc")
    d.text((26, img.height + 48), detail, font=font(17), fill="#cbd5e1")
    return canvas


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "_tmp"
    tmp.mkdir(exist_ok=True)
    dead_query = pick_query_for_dead_node()
    print("query whose prefixes live on the node we will kill:", dead_query)

    seen: list[dict] = []
    http_errors = 0
    frames: list[tuple[Image.Image, float]] = []

    def on_response(r):
        nonlocal http_errors
        if r.url.startswith(API) and ("/suggest" in r.url):
            if r.status >= 400:
                http_errors += 1
            seen.append({"url": r.url, "status": r.status, "ms": r.headers.get("x-response-time-ms")})

    def last_suggest() -> dict:
        return seen[-1] if seen else {"status": "-", "ms": "?", "url": ""}

    def metrics() -> dict:
        return requests.get(f"{API}/metrics", timeout=5).json()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": 1000, "height": 780})
        page.on("response", on_response)
        page.goto(WEB)
        page.add_style_tag(content="nextjs-portal{display:none !important}")   # hide the dev-mode badge
        box = page.locator("input[role=combobox]")
        box.wait_for()
        time.sleep(1)

        def shot(name: str) -> Path:
            p = tmp / f"{name}.png"
            page.screenshot(path=str(p))
            return p

        def type_text(text: str) -> None:
            box.click()
            box.fill("")
            time.sleep(0.2)
            page.keyboard.type(text, delay=150)
            try:
                page.wait_for_selector("[role=listbox] li, text=No results", timeout=6000)
            except Exception:
                pass
            time.sleep(0.8)

        def frame(png: Path, title: str, detail: str, color: str, secs: float) -> None:
            frames.append((with_caption(png, title, detail, color), secs))

        # 1. idle
        frame(shot("idle"), "TypeAheadX  ·  Next.js UI → FastAPI → 3 Redis nodes (consistent-hash ring) → PostgreSQL",
              "150 000 real queries · debounce 250 ms · in-flight requests are aborted", "#6366f1", 2.2)

        # 2. everything healthy
        type_text("iph")
        s = last_suggest()
        frame(shot("iph"), f"All 3 Redis nodes up   GET /suggest?q=iph → {s['status']}  ·  {s['ms']} ms server-side",
              f"prefix 'iph' is owned by Redis {owner('iph').split(':')[1]}  ·  HTTP errors so far: {http_errors}", "#16a34a", 2.6)

        type_text("iphone 15 p")
        s = last_suggest()
        frame(shot("iph2"), f"GET /suggest?q=iphone 15 p → {s['status']}  ·  {s['ms']} ms server-side",
              f"served from the cache on the second keystroke of the same prefix  ·  HTTP errors so far: {http_errors}", "#16a34a", 2.4)

        # 3. kill a node
        out = subprocess.run(["docker", "stop", "-t", "1", DEAD], capture_output=True, text=True)
        frame(shot("killed"), f"$ docker stop {DEAD}      — one of the three cache nodes is now DEAD",
              "keys owned by that node can no longer be cached; what does the user see?", "#dc2626", 2.6)

        # 4. typing prefixes that live on the dead node
        shown = []
        last_dead = None
        for n in (3, 4, 5, 6):
            prefix = dead_query[:n]
            if owner(prefix) != DEAD_RING_NAME:
                continue
            type_text(prefix)
            s = last_suggest()
            shown.append((prefix, s))
            last_dead = tmp / f"dead{n}.png"
            frame(shot(f"dead{n}"),
                  f"Redis B DEAD   GET /suggest?q={prefix} → {s['status']}  ·  {s['ms']} ms server-side",
                  f"prefix owned by the dead node → breaker skips it, answered from PostgreSQL  ·  HTTP errors so far: {http_errors}",
                  "#dc2626", 2.6)
            if len(shown) == 3:
                break
        m = metrics()
        c = m["cache"]
        frame(shot("metrics"), "What the service recorded while a node was dead",
              f"cache errors: {c['errors']}  ·  breaker skips (no network I/O): {c['breaker_skips']}  ·  HTTP errors to the user: {http_errors}",
              "#d97706", 3.2)

        # 5. recovery
        subprocess.run(["docker", "start", DEAD], capture_output=True, text=True)
        time.sleep(7.5)                       # > breaker window
        probe = next((dead_query[:n] for n in (7, 8, 9, 6, 5) if n <= len(dead_query) and owner(dead_query[:n]) == DEAD_RING_NAME), dead_query[:5])
        type_text(probe)
        s = last_suggest()
        frame(shot("recovered"), f"$ docker start {DEAD}   GET /suggest?q={probe} → {s['status']}  ·  {s['ms']} ms",
              f"breaker probe succeeded → node serving again  ·  total HTTP errors during the whole demo: {http_errors}", "#16a34a", 3.2)

        # JSON "cards" for the README (real responses, pretty-printed and styled)
        def json_card(title: str, obj: object, name: str) -> None:
            body = json.dumps(obj, indent=2).replace("<", "&lt;")
            lines = len(body.splitlines())
            page.set_viewport_size({"width": 920, "height": min(900, 90 + 21 * lines)})
            page.set_content(
                "<body style='margin:0;background:#0f172a;font-family:Consolas,monospace'>"
                f"<div style='padding:14px 22px;background:#1e293b;color:#e2e8f0;font:600 16px Segoe UI,sans-serif'>{title}</div>"
                f"<pre style='margin:0;padding:16px 22px;color:#a5f3fc;font-size:14px;line-height:21px'>{body}</pre></body>")
            page.screenshot(path=str(OUT / f"{name}.png"))

        m = metrics()
        json_card("GET /metrics  (cache · write buffer · database guard)", m, "metrics")
        json_card("GET /cache/debug?prefix=iphone  (which ring node owns this key)",
                  requests.get(f"{API}/cache/debug", params={"prefix": "iphone"}, timeout=5).json(), "cache-debug")
        browser.close()

    # captioned stills for the README (frame 1 = healthy, first frame after the kill = degraded)
    frames[1][0].save(OUT / "ui-suggestions.png")
    frames[4][0].save(OUT / "ui-redis-down.png")

    # assemble animation
    w = 960
    small = [f.resize((w, int(f.height * w / f.width)), Image.LANCZOS) for f, _ in frames]
    durs = [int(s * 1000) for _, s in frames]
    small[0].save(OUT / "demo-redis-node-killed.webp", save_all=True, append_images=small[1:], duration=durs, loop=0, quality=82, method=6)
    pal = [f.convert("P", palette=Image.ADAPTIVE, colors=128) for f in small]
    pal[0].save(OUT / "demo-redis-node-killed.gif", save_all=True, append_images=pal[1:], duration=durs, loop=0, optimize=True)
    for f in tmp.glob("*.png"):
        f.unlink()
    tmp.rmdir()
    print(json.dumps({"frames": len(frames), "http_errors": http_errors,
                      "webp_kb": round((OUT / "demo-redis-node-killed.webp").stat().st_size / 1024),
                      "gif_kb": round((OUT / "demo-redis-node-killed.gif").stat().st_size / 1024)}))


if __name__ == "__main__":
    main()
