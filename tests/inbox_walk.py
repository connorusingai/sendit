"""Notifications inbox (the bell): walk it in a hidden Chrome with a faked database (nothing reaches the real one).

Run:  ..\\sendit\\.venv-test\\Scripts\\python.exe tests\\inbox_walk.py

Checks:
  1. The bell shows a count of new things (verified clip, fires, a comment, a friend request, a duel turn).
  2. Old things (over a day) don't count as new on the first open on a phone.
  3. Opening the inbox lists them (Today / Earlier), new ones highlighted; the count clears afterwards.
  4. Tapping the comment opens that clip in the feed with comments open; tapping the duel opens the duel.
  5. Blocked riders' fires don't show.
"""
import json
import os
from datetime import datetime, timedelta, timezone

from playwright.sync_api import sync_playwright

import ui_walk as W   # reuse the fake sign-in + server

UID, now = W.UID, datetime.now(timezone.utc)
iso = lambda **kw: (now - timedelta(**kw)).isoformat().replace("+00:00", "Z")
JAKE = {"id": "a0000000-0000-0000-0000-00000000000a", "username": "jake", "points": 300, "rating": 1000}
MAYA = {"id": "b0000000-0000-0000-0000-00000000000b", "username": "maya", "points": 500, "rating": 1000}
BLOCKED = "c0000000-0000-0000-0000-00000000000c"
base = {"user_id": UID, "combo": [], "video_path": "x.mp4", "profiles": {"username": "walker", "points": 1284},
        "likes": [{"count": 0}], "comments": [{"count": 0}]}
CLIPS = [
    {**base, "id": "c1", "trick_id": "cork720", "status": "verified", "points_awarded": 140, "created_at": iso(hours=3), "verified_at": iso(hours=2)},
    {**base, "id": "c2", "trick_id": "cork720", "status": "verified", "points_awarded": 20, "created_at": iso(days=5), "verified_at": iso(days=5)},
]
LIKES = [{"clip_id": "c1", "user_id": JAKE["id"], "created_at": iso(minutes=30), "profiles": {"username": "jake"}},
         {"clip_id": "c1", "user_id": MAYA["id"], "created_at": iso(minutes=50), "profiles": {"username": "maya"}},
         {"clip_id": "c1", "user_id": BLOCKED, "created_at": iso(minutes=5), "profiles": {"username": "troll"}}]
COMMENTS = [{"id": "m1", "clip_id": "c1", "user_id": MAYA["id"], "body": "clean landing!!", "created_at": iso(minutes=20),
             "hidden": False, "profiles": {"username": "maya"}}]
FRIENDS = [{"requester": JAKE["id"], "addressee": UID, "status": "pending", "created_at": iso(hours=1), "req": JAKE, "addr": W.ME}]
DUELS = [{"id": "d1", "challenger": UID, "opponent": MAYA["id"], "status": "active", "turn": UID, "phase": "match", "trick_id": "cork720",
          "letters_challenger": 0, "letters_opponent": 1, "winner": None, "created_at": iso(days=1), "updated_at": iso(minutes=10),
          "ch": W.ME, "op": MAYA}]
nav = []


def handle(route, req):
    path = req.url.split(".supabase.co", 1)[1]
    if req.method == "GET":
        if path.startswith("/rest/v1/likes") and "user_id=neq" in path: return route.fulfill(json=LIKES)
        if path.startswith("/rest/v1/comments") and "user_id=neq" in path: return route.fulfill(json=COMMENTS)
        if path.startswith("/rest/v1/comments"): nav.append("comments-loaded"); return route.fulfill(json=COMMENTS)
        if path.startswith("/rest/v1/friendships"): return route.fulfill(json=FRIENDS)
        if path.startswith("/rest/v1/duels"): return route.fulfill(json=DUELS)
        if path.startswith("/rest/v1/duel_moves"): nav.append("duel-opened"); return route.fulfill(json=[])
        if path.startswith("/rest/v1/blocks"): return route.fulfill(json=[{"blocked": BLOCKED, "p": {"username": "troll"}}])
        if path.startswith("/rest/v1/clips") and "id=eq.c1" in path: return route.fulfill(json=CLIPS[0])
        if path.startswith("/rest/v1/clips") and "rider_ok=eq.false" in path: return route.fulfill(json=[])
        if path.startswith("/rest/v1/clips"): return route.fulfill(json=CLIPS)
    return W.handle(route, req)


def main():
    srv = W.serve()
    logs, ok = [], True
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        ctx.add_init_script(f"localStorage.setItem('sb-{W.REF}-auth-token', {json.dumps(json.dumps(W.session))});"
                            f"localStorage.setItem('seen-status-{UID}', JSON.stringify({{c1:'verified', c2:'verified'}}));"
                            "localStorage.setItem('sendit-splash-seen', '1');")
        ctx.route(f"https://{W.REF}.supabase.co/**", handle)
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: logs.append(f"PAGEERROR: {e}"))
        pg.on("console", lambda m: logs.append(f"{m.type}: {m.text}") if m.type == "error" else None)
        pg.goto(W.URL, wait_until="networkidle")
        pg.wait_for_timeout(3500)
        for sel in ["#splash [data-act=close-splash]", ".install-sheet .btn.ghost"]:
            if pg.locator(sel).count(): pg.locator(sel).first.click(); pg.wait_for_timeout(400)

        def check(name, cond, extra=""):
            nonlocal ok
            ok &= bool(cond)
            print(("PASS " if cond else "FAIL ") + name, extra)

        badge = pg.locator("#bell-chip .badge")
        # new: verified c1, fires on c1, maya's comment, jake's request, duel turn = 5. c2 (5 days old) isn't new.
        check("bell count = 5", badge.count() and badge.inner_text() == "5", badge.inner_text() if badge.count() else "(no badge)")
        pg.screenshot(path=W.SHOTS / "inbox-1-bell.png")
        pg.click("#bell-chip")
        pg.wait_for_timeout(800)
        rows = pg.locator(".nt")
        texts = [rows.nth(i).inner_text().replace("\n", " ") for i in range(rows.count())]
        for t in texts: print("   ", t)
        check("6 rows", rows.count() == 6)
        check("5 highlighted", pg.locator(".nt.new").count() == 5)
        check("fires grouped, blocked hidden", any("@jake and 1 other fired" in t for t in texts) and not any("troll" in t for t in texts))
        check("Today + Earlier", pg.locator(".inbox .label").count() == 2)
        check("bell cleared while open", pg.locator("#bell-chip .badge").count() == 0)
        pg.screenshot(path=W.SHOTS / "inbox-2-list.png", full_page=True)
        # tap the comment -> the clip opens in the feed with comments loaded
        pg.locator(".nt", has_text="clean landing").click()
        pg.wait_for_timeout(1500)
        check("comment tap opens clip + comments", pg.locator("#clip-c1").count() and "comments-loaded" in nav)
        pg.screenshot(path=W.SHOTS / "inbox-3-comment.png")
        check("bell stays cleared", pg.locator("#bell-chip .badge").count() == 0)
        pg.click("#tabs [data-tab=lodge]"); pg.wait_for_timeout(600)   # the feed hides the top bar (full-screen clips)
        pg.click("#bell-chip"); pg.wait_for_timeout(600)
        check("rows read now", pg.locator(".nt.new").count() == 0)
        pg.locator(".nt", has_text="S.K.I.").click()
        pg.wait_for_timeout(1200)
        check("duel tap opens the duel", "duel-opened" in nav)
        # reload: still read (saved on the phone)
        pg.reload(wait_until="networkidle"); pg.wait_for_timeout(3000)
        check("still read after reload", pg.locator("#bell-chip .badge").count() == 0)
        # a new like arrives -> 1 new
        LIKES.insert(0, {"clip_id": "c1", "user_id": "d0000000-0000-0000-0000-00000000000d", "created_at": iso(minutes=1), "profiles": {"username": "sam"}})
        pg.reload(wait_until="networkidle"); pg.wait_for_timeout(3000)
        check("new fire -> 1 new", pg.locator("#bell-chip .badge").count() and pg.locator("#bell-chip .badge").inner_text() == "1")
        b.close()
    srv.shutdown()
    check("no page errors", not logs, logs or "")
    print("ALL PASS" if ok else "SOME FAILED")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
