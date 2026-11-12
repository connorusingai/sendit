"""Story 5: I challenge a friend to Game of S.K.I. We take turns, and the app tells me (in the inbox) when it's
my turn.

Run:  .venv-test\\Scripts\\python.exe tests\\story5_walk.py        (from the app folder)
"""
import datetime as dt
import json

from playwright.sync_api import sync_playwright

import story_kit as k
from story_kit import w

MAYA = "aaaaaaaa-0000-0000-0000-00000000000a"
ME_BITS = {"id": k.UID, "username": "walker", "points": 1284, "rating": 1000}
MAYA_BITS = {"id": MAYA, "username": "maya", "points": 420, "rating": 1040}
FRIEND = {"requester": k.UID, "addressee": MAYA, "status": "accepted", "created_at": "2026-11-01T12:00:00Z", "req": ME_BITS, "addr": MAYA_BITS}
state = {"stage": "none", "moves": [], "rpc": []}


def iso(minutes=0):
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def duel():
    base = {"id": "d1", "challenger": k.UID, "opponent": MAYA, "status": "active", "letters_challenger": 0, "letters_opponent": 0,
            "created_at": iso(30), "winner": None, "rating_change": None, "ch": ME_BITS, "op": MAYA_BITS}
    if state["stage"] == "mine_to_set":
        return [{**base, "turn": k.UID, "phase": "set", "trick_id": None, "updated_at": iso(30)}]
    if state["stage"] == "her_match":                        # I landed a 360, she has to match it
        return [{**base, "turn": MAYA, "phase": "match", "trick_id": "360", "updated_at": iso(20)}]
    if state["stage"] == "my_match":                         # she missed (takes S), I set again and bailed, she set a 540: my turn to match
        return [{**base, "turn": k.UID, "phase": "match", "trick_id": "540", "letters_opponent": 1, "updated_at": iso(1)}]
    return []


def handle(route, req):
    path, m = k.path_of(req), req.method
    if m == "GET" and path.startswith("/rest/v1/friendships"):
        return route.fulfill(json=[FRIEND])
    if m == "GET" and path.startswith("/rest/v1/duels"):
        return route.fulfill(json=duel())
    if m == "GET" and path.startswith("/rest/v1/duel_moves"):
        return route.fulfill(json=state["moves"])
    if "/rpc/start_duel" in path:
        state["rpc"].append(("start_duel", req.post_data or ""))
        state["stage"] = "mine_to_set"
        return route.fulfill(json="d1")
    if "/rpc/duel_move" in path:
        state["rpc"].append(("duel_move", req.post_data or ""))
        state["stage"] = "her_match"
        state["moves"] = [{"id": 1, "duel_id": "d1", "user_id": k.UID, "kind": "set", "trick_id": "360", "landed": True, "clip_id": "x", "clips": {"video_path": f"{k.UID}/x.mp4"}}]
        return route.fulfill(json=None)
    if m == "POST" and path.startswith("/rest/v1/clips"):
        return route.fulfill(status=201, json={"id": "99999999-0000-0000-0000-000000000099"})
    return w.handle(route, req)


def main():
    W = k.Walk("Story 5: challenge a friend to S.K.I., take turns, and hear when it's my turn")
    srv = w.serve()
    with sync_playwright() as p:
        b = k.launch(p, camera=True)
        ctx = k.phone(b, handle, camera=True, init=f"localStorage.setItem('seen-status-{k.UID}', JSON.stringify({{c1: 'verified'}}));"
                                                     f"localStorage.setItem('sendit-onboarded-{k.UID}', '1'); localStorage.setItem('sendit-squad', 'friends');")
        pg = W.watch(ctx.new_page())
        pg.goto(w.URL, wait_until="networkidle")
        pg.wait_for_timeout(2500)

        def challenge():
            pg.click("#tabs [data-tab=duels]")
            pg.wait_for_timeout(1000)
            row = pg.locator(".friend", has_text="@maya")
            row.locator("[data-act=challenge]").click()
            pg.wait_for_timeout(1500)
            t = pg.locator(".turn").inner_text().lower()
            return any(n == "start_duel" and MAYA in body for n, body in state["rpc"]) and "your turn: set a trick" in t
        W.attempt("Crew > friends > Challenge on @maya starts the game and it's my turn to set a trick", challenge)
        pg.screenshot(path=w.SHOTS / "story5-1-set.png")

        def set_trick():
            pg.select_option("#duel-trick", "360")
            pg.click("[data-act=duel-record]")
            pg.wait_for_timeout(900)
            k.film(pg)
            pg.wait_for_selector("#duel-send", timeout=8000)
            pg.click("#duel-send")
            pg.wait_for_timeout(3500)
            sent = [json.loads(body) for n, body in state["rpc"] if n == "duel_move"]
            t = pg.locator(".turn").inner_text().lower()
            return bool(sent) and sent[0]["p_landed"] is True and sent[0]["p_trick"] == "360" and bool(sent[0]["p_clip"]) and "@maya's turn" in t and "match your 360" in t
        W.attempt("I pick a 360, film it, send it: the move is saved with my clip, and now it's @maya's turn to match", set_trick)
        pg.screenshot(path=w.SHOTS / "story5-2-their-turn.png")

        # ---- later: she's played, it's on me. Open the app fresh. ----
        state["stage"] = "my_match"
        state["moves"].append({"id": 4, "duel_id": "d1", "user_id": MAYA, "kind": "set", "trick_id": "540", "landed": True, "clip_id": "y", "clips": {"video_path": f"{MAYA}/y.mp4"}})
        pg.reload(wait_until="networkidle")
        pg.wait_for_timeout(3000)

        def bell():
            return pg.locator("#bell-chip .badge").count() == 1 and pg.locator("#bell-chip .badge").inner_text() == "1"
        W.attempt("when it's my turn again, the bell shows 1 new", bell)

        def base_line():
            line = pg.locator(".base .duel-turn").first
            t = line.inner_text().lower().replace("\n", " ")
            return "your turn" in t and "@maya" in t and "match the 540" in t
        W.attempt("...and Base says it in one line: 'your turn vs @maya · match the 540'", base_line)
        pg.screenshot(path=w.SHOTS / "story5-3-base.png")

        def inbox():
            pg.click("#bell-chip")
            pg.wait_for_timeout(700)
            row = pg.locator(".nt.new", has_text="Your turn in S.K.I. vs @maya")
            ok = row.count() == 1
            pg.screenshot(path=w.SHOTS / "story5-4-inbox.png")
            row.click()
            pg.wait_for_timeout(1200)
            t = pg.locator(".turn").inner_text().lower()
            return ok and "match the 540" in t and pg.locator("[data-act=duel-record][data-kind=match]").count() == 1
        W.attempt("the inbox says 'Your turn in S.K.I. vs @maya', and tapping it opens the game on 'match the 540' with Film my match", inbox)
        pg.screenshot(path=w.SHOTS / "story5-5-match.png")

        def from_base():
            pg.click("#tabs [data-tab=lodge]")
            pg.wait_for_timeout(700)
            pg.locator(".base .duel-turn").first.click()
            pg.wait_for_timeout(1000)
            return "match the 540" in pg.locator(".turn").inner_text().lower()
        W.attempt("the Base line opens the same game in one tap", from_base)
        b.close()
    srv.shutdown()
    W.finish()


if __name__ == "__main__":
    main()
