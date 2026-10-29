"""Walk the app in a hidden Chrome as a signed-in rider, with the database faked (nothing reaches the real one).

Only two public reads go to the real Supabase: the trick list and Trick of the Day. Every other call gets a
made-up answer, and every write is only logged. Screenshots land in tests/shots/.

Run:  .venv-test\\Scripts\\python.exe tests\\ui_walk.py        (from dev\\sendit; uses your installed Chrome)

What it checks now:
  1. The Lodge opens first (scene, rank road, chips) with no page errors.
  2. A clip that was pending last visit and is now verified gets the reward moment (STOMPED, points, Collect).
  3. Each tab opens without errors.
"""
import os
import base64
import functools
import http.server
import json
import threading
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SHOTS = Path(__file__).parent / "shots"
PORT = int(os.environ.get("WALK_PORT", 8123))   # another copy of the app running its tests at once: give each its own port
URL = f"http://127.0.0.1:{PORT}/app/"
REF = "kyabslzotdtcwtjcygew"
UID = "11111111-2222-3333-4444-555555555555"
ME = {"id": UID, "username": "walker", "home_resort": "eldora", "points": 1284, "rating": 1000, "created_at": "2026-10-20T12:00:00Z"}
CLIP = {"id": "c1", "user_id": UID, "trick_id": "cork720", "combo": [], "status": "verified", "points_awarded": 140,
        "created_at": "2026-10-23T12:00:00Z", "verified_at": "2026-10-23T13:00:00Z", "video_path": "x.mp4",
        "profiles": {"username": "walker", "points": 1284}, "likes": [{"count": 0}], "comments": [{"count": 0}]}


def b64(d):
    return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")


exp = int(time.time()) + 3600
jwt = f"{b64({'alg': 'HS256', 'typ': 'JWT'})}.{b64({'sub': UID, 'exp': exp, 'role': 'authenticated', 'aud': 'authenticated'})}.sig"
user = {"id": UID, "aud": "authenticated", "role": "authenticated", "email": "walker@example.com",
        "user_metadata": {"username": "walker"}, "app_metadata": {}, "created_at": "2026-10-20T12:00:00Z"}
session = {"access_token": jwt, "token_type": "bearer", "expires_in": 3600, "expires_at": exp, "refresh_token": "fake", "user": user}
writes, logs = [], []


def handle(route, req):
    url, m = req.url, req.method
    path = url.split(".supabase.co", 1)[1]
    if (m == "GET" and path.startswith("/rest/v1/tricks")) or (m == "POST" and "/rpc/trick_of_day" in path):
        return route.continue_(headers={k: v for k, v in req.headers.items() if k.lower() != "authorization"})
    if path.startswith("/auth/v1/user"):
        return route.fulfill(json=user)
    if "/storage/v1/" in path and m != "GET":
        writes.append(f"{m} {path[:90]}")
        return route.fulfill(json={"Key": "clips/x", "Id": "x"})
    if m not in ("GET", "HEAD") and "/rpc/" not in path:
        writes.append(f"{m} {path[:120]} {(req.post_data or '')[:200]}")
        return route.fulfill(status=201, json={"id": 999} if "vnd.pgrst.object" in req.headers.get("accept", "") else [])
    if "/rpc/" in path:
        return route.fulfill(json=[])
    single = "vnd.pgrst.object" in req.headers.get("accept", "")
    if path.startswith("/rest/v1/profiles"):
        return route.fulfill(json=ME if single else [])
    if path.startswith("/rest/v1/clips") and f"user_id=eq.{UID}" in path or path.startswith("/rest/v1/clips?select"):
        return route.fulfill(json=[CLIP])
    return route.fulfill(json={} if single else [])


def serve():
    # A free port every run: on Windows two servers can share a fixed port, and then another worktree's server answers
    global PORT, URL
    h = type("Quiet", (http.server.SimpleHTTPRequestHandler,), {"log_message": lambda *a: None})
    h = functools.partial(h, directory=str(ROOT))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
    PORT = srv.server_address[1]
    URL = f"http://127.0.0.1:{PORT}/app/"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main():
    SHOTS.mkdir(exist_ok=True)
    srv = serve()
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        ctx = b.new_context(viewport={"width": int(os.environ.get("VW", 390)), "height": int(os.environ.get("VH", 844))}, is_mobile=True, has_touch=True)
        ctx.add_init_script(f"localStorage.setItem('sb-{REF}-auth-token', {json.dumps(json.dumps(session))});"
                            f"localStorage.setItem('seen-status-{UID}', JSON.stringify({{c1: 'pending'}}));")
        ctx.route(f"https://{REF}.supabase.co/**", handle)
        pg = ctx.new_page()
        pg.on("console", lambda m: logs.append(f"{m.type}: {m.text}") if m.type == "error" else None)
        pg.on("pageerror", lambda e: logs.append(f"PAGEERROR: {e}"))
        pg.goto(URL, wait_until="networkidle")
        pg.wait_for_timeout(4000)
        pg.screenshot(path=SHOTS / "1-open.png")
        reward = pg.locator("#reward").count()
        print("reward moment shown:", bool(reward), "|", pg.locator(".reward-card").inner_text().replace("\n", " ") if reward else "")
        if reward:
            pg.click("[data-act=reward-collect]")
            pg.wait_for_timeout(600)
        if pg.locator(".gate").count():   # the rank up waits for Let's go
            pg.wait_for_timeout(2500)
            pg.click(".ru-go")
            pg.wait_for_timeout(500)
        pg.wait_for_timeout(1500)
        # Base (DESIGN.md 10/28): the season pass, today's trick + Film it, clips to call, the week in 3 numbers
        print("base first:", pg.locator(".base").count() == 1, "| pass:", pg.locator(".base .pass").count() == 1,
              "| film it:", pg.locator(".today .btn").count() == 1, "| calls:", pg.locator(".calls").count() == 1,
              "| week:", pg.locator(".week3 .num").count())
        pg.screenshot(path=SHOTS / "2-lodge.png")
        # The pass opens Me: pass, 6 stats, your bag, contact sheet, badges
        pg.click(".base .pass-btn")
        pg.wait_for_timeout(1200)
        print("me:", pg.locator(".me .pass").count() >= 1, "| stats:", pg.locator(".six .num").count(),
              "| bag:", pg.locator(".bag").count() == 1, "| badges:", pg.locator(".ach").count())
        pg.screenshot(path=SHOTS / "4-profile.png", full_page=True)
        # Crew: board + friends / your crew / duels
        pg.click("#tabs [data-tab=duels]")
        pg.wait_for_timeout(900)
        for k in ["friends", "crew", "duels"]:
            pg.click(f".squad-seg [data-k={k}]")
            pg.wait_for_timeout(700)
            pg.screenshot(path=SHOTS / f"5-squad-{k}.png")
        print("squad tabs:", pg.locator(".squad-seg button").count())
        pg.click(".squad-seg [data-k=friends]")
        for tab in ["feed", "record", "duels", "lodge"]:
            pg.click(f"#tabs [data-tab={tab}]")
            pg.wait_for_timeout(900)
            if tab != "lodge":
                pg.screenshot(path=SHOTS / f"6-{tab}.png")
        # Trick book from Me
        pg.click("#tabs [data-act=me]")
        pg.wait_for_timeout(1200)
        pg.click(".bag [data-act=book]")
        pg.wait_for_timeout(2500)
        pg.screenshot(path=SHOTS / "7-book.png")
        pg.click("#tabs [data-tab=lodge]")
        pg.wait_for_timeout(900)
        pg.screenshot(path=SHOTS / "3-back-to-lodge.png")
        b.close()
    srv.shutdown()
    print("page errors:", logs or "none")
    print("writes (faked):", writes or "none")


if __name__ == "__main__":
    main()
