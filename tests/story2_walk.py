"""Story 2: I film my first trick in the app and post it. I see it upload, and I know what happens next:
riders judge it.

Run:  .venv-test\\Scripts\\python.exe tests\\story2_walk.py        (from the app folder)
"""
import re
import time

from playwright.sync_api import sync_playwright

import story_kit as k
from story_kit import w

state = {"posted": False, "upload_seen": False}
OTHERS = [c for c in k.bot.CLIPS if c["user_id"] != k.UID]            # 3 verified + 3 still being called
MINE = {"id": "new1", "user_id": k.UID, "trick_id": "180", "combo": [], "grab": "No grab", "status": "pending", "points_awarded": 0,
        "created_at": "2026-11-11T18:00:00Z", "verified_at": None, "video_path": f"{k.UID}/new1.mp4", "resort": "Eldora",
        "profiles": {"username": "newbie", "points": 0}, "likes": [{"count": 0}], "comments": [{"count": 0}]}
LEFT = [{"clip_id": "new1", "calls_left": 2}, {"clip_id": "o4", "calls_left": 2}, {"clip_id": "o5", "calls_left": 1}, {"clip_id": "o6", "calls_left": 2}]


def handle(route, req):
    path, m = k.path_of(req), req.method
    if m == "GET" and path.startswith("/rest/v1/profiles"):
        return route.fulfill(json=k.NEW if k.wants_one(req) else [])
    if m == "GET" and path.startswith("/rest/v1/clips"):
        mine = [dict(MINE, trick_id=state.get("trick", "180"))] if state["posted"] else []
        if f"user_id=eq.{k.UID}" in path:
            return route.fulfill(json=[] if "rider_ok=eq.false" in path or "status=eq.verified" in path else mine)
        return route.fulfill(json=mine + OTHERS)
    if m == "POST" and "/storage/v1/object/clips/" in path and path.endswith(".mp4"):
        state["upload_seen"] = True
        time.sleep(1.6)                                      # a slow mountain connection
        w.writes.append(f"POST {path[:60]}")
        return route.fulfill(json={"Key": "clips/x", "Id": "x"})
    if m == "POST" and path.startswith("/rest/v1/clips"):
        w.writes.append(f"POST {path[:40]} {(req.post_data or '')[:200]}")
        m2 = re.search(r'"trick_id":"([^"]+)"', req.post_data or "")
        state["trick"] = m2.group(1) if m2 else "180"
        state["posted"] = True
        return route.fulfill(status=201, json={"id": "new1"})
    if "/rpc/calls_left" in path:
        return route.fulfill(json=LEFT)
    return w.handle(route, req)


def main():
    W = k.Walk("Story 2: film my first trick, watch it upload, know what happens next")
    srv = w.serve()
    with sync_playwright() as p:
        b = k.launch(p, camera=True)
        ctx = k.phone(b, handle, camera=True, init=f"localStorage.setItem('sendit-onboarded-{k.UID}', '1'); localStorage.setItem('sendit-save-ask', 'off');")
        pg = W.watch(ctx.new_page())
        pg.goto(w.URL, wait_until="networkidle")
        pg.wait_for_timeout(2500)
        for sel in ["#splash [data-act=close-splash]", ".install-sheet .btn.ghost"]:
            if pg.locator(sel).count():
                pg.locator(sel).first.click(); pg.wait_for_timeout(400)

        def record():
            pg.click("#tabs [data-tab=record]")
            pg.wait_for_timeout(900)
            k.film(pg)
            pg.wait_for_selector("#post-form", timeout=8000)
            return True
        W.attempt("the record button opens the camera, I film, and it shows me the clip to post", record)
        # this phone was never told what I ride (a fresh phone, or the home-screen app): the switch has to be there
        W.attempt("a rider who never said ski or snowboard on this phone still gets the switch on the post form",
                  lambda: pg.locator("#post-form .sport-switch button").count() == 2)
        pg.screenshot(path=w.SHOTS / "story2-1-review.png")

        seen = []
        def post():
            pg.select_option("#post-trick", index=1)
            pg.click("#post-btn")
            for _ in range(14):                              # watch the button while the video goes up
                t = pg.evaluate("() => { const b = document.getElementById('post-btn'); return b ? b.textContent : ''; }")
                if t: seen.append(t)
                pg.wait_for_timeout(120)
            return state["upload_seen"]
        W.attempt("Post sends the video", post)
        W.check("...and I see it upload: the button counts up in percent", any(re.search(r"\d+%", t) for t in seen), sorted(set(seen)))
        pg.screenshot(path=w.SHOTS / "story2-2-uploading.png")

        def next_steps():
            pg.wait_for_selector("#posted-sheet.open", timeout=10000)
            t = pg.locator("#posted-sheet").inner_text().lower()
            return ("posted" in t and "riders call it" in t and "needs 2 calls" in t and "bell" in t and re.search(r"\+\d+ pts", t) is not None, t)
        r = [None]
        def next_ok():
            good, t = next_steps(); r[0] = t; return good
        W.attempt("then it tells me what happens next: posted -> riders call it (needs 2 calls) -> +points, and the bell will say", next_ok)
        pg.wait_for_timeout(500)
        pg.screenshot(path=w.SHOTS / "story2-3-posted.png")
        W.check("the clip row really was saved", any("/rest/v1/clips" in x for x in w.writes))

        def in_feed():
            t = pg.locator("#clip-new1").inner_text().lower()
            return "riders are calling it" in t and "needs 2 more calls" in t
        W.attempt("behind it, my clip is first in the feed: 'riders are calling it · needs 2 more calls'", in_feed)

        def go_judge():
            pg.locator("#posted-sheet [data-act=posted-judge]").click()
            pg.wait_for_timeout(1200)
            return pg.locator(".judge-item").count() == 3 and pg.locator("#posted-sheet.open").count() == 0
        W.attempt("one tap from there: call the 3 clips waiting on me while I wait", go_judge)

        def on_me():
            pg.click("#tabs [data-act=me]")
            pg.wait_for_timeout(1500)
            return "2 calls to go" in pg.locator(".sheet-grid .tile").first.inner_text().lower()
        W.attempt("on Me, the clip is marked '2 calls to go' until riders decide", on_me)

        def one_sport():
            pg.evaluate("localStorage.setItem('sendit-sports', 'snowboard'); localStorage.setItem('sendit-sport', 'snowboard')")
            pg.reload(wait_until="networkidle")
            pg.wait_for_timeout(2500)
            pg.click("#tabs [data-tab=record]")
            pg.wait_for_timeout(900)
            k.film(pg)
            pg.wait_for_selector("#post-form", timeout=8000)
            names = " ".join(k.texts(pg, "#post-grab option")).lower()
            return pg.locator("#post-form .sport-switch").count() == 0 and "indy" in names
        W.attempt("once I've said I only snowboard, the switch is gone and the form is snowboard tricks", one_sport)
        pg.screenshot(path=w.SHOTS / "story2-4-me.png", full_page=True)
        b.close()
    srv.shutdown()
    W.finish()


if __name__ == "__main__":
    main()
