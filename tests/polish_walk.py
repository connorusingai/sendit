"""Polish 11/13: one-tap trick buttons on the post form, the 72-hour S.K.I. clock, and the founder's vouch list.

Run:  .venv-test\\Scripts\\python.exe tests\\polish_walk.py        (from the app folder)
"""
import datetime as dt
import json

from playwright.sync_api import sync_playwright

import story_kit as k
from story_kit import w

MAYA = "aaaaaaaa-0000-0000-0000-00000000000a"
NEWB = "bbbbbbbb-0000-0000-0000-00000000000b"
ME = {**w.ME, "is_founder": True, "home_resort": "Eldora"}
ME_BITS = {"id": k.UID, "username": "walker", "points": 1284, "rating": 1000}
MAYA_BITS = {"id": MAYA, "username": "maya", "points": 420, "rating": 1040}
FRIEND = {"requester": k.UID, "addressee": MAYA, "status": "accepted", "created_at": "2026-11-01T12:00:00Z", "req": ME_BITS, "addr": MAYA_BITS}
state = {"rpc": [], "claimed": False, "vouched": False}
# The first recording on this page hands back nothing, like desktop Chrome's first H.264 take did on 11/13
EMPTY_FIRST_TAKE = """(() => { const R = window.MediaRecorder; if (!R) return; let first = true;
  window.MediaRecorder = class extends R {
    constructor(s, o){ super(s, o); this._empty = first; first = false; }
    set ondataavailable(f){ super.ondataavailable = this._empty ? (() => f({data: new Blob([])})) : f; }
    get ondataavailable(){ return super.ondataavailable; } };
  window.MediaRecorder.isTypeSupported = t => R.isTypeSupported(t); })();"""


def ago(hours):
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def duels():
    base = {"challenger": k.UID, "opponent": MAYA, "letters_challenger": 0, "letters_opponent": 1, "created_at": ago(200),
            "rating_change": None, "winner": None, "timed_out": False, "ch": ME_BITS, "op": MAYA_BITS}
    stale = {**base, "id": "d1", "status": "active", "turn": MAYA, "phase": "match", "trick_id": "360", "updated_at": ago(80)}
    if state["claimed"]:
        stale = {**stale, "status": "done", "turn": None, "winner": k.UID, "rating_change": 17, "timed_out": True, "updated_at": ago(0)}
    mine = {**base, "id": "d2", "opponent": "cccccccc-0000-0000-0000-00000000000c", "status": "active", "turn": k.UID, "phase": "set",
            "trick_id": None, "updated_at": ago(20), "op": {"id": "cccccccc-0000-0000-0000-00000000000c", "username": "theo", "points": 10, "rating": 990}}
    return [stale, mine]


def handle(route, req):
    path, m = k.path_of(req), req.method
    if m == "GET" and path.startswith("/rest/v1/profiles") and k.wants_one(req):
        return route.fulfill(json=ME)
    if m == "GET" and path.startswith("/rest/v1/friendships"):
        return route.fulfill(json=[FRIEND])
    if m == "GET" and path.startswith("/rest/v1/duels"):
        return route.fulfill(json=duels())
    if m == "GET" and path.startswith("/rest/v1/duel_moves"):
        return route.fulfill(json=[{"id": 1, "duel_id": "d1", "user_id": k.UID, "kind": "set", "trick_id": "360", "landed": True, "clip_id": None, "clips": None}])
    if "/rpc/claim_duel" in path:
        state["rpc"].append(("claim_duel", req.post_data or "")); state["claimed"] = True
        return route.fulfill(json="won")
    if "/rpc/founder_queue" in path:
        return route.fulfill(json=[])
    if "/rpc/founder_stats" in path:
        return route.fulfill(json={"riders": 3, "new_7d": 1, "active_1d": 1, "active_7d": 2, "funnel": {}, "by_src": [], "top_events_7d": [], "riders_list": []})
    if "/rpc/founder_ai_stats" in path:
        return route.fulfill(status=404, json={"message": "not here"})
    if "/rpc/founder_new_riders" in path:
        return route.fulfill(json=[{"id": NEWB, "username": "jess", "joined": ago(30), "vouched": state["vouched"], "counts": 1 if state["vouched"] else 0.25}])
    if "/rpc/vouch" in path:
        state["rpc"].append(("vouch", req.post_data or "")); state["vouched"] = json.loads(req.post_data)["p_on"]
        return route.fulfill(json=None)
    if m == "GET" and path.startswith("/rest/v1/clips") and "rider_ok=eq.false" in path:
        return route.fulfill(json=[])
    return w.handle(route, req)


def main():
    W = k.Walk("Polish 11/13: one-tap tricks, the S.K.I. clock, vouching")
    srv = w.serve()
    with sync_playwright() as p:
        b = k.launch(p, camera=True)
        ctx = k.phone(b, handle, camera=True, init=f"localStorage.setItem('seen-status-{k.UID}', JSON.stringify({{c1: 'verified'}}));"
                                                     f"localStorage.setItem('sendit-onboarded-{k.UID}', '1'); localStorage.setItem('sendit-squad', 'duels');"
                                                     "localStorage.setItem('sendit-sports', 'ski');")
        pg = W.watch(ctx.new_page())
        pg.goto(w.URL, wait_until="networkidle")
        pg.wait_for_timeout(2500)

        # ---- post form ----
        def picks():
            pg.click("#tabs [data-tab=record]")
            pg.wait_for_timeout(800)
            k.film(pg)
            pg.wait_for_selector("#post-form", timeout=8000)
            q = pg.locator(".qpick")
            hs = [q.nth(i).bounding_box()["height"] for i in range(q.count())]
            return q.count() >= 3 and min(hs) >= 56 and pg.input_value("#post-trick") == ""
        W.attempt("after filming, the post form shows big trick buttons (3+, 56px tall) and still no trick picked for you", picks)
        pg.screenshot(path=w.SHOTS / "polish-1-picks.png")

        def tap_pick():
            first = pg.locator(".qpick").first
            want = first.get_attribute("data-id")
            first.click()
            pg.wait_for_timeout(300)
            return pg.input_value("#post-trick") == want and "on" in (first.get_attribute("class") or "") and pg.locator("#post-pts").inner_text() != "0"
        W.attempt("one tap on a button picks that trick (the list below follows) and shows what it pays", tap_pick)

        def resort():
            line = pg.locator(".resort-line")
            ok = line.count() == 1 and "eldora" in line.inner_text().lower() and not pg.locator("#post-resort").is_visible()
            pg.click("[data-act=post-resort-open]")
            pg.wait_for_timeout(300)
            return ok and pg.locator("#post-resort").is_visible() and pg.input_value("#post-trick") != ""
        W.attempt("the resort is one line ('at Eldora'); 'Somewhere else?' opens the list and keeps the trick picked", resort)
        pg.screenshot(path=w.SHOTS / "polish-2-picked.png")
        pg.goto(w.URL, wait_until="networkidle")              # start over from Base
        pg.wait_for_timeout(2500)

        # ---- S.K.I. clock ----
        def my_clock():
            pg.click("#tabs [data-tab=duels]")
            pg.wait_for_timeout(900)
            pg.locator(".duel-row", has_text="@theo").click()
            pg.wait_for_timeout(900)
            t = pg.locator(".turn").inner_text().lower()
            return "you have 2 days left to move" in t
        W.attempt("on my turn the game says how long I have ('You have 2 days left to move')", my_clock)

        def claim():
            pg.click("[data-act=duels-home]")
            pg.wait_for_timeout(600)
            row = pg.locator(".duel-row", has_text="@maya")
            gone = "ran out of time" in row.inner_text().lower()
            row.click()
            pg.wait_for_timeout(900)
            t = pg.locator(".turn").inner_text().lower()
            btn = pg.locator("[data-act=claim-duel]")
            ok = gone and "haven't moved in 3 days" in t and btn.count() == 1 and "claim the win" in btn.inner_text().lower()
            pg.screenshot(path=w.SHOTS / "polish-3-claim.png")
            btn.click()
            pg.wait_for_timeout(1500)
            done = pg.locator(".turn").inner_text().lower()
            return ok and any(n == "claim_duel" for n, _ in state["rpc"]) and "you won" in done and "ran out of time" in done
        W.attempt("@maya hasn't moved in 3 days: 'Claim the win' ends it, and the game says she ran out of time", claim)
        pg.screenshot(path=w.SHOTS / "polish-4-won.png")

        # ---- vouch ----
        def vouch():
            pg.click("#tabs [data-act=me]")
            pg.wait_for_timeout(900)
            pg.click("[data-act=fdash]")
            pg.wait_for_timeout(1200)
            row = pg.locator(".fd-riders.vouch > div", has_text="@jess")
            ok = row.count() == 1 and "count ¼" in row.inner_text()
            row.locator("[data-act=vouch]").click()
            pg.wait_for_timeout(1200)
            row = pg.locator(".fd-riders.vouch > div", has_text="@jess")
            sent = [json.loads(body) for n, body in state["rpc"] if n == "vouch"]
            return ok and sent and sent[0] == {"p_user": NEWB, "p_on": True} and "count fully" in row.inner_text() and "vouched" in row.inner_text().lower()
        W.attempt("Founder dashboard: a week-old rider shows 'calls count ¼'; Vouch makes them count fully", vouch)
        if pg.locator(".fd-riders.vouch").count(): pg.locator(".fd-riders.vouch").scroll_into_view_if_needed()
        pg.screenshot(path=w.SHOTS / "polish-5-vouch.png")

        # ---- an empty take never gets posted (first H.264 take in desktop Chrome can be 0 bytes) ----
        ctx2 = k.phone(b, handle, camera=True, init=EMPTY_FIRST_TAKE + f"localStorage.setItem('sendit-onboarded-{k.UID}', '1');")
        pg2 = W.watch(ctx2.new_page())
        pg2.goto(w.URL, wait_until="networkidle")
        pg2.wait_for_timeout(2500)

        def empty_take():
            pg2.click("#tabs [data-tab=record]")
            pg2.wait_for_timeout(800)
            pg2.locator("[data-act=cam-open]").first.click()
            pg2.wait_for_timeout(1500)
            pg2.locator("[data-act=rec-start]").first.click()
            pg2.wait_for_timeout(2000)
            pg2.locator("[data-act=rec-stop]").first.click()
            pg2.wait_for_timeout(1500)
            bounced = pg2.locator("#post-form").count() == 0 and pg2.locator("[data-act=rec-start]").count() == 1
            said = "didn't save" in " ".join(pg2.locator(".toast").all_inner_texts()).lower()
            k.film(pg2)                                      # the second take is fine
            pg2.wait_for_selector("#post-form", timeout=8000)
            return bounced and said
        W.attempt("an empty take goes back to the camera with 'That take didn't save. Film it again.'; the next take reaches Post", empty_take)
        b.close()
    srv.shutdown()
    W.finish()


if __name__ == "__main__":
    main()
