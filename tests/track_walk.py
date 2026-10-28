"""App activity log + the Founder dashboard.

Same fake database as ui_walk.py. A normal rider's taps write small event rows (021) and they never see the
dashboard; rider #001 (signed in as the creator) gets it on his own profile, filled from founder_stats().

Run:  ..\\sendit\\.venv-test\\Scripts\\python.exe tests\\track_walk.py
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ui_walk as w  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

w.PORT = int(os.environ.get("PORT", 8133))
w.URL = f"http://127.0.0.1:{w.PORT}/app/"
CREATOR = "713e0c5f-7de1-4842-b845-d1679b4eb7b3"
STATS = {"riders": 9, "new_7d": 4, "active_1d": 3, "active_7d": 6,
         "signups_by_day": [{"day": "2026-10-27", "n": 2}, {"day": "2026-10-28", "n": 2}],
         "by_src": [{"src": "ig", "n": 5}, {"src": "direct", "n": 4}],
         "funnel": {"signed_up": 9, "set_up": 7, "filmed": 4, "posted": 3, "judged": 5, "friended": 6},
         "top_events_7d": [{"name": "tab:feed_clips", "n": 40}],
         "riders_list": [{"username": "boston_bri", "joined": "2026-10-28T12:00:00Z", "src": "ig", "last_seen": "2026-10-28T15:00:00Z",
                          "events": 30, "clips": 1, "votes": 6}]}
AI = {"guessed": 3, "decided": 2, "landed_calls": 2, "landed_right": 2, "spin_calls": 1, "spin_right": 1, "cant_tell": 0}


def session_for(uid):
    exp = int(time.time()) + 3600
    jwt = f"{w.b64({'alg': 'HS256', 'typ': 'JWT'})}.{w.b64({'sub': uid, 'exp': exp, 'role': 'authenticated', 'aud': 'authenticated'})}.sig"
    return dict(w.session, access_token=jwt, user=dict(w.user, id=uid))


def run(uid):
    ok, rpcs = [], []
    me = dict(w.ME, id=uid)

    def handle(route, req):
        path = req.url.split(".supabase.co", 1)[1]
        if "/rpc/founder_stats" in path:
            rpcs.append("stats")
            return route.fulfill(json=STATS) if uid == CREATOR else route.fulfill(status=400, json={"message": "Founder only"})
        if "/rpc/founder_ai_stats" in path:
            return route.fulfill(json=AI)
        if path.startswith("/auth/v1/user"):
            return route.fulfill(json=dict(w.user, id=uid))
        if req.method == "GET" and path.startswith("/rest/v1/profiles") and "vnd.pgrst.object" in req.headers.get("accept", ""):
            return route.fulfill(json=me)
        return w.handle(route, req)

    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        ctx.add_init_script(f"localStorage.setItem('sb-{w.REF}-auth-token', {json.dumps(json.dumps(session_for(uid)))});"
                            f"localStorage.setItem('seen-status-{uid}', JSON.stringify({{c1: 'pending'}}));"
                            f"localStorage.setItem('sendit-onboarded-{uid}', '1');")
        ctx.route(f"https://{w.REF}.supabase.co/**", handle)
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: w.logs.append(f"PAGEERROR: {e}"))
        pg.goto(w.URL, wait_until="networkidle")
        pg.wait_for_timeout(2500)
        for sel in ("[data-act=reward-collect]", ".ru-go"):
            if pg.locator(sel).count():
                pg.click(sel); pg.wait_for_timeout(2200)
        pg.click("#tabs [data-tab=feed]"); pg.wait_for_timeout(600)
        pg.click("#tabs [data-act=me]"); pg.wait_for_timeout(1200)
        ev = [x for x in w.writes if "/rest/v1/events" in x]
        if uid != CREATOR:
            ok.append(("opening the app is logged", any("app_open" in x for x in ev)))
            ok.append(("switching tabs is logged (feed_clips)", any("feed_clips" in x for x in ev)))
            ok.append(("a normal rider has no Founder dashboard", pg.locator(".fdash").count() == 0))
        else:
            ok.append(("rider #001 sees the Founder dashboard on his profile", pg.locator(".fdash").count() == 1))
            pg.click(".fdash [data-act=fdash]"); pg.wait_for_timeout(1200)
            ok.append(("it loads his numbers (9 riders, ig 5)", pg.locator(".fd-nums", has_text="9").count() == 1
                       and pg.locator(".fdash", has_text="ig · 5").count() == 1))
            ok.append(("...the funnel and the rider list", pg.locator(".fd-step").count() == 6 and pg.locator(".fdash", has_text="@boston_bri").count() == 1))
            ok.append(("...and the background AI's score", pg.locator(".fdash", has_text="spin right 1/1").count() == 1))
            pg.locator(".fdash").scroll_into_view_if_needed()
            pg.screenshot(path=str(w.SHOTS / "founder-dash.png"), full_page=True)
        b.close()
    return ok


def main():
    srv = w.serve()
    ok = run(w.UID)
    w.writes.clear()
    ok += run(CREATOR)
    srv.shutdown()
    errs = [x for x in w.logs if "PAGEERROR" in x]
    for name, good in ok:
        print(("PASS " if good else "FAIL ") + name)
    print("page errors:", errs or "none")
    sys.exit(0 if all(g for _, g in ok) and not errs else 1)


if __name__ == "__main__":
    main()
