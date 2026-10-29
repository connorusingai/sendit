"""Walk the new look (BRAND-DECISIONS.md, 10/28) in a hidden Chrome with the database faked (nothing reaches the real one).

Run:  ..\\sendit\\.venv-test\\Scripts\\python.exe tests\\rebrand_walk.py      (from the repo folder; uses your installed Chrome)

What it checks:
  1. A clip that got called landed shows the STOMPED moment; Collect leads into the rank-up (pass taps the gate).
  2. Base: the season pass, today's trick + Film it, "clips need your call", the week in 3 numbers.
  3. Judge: video on top, landed or bailed?, and the stamp after a call.
  4. Feed: full screen, mountain / crew / CU tabs, Bailed / Landed on clips that still need calls.
  5. Crew: podium of 3 passes + the list. Me: pass, 6 stats, your bag, contact sheet. Settings. Record.
  6. Someone else's pass: report + block. The landing page and the signup mountain pick.
  7. First run: ski or snowboard, mountain, call 3 clips, then the green pass.
  8. Glove-proof: Film it, Landed / Bailed and Collect are all at least 56px tall.
Screenshots land in tests/shots/rebrand-*.png.
"""
import base64
import functools
import http.server
import json
import threading
import time
from pathlib import Path
from urllib.parse import unquote

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SHOTS = Path(__file__).parent / "shots"
URL = ""   # set by serve(): a free port, so other test servers on this laptop never answer for us
REF = "kyabslzotdtcwtjcygew"
UID = "11111111-2222-3333-4444-555555555555"
NEW = "99999999-2222-3333-4444-555555555555"
OTHERS = [f"2222222{i}-2222-3333-4444-555555555555" for i in range(5)]
NAMES = ["mia.rides", "jakeb", "lucyw", "theo.snow", "sam_k"]
results, logs, writes = [], [], []


def check(name, ok, got=""):
    results.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name, got if not ok else "")


def b64(d):
    return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")


def session_for(uid, name):
    exp = int(time.time()) + 3600
    jwt = f"{b64({'alg': 'HS256', 'typ': 'JWT'})}.{b64({'sub': uid, 'exp': exp, 'role': 'authenticated', 'aud': 'authenticated'})}.sig"
    user = {"id": uid, "aud": "authenticated", "role": "authenticated", "email": f"{name}@example.com",
            "user_metadata": {"username": name}, "app_metadata": {}, "created_at": "2026-10-20T12:00:00Z"}
    return user, {"access_token": jwt, "token_type": "bearer", "expires_in": 3600, "expires_at": exp, "refresh_token": "fake", "user": user}


def clip(cid, uid, name, trick, status, pts=None, resort="Eldora", hours=2):
    t = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - hours * 3600))
    return {"id": cid, "user_id": uid, "trick_id": trick, "combo": [], "grab": "No grab", "status": status, "points_awarded": pts,
            "resort": resort, "created_at": t, "verified_at": t, "video_path": "x.mp4", "hidden": False, "totd": False,
            "profiles": {"username": name, "points": 700}, "likes": [{"count": 2}], "comments": [{"count": 0}]}


def world(uid, name, points, home):
    me = {"id": uid, "username": name, "home_resort": home, "points": points, "rating": 1000, "created_at": "2026-10-20T12:00:00Z"}
    mine = [clip(f"m{i}", uid, name, t, s, p) for i, (t, s, p) in enumerate(
        [("backflip", "verified", 140), ("360", "rejected", None), ("180", "verified", 40), ("shifty", "pending", None)])] if points else []
    others = [clip(f"c{i}", OTHERS[i], NAMES[i], t, "pending", hours=i + 1) for i, t in enumerate(["360", "540", "5050", "180"])]
    others += [clip("v1", OTHERS[4], NAMES[4], "backflip", "verified", 140, "Copper")]
    board = [{"id": OTHERS[i], "username": NAMES[i], "home_resort": "Eldora", "points": 2000 - 300 * i, "rating": 1000, "score": 2000 - 300 * i} for i in range(4)]
    board.insert(3, {"id": uid, "username": name, "home_resort": home, "points": points, "rating": 1000, "score": points})
    return me, mine, others, board


def make_handler(uid, name, points, home):
    me, mine, others, board = world(uid, name, points, home)
    user, _ = session_for(uid, name)

    def handle(route, req):
        url, m = req.url, req.method
        path = unquote(url.split(".supabase.co", 1)[1])
        if (m == "GET" and path.startswith("/rest/v1/tricks")) or (m == "POST" and "/rpc/trick_of_day" in path):
            return route.continue_(headers={k: v for k, v in req.headers.items() if k.lower() != "authorization"})
        if path.startswith("/auth/v1/user"):
            return route.fulfill(json=user)
        if "/storage/v1/" in path and m != "GET":
            writes.append(f"{m} {path[:90]}")
            return route.fulfill(json={"Key": "x", "Id": "x"})
        single = "vnd.pgrst.object" in req.headers.get("accept", "")
        if "/rpc/" in path:
            writes.append(f"RPC {path[:60]}")
            if "/rpc/leaderboard" in path:
                return route.fulfill(json=board)
            return route.fulfill(json=[])
        if m not in ("GET", "HEAD"):
            writes.append(f"{m} {path[:120]} {(req.post_data or '')[:200]}")
            return route.fulfill(status=201, json={"id": 999} if single else [])
        if path.startswith("/rest/v1/profiles"):
            if single:
                return route.fulfill(json=me if f"id=eq.{uid}" in path else {**me, "id": OTHERS[1], "username": NAMES[1], "points": 1700})
            if "count=exact" in req.headers.get("prefer", "") or m == "HEAD":
                return route.fulfill(json=[], headers={"content-range": "0-0/41"})
            return route.fulfill(json=[{"id": OTHERS[i], "username": NAMES[i], "points": 2000 - 300 * i, "home_resort": "Eldora", "pass_no": 7 + i} for i in range(4)])
        if path.startswith("/rest/v1/clips"):
            if "rider_ok=eq.false" in path:
                return route.fulfill(json=[])
            if f"user_id=eq.{uid}" in path:
                return route.fulfill(json=[c for c in mine if "status=eq.verified" not in path or c["status"] == "verified"])
            if f"user_id=eq.{OTHERS[1]}" in path:
                return route.fulfill(json=[clip("o1", OTHERS[1], NAMES[1], "540", "verified", 160)])
            if single:
                return route.fulfill(json=others[0])
            return route.fulfill(json=mine + others)
        return route.fulfill(json={} if single else [])
    return handle


def serve():
    h = type("Quiet", (http.server.SimpleHTTPRequestHandler,), {"log_message": lambda *a: None})
    global URL
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(h, directory=str(ROOT)))
    URL = f"http://127.0.0.1:{srv.server_address[1]}/app/"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def page_for(b, uid=None, name=None, points=0, home=None, seen=None, store=None):
    ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    init = ""
    if uid:
        _, sess = session_for(uid, name)
        init += f"localStorage.setItem('sb-{REF}-auth-token', {json.dumps(json.dumps(sess))});"
        if seen:
            init += f"localStorage.setItem('seen-status-{uid}', {json.dumps(json.dumps(seen))});"
        ctx.route(f"https://{REF}.supabase.co/**", make_handler(uid, name, points, home))
    for k, v in (store or {}).items():
        init += f"localStorage.setItem({json.dumps(k)}, {json.dumps(v)});"
    ctx.add_init_script(init)
    pg = ctx.new_page()
    pg.on("console", lambda m: logs.append(f"{m.type}: {m.text}") if m.type == "error" and "Failed to load resource" not in m.text else None)
    pg.on("pageerror", lambda e: logs.append(f"PAGEERROR: {e}"))
    return pg


def tall(pg, sel):
    h = pg.eval_on_selector_all(sel, "els => els.filter(e => e.offsetParent).map(e => e.getBoundingClientRect().height)")
    return min(h) if h else 0


def main():
    SHOTS.mkdir(exist_ok=True)
    srv = serve()
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        # ---------- a regular rider: double black, Eldora ----------
        pg = page_for(b, UID, "walker", 840, "Eldora", seen={"m0": "pending"}, store={f"sendit-onboarded-{UID}": "1"})
        pg.goto(URL, wait_until="networkidle")
        pg.wait_for_timeout(3500)
        check("STOMPED moment shows", pg.locator("#reward .stamp-svg").count() == 1)
        check("Collect is glove size (56px+)", tall(pg, "[data-act=reward-collect]") >= 56, tall(pg, "[data-act=reward-collect]"))
        pg.screenshot(path=SHOTS / "rebrand-1-stomped.png")
        pg.click("[data-act=reward-collect]")
        pg.wait_for_timeout(1300)
        check("rank-up: pass taps the gate", pg.locator(".gate .g-reader").count() == 1 and pg.locator(".gate .g-card .pass").count() == 2)
        pg.screenshot(path=SHOTS / "rebrand-2-rankup-mid.png")
        pg.wait_for_timeout(1400)
        check("rank-up ends on the new tier", "double black" in pg.locator("#g-word").inner_text(), pg.locator("#g-word").inner_text())
        pg.screenshot(path=SHOTS / "rebrand-3-rankup-end.png")
        pg.click(".g-go")
        pg.wait_for_timeout(600)
        # Base
        check("base: big season pass", pg.locator(".base .pass").count() == 1)
        check("base: pass says double black", "double black" in pg.locator(".base .pass").inner_html())
        check("base: Film it is glove size", tall(pg, ".today .btn") >= 56, tall(pg, ".today .btn"))
        check("base: clips need your call", "need your call" in pg.locator(".calls").inner_text(), pg.locator(".calls").inner_text())
        check("base: week in 3 numbers", pg.locator(".week3 .num").count() == 3)
        check("tabs: base / feed / record / crew / me", [w for w in pg.locator("#tabs").inner_text().split() if not w.isdigit()] == ["base", "feed", "record", "crew", "me"], pg.locator("#tabs").inner_text().split())
        pg.screenshot(path=SHOTS / "rebrand-4-base.png", full_page=True)
        # Judge
        pg.click(".calls")
        pg.wait_for_timeout(900)
        check("judge: landed or bailed?", pg.locator(".judge-item h1").first.inner_text() == "landed or bailed?")
        check("judge: name hidden until you call it", "mia.rides" not in pg.locator(".judge-item .jmeta").first.inner_text())
        check("judge: Landed / Bailed glove size", tall(pg, ".judge-item .jbtns .call") >= 56, tall(pg, ".judge-item .jbtns .call"))
        pg.screenshot(path=SHOTS / "rebrand-5-judge.png")
        pg.locator(".judge-item .call.yes").first.click()
        pg.wait_for_timeout(500)
        check("judge: STOMPED stamp after a Landed call", pg.locator(".reel-done.yes .stamp-svg").count() == 1)
        pg.screenshot(path=SHOTS / "rebrand-6-judge-stamped.png")
        pg.wait_for_timeout(3200)
        check("judge: the call was saved", any("/rest/v1/votes" in w for w in writes))
        # Feed
        pg.click("#tabs [data-tab=feed]")
        pg.wait_for_timeout(1200)
        check("feed: full screen, header hidden", pg.locator(".top").is_hidden())
        check("feed: eldora / crew / CU", pg.locator(".feed-tabs").inner_text().split() == ["eldora", "crew", "CU"], pg.locator(".feed-tabs").inner_text().split())
        check("feed: REC + brackets", pg.locator(".reel-item .rec").count() > 0 and pg.locator(".reel-item .brk").count() > 0)
        check("feed: Bailed / Landed on a clip that needs calls", pg.locator(".has-calls .fi-calls .call").count() >= 2)
        check("feed: on-clip calls glove size", tall(pg, ".has-calls .fi-calls .call") >= 56, tall(pg, ".has-calls .fi-calls .call"))
        pg.screenshot(path=SHOTS / "rebrand-7-feed.png")
        pg.click(".feed-tabs [data-k=all]")
        pg.wait_for_timeout(600)
        pg.screenshot(path=SHOTS / "rebrand-7b-feed-cu.png")
        # Crew
        pg.click("#tabs [data-tab=duels]")
        pg.wait_for_timeout(1200)
        check("crew: title", "eldora, this week" in pg.locator(".crew-h").inner_text(), pg.locator(".crew-h").inner_text())
        check("crew: podium of 3 passes", pg.locator(".podium .pass").count() == 3)
        check("crew: ranked list", pg.locator(".board li").count() >= 1)
        pg.screenshot(path=SHOTS / "rebrand-8-crew.png", full_page=True)
        for k in ["crew", "duels", "friends"]:
            pg.click(f".squad-seg [data-k={k}]")
            pg.wait_for_timeout(400)
        # Someone else's pass: report + block
        pg.locator(".podium .p1").click()
        pg.wait_for_timeout(1500)
        check("their pass opens", pg.locator(".me .pass").count() >= 1)
        pg.click("[data-act=pass-menu]")
        pg.wait_for_timeout(400)
        check("report pass + block", pg.locator("[data-act=report-pass]").count() == 1 and pg.locator("[data-act=block]").count() == 1)
        pg.screenshot(path=SHOTS / "rebrand-9-their-pass.png", full_page=True)
        pg.click("[data-act=report-pass]")
        pg.wait_for_timeout(600)
        check("pass report saved", any("/rest/v1/reports" in w and "profile_id" in w for w in writes))
        # Me
        pg.click("#tabs [data-act=me]")
        pg.wait_for_timeout(1500)
        check("me: 6 stats", pg.locator(".six .num").count() == 6)
        check("me: your bag", pg.locator(".bag .chip").count() >= 1)
        check("me: contact sheet with stamps", pg.locator(".sheet-grid .tile .stamp-svg").count() >= 2)
        pg.screenshot(path=SHOTS / "rebrand-10-me.png", full_page=True)
        # Settings + record
        pg.click("#acct-chip")
        pg.wait_for_timeout(800)
        check("settings: home mountain", pg.locator("#home-resort").count() == 1)
        pg.screenshot(path=SHOTS / "rebrand-11-settings.png", full_page=True)
        pg.click("#tabs [data-tab=record]")
        pg.wait_for_timeout(800)
        pg.screenshot(path=SHOTS / "rebrand-12-record.png")
        pg.context.close()

        # ---------- signed out: the landing page ----------
        pg = page_for(b)
        pg.goto(URL, wait_until="networkidle")
        pg.wait_for_timeout(1500)
        check("landing: land it. prove it.", "land it." in pg.locator(".land-hero h1").inner_text())
        pg.screenshot(path=SHOTS / "rebrand-13-landing.png", full_page=True)
        pg.locator(".land-cta [data-act=join]").click()
        pg.wait_for_timeout(700)
        check("signup: home mountain pick", pg.locator(".mt-pick button").count() == 8)
        pg.fill("#auth-user", "newrider")
        pg.locator(".mt-pick [data-k=Copper]").click()
        check("signup: typed name survives the pick", pg.input_value("#auth-user") == "newrider")
        pg.screenshot(path=SHOTS / "rebrand-14-signup.png", full_page=True)
        pg.context.close()

        # ---------- first run: brand-new rider ----------
        pg = page_for(b, NEW, "fresh", 0, None)
        pg.goto(URL, wait_until="networkidle")
        pg.wait_for_timeout(2500)
        check("first run: ski or snowboard", pg.locator(".onboard [data-act=ob-sport]").count() == 3)
        pg.click(".onboard [data-k=ski]")
        pg.wait_for_timeout(500)
        check("first run: mountain short list", pg.locator(".ob-mt").count() == 7)
        pg.screenshot(path=SHOTS / "rebrand-15-mountain.png")
        pg.locator(".ob-mt").first.click()
        pg.wait_for_timeout(2500)
        check("first run: call 3 clips", "call 3 clips" in (pg.locator(".first-run").inner_text() if pg.locator(".first-run").count() else ""))
        pg.screenshot(path=SHOTS / "rebrand-16-first-calls.png")
        for i in range(3):
            pg.locator(f"#reel .judge-item:nth-child({i + 1}) .call.yes").click()
            pg.wait_for_timeout(1300)
        pg.wait_for_timeout(7000)   # the last call saves after its 3 s Undo window, then the pass animates
        check("first run: green pass after 3 calls", pg.locator(".gate").count() == 1 and "green" in pg.locator("#g-word").inner_text(),
              pg.locator("#g-word").inner_text() if pg.locator("#g-word").count() else "no gate")
        pg.screenshot(path=SHOTS / "rebrand-17-green-pass.png")
        b.close()
    srv.shutdown()
    bad = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    print("page errors:", logs or "none")
    if bad or logs:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
