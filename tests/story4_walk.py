"""Story 4: when riders call my clip landed, I get the STOMPED moment and points, and I rank up.
It feels like a game, not a website.

Two of my clips got called landed while the app was closed (+60, then +140). 120 points before = a blue pass;
320 after = black. So: two STOMPED moments, one after the other, then the pass taps the gate and turns black.

Run:  .venv-test\\Scripts\\python.exe tests\\story4_walk.py        (from the app folder)
"""
import datetime as dt

from playwright.sync_api import sync_playwright

import story_kit as k
from story_kit import w

ME = {**w.ME, "points": 320}


def ago(hours):
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def mine(cid, trick, pts, hours):
    # posted a day before it was verified; verified a few hours ago (the bell only counts the last day as new)
    return {"id": cid, "user_id": k.UID, "trick_id": trick, "combo": [], "grab": "No grab", "status": "verified", "points_awarded": pts,
            "created_at": ago(hours + 24), "verified_at": ago(hours), "video_path": f"{k.UID}/{cid}.mp4",
            "resort": "Eldora", "profiles": {"username": "walker", "points": 320}, "likes": [{"count": 0}], "comments": [{"count": 0}]}


CLIPS = [mine("m2", "cork720", 140, 2), mine("m1", "backflip", 60, 5)]      # newest first, like the database sends them


def handle(route, req):
    path, m = k.path_of(req), req.method
    if m == "GET" and path.startswith("/rest/v1/profiles"):
        return route.fulfill(json=ME if k.wants_one(req) else [])
    if m == "GET" and path.startswith("/rest/v1/clips"):
        return route.fulfill(json=[] if "rider_ok=eq.false" in path else CLIPS)
    return w.handle(route, req)


def main():
    W = k.Walk("Story 4: riders called it landed -> STOMPED, points, rank up")
    srv = w.serve()
    with sync_playwright() as p:
        b = k.launch(p)
        ctx = k.phone(b, handle, init=f"if (!localStorage.getItem('seen-status-{k.UID}')) localStorage.setItem('seen-status-{k.UID}', JSON.stringify({{m1: 'pending', m2: 'pending'}}));"
                                        f"localStorage.setItem('sendit-onboarded-{k.UID}', '1');")
        pg = W.watch(ctx.new_page())
        pg.goto(w.URL, wait_until="networkidle")

        def first():
            pg.wait_for_selector("#reward", timeout=8000)
            pg.wait_for_timeout(1400)                        # the points count up
            t = pg.locator(".reward-card").inner_text().lower()
            return (pg.locator("#reward .rw-stamp svg").count() == 1 and "+60" in t and "backflip" in t and "riders called it landed" in t, t)
        r = [""]
        def first_ok():
            good, r[0] = first(); return good
        W.attempt("the app opens on the STOMPED moment for the first clip: the stamp, +60 (counted up), 'Riders called it landed'", first_ok)
        W.check("...it says there's one more to collect", "1 more to collect" in r[0], r[0].replace("\n", " ")[:90])
        W.attempt("...with the bar to my next pass and a glove-size Collect (56px+)",
                  lambda: pg.locator("#rw-bar").count() == 1 and "blue" in pg.locator("#rw-rank").inner_text().lower()
                  and pg.locator("[data-act=reward-collect]").bounding_box()["height"] >= 56)
        pg.screenshot(path=w.SHOTS / "story4-1-stomped.png")

        def second():
            pg.click("[data-act=reward-collect]")
            pg.wait_for_selector("#reward", timeout=4000)
            pg.wait_for_timeout(2300)                        # counts up and breaks through into the next pass
            t = pg.locator(".reward-card").inner_text().lower()
            return "+140" in t and "cork 720" in t and "black" in pg.locator("#rw-rank").inner_text().lower()
        W.attempt("Collect -> the second clip gets its own moment (+140), and its bar breaks through from blue into black", second)
        pg.screenshot(path=w.SHOTS / "story4-2-second.png")

        def rank_up():
            pg.click("[data-act=reward-collect]")
            pg.wait_for_selector(".gate", timeout=4000)
            pg.wait_for_timeout(1500)
            pg.screenshot(path=w.SHOTS / "story4-3-gate.png")
            pg.locator(".gate").click()                      # a tap skips to the end
            pg.wait_for_timeout(700)
            word = pg.locator("#g-word").inner_text().lower()
            pg.screenshot(path=w.SHOTS / "story4-4-rankup.png")
            return word.strip() == "black" and pg.locator(".g-stamp").count() == 1
        W.attempt("Collect -> rank up: my pass taps the gate and the same pass turns black, RANK UP stamped on", rank_up)

        def back_on_base():
            pg.click(".ru-go")
            pg.wait_for_timeout(900)
            label = pg.locator(".base .pass").get_attribute("aria-label").lower()
            return pg.locator("#overlay").inner_html().strip() == "" and "black" in label and "320" in label
        W.attempt("let's go -> Base, with the black pass and 320 points on it", back_on_base)

        def bell():
            n = pg.locator("#bell-chip .badge").inner_text()
            pg.click("#bell-chip")
            pg.wait_for_timeout(700)
            rows = " | ".join(k.texts(pg, ".nt")).lower()
            return n in ("2", "3") and "backflip got verified. +60" in rows and "cork 720 got verified. +140" in rows
        W.attempt("and the bell keeps both results (+60, +140) so I can find them again", bell)

        def once():
            pg.reload(wait_until="networkidle")
            pg.wait_for_timeout(2500)
            return pg.locator("#reward").count() == 0 and pg.locator(".gate").count() == 0
        W.attempt("opening the app again doesn't replay the moment", once)
        b.close()
    srv.shutdown()
    W.finish()


if __name__ == "__main__":
    main()
