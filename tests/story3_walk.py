"""Story 3: I open the feed and judge other riders' clips with quick swipes. Each one tells me how many more
calls it needs.

Run:  .venv-test\\Scripts\\python.exe tests\\story3_walk.py        (from the app folder)
"""
import time

from playwright.sync_api import sync_playwright

import story_kit as k
from story_kit import w

votes = []
mode = {"calls_left": True}
LEFT = {"o4": 2, "o5": 1, "o6": 2}


def handle(route, req):
    path, m = k.path_of(req), req.method
    if m == "GET" and path.startswith("/rest/v1/clips"):
        return route.fulfill(json=k.bot.CLIPS)
    if m == "POST" and path.startswith("/rest/v1/votes"):
        votes.append(req.post_data or "")
        return route.fulfill(status=201, json=[])
    if "/rpc/calls_left" in path:
        if not mode["calls_left"]:                           # the database before 030 is pasted: no such function
            return route.fulfill(status=404, json={"code": "PGRST202", "message": "Could not find the function public.calls_left(p_clips) in the schema cache"})
        return route.fulfill(json=[{"clip_id": c, "calls_left": n} for c, n in LEFT.items()])
    return w.handle(route, req)


def swipe(pg, sel, dx):
    """A quick thumb swipe across a clip: right = landed, left = bailed. Returns how long it took."""
    box = pg.locator(sel).bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + 150
    t0 = time.time()
    pg.mouse.move(x, y); pg.mouse.down()
    for i in range(1, 6):
        pg.mouse.move(x + dx * i / 5, y, steps=2)
    pg.mouse.up()
    return time.time() - t0


def open_app(b, W):
    ctx = k.phone(b, handle, init=f"localStorage.setItem('seen-status-{k.UID}', JSON.stringify({{c1: 'verified'}}));")
    pg = W.watch(ctx.new_page())
    pg.goto(w.URL, wait_until="networkidle")
    pg.wait_for_timeout(2500)
    return ctx, pg


def main():
    W = k.Walk("Story 3: judge with quick swipes; every clip says how many more calls it needs")
    srv = w.serve()
    with sync_playwright() as p:
        b = k.launch(p)
        ctx, pg = open_app(b, W)

        def open_judge():
            t = pg.locator(".calls").first.inner_text().lower()
            pg.locator(".calls").first.click()
            pg.wait_for_timeout(1200)
            return "3 clips need your call" in t and pg.locator(".judge-item").count() == 3
        W.attempt("Base says '3 clips need your call' and one tap opens them", open_judge)

        def says_left():
            got = {el: pg.locator(f"#reel-{el} .jfoot").inner_text().lower() for el in LEFT}
            return all(f"needs {n} more call{'s' if n > 1 else ''}" in got[c] for c, n in LEFT.items()), got
        r = [None]
        def left_ok():
            good, got = says_left(); r[0] = got; return good
        W.attempt("each clip says how many more calls it needs (2, 1, 2)", left_ok)
        pg.screenshot(path=w.SHOTS / "story3-1-judge.png")

        took = []
        def swipe_right():
            took.append(swipe(pg, "#reel-o4", 170))
            pg.wait_for_timeout(600)
            stamped = pg.locator("#reel-o4 .reel-done.yes").count() == 1
            pg.screenshot(path=w.SHOTS / "story3-2-stamped.png")
            pg.wait_for_timeout(3200)                        # the 3 second Undo window, then it's saved
            return stamped and any('"clip_id":"o4"' in v.replace(" ", "") and '"landed":true' in v.replace(" ", "") for v in votes)
        W.attempt("swipe right = landed: the stamp slams on and the call is saved", swipe_right)

        def swipe_left():
            pg.wait_for_timeout(700)
            took.append(swipe(pg, "#reel-o5", -170))
            pg.wait_for_timeout(3900)
            return any('"clip_id":"o5"' in v.replace(" ", "") and '"landed":false' in v.replace(" ", "") for v in votes)
        W.attempt("swipe left = bailed: saved too", swipe_left)
        W.check("...each swipe is quick (under a second)", bool(took) and max(took) < 1.0, [f"{t:.2f}s" for t in took])

        def feed_card():
            pg.click("#tabs [data-tab=feed]")
            pg.wait_for_timeout(1500)
            card = pg.locator("#reel-o6")
            return card.count() == 1 and "needs 2 more calls" in card.inner_text().lower() and card.locator("[data-act=vote][data-y='1']").count() == 1
        W.attempt("in the feed, a clip still waiting on me carries Bailed / Landed and 'needs 2 more calls'", feed_card)
        pg.screenshot(path=w.SHOTS / "story3-3-feed.png")
        ctx.close()

        # ---- before 030 is pasted: no number, nothing broken ----
        mode["calls_left"] = False
        ctx, pg = open_app(b, W)
        def no_number():
            pg.locator(".calls").first.click()
            pg.wait_for_timeout(1200)
            t = pg.locator("#reel-o4 .jfoot").inner_text().lower()
            return "anonymous" in t and "needs" not in t and pg.locator("#reel-o4 [data-act=vote][data-y='1']").count() == 1
        W.attempt("until SQL 030 is pasted: no number is shown, and judging works exactly as before", no_number)
        ctx.close()
        b.close()
    srv.shutdown()
    W.finish()


if __name__ == "__main__":
    main()
