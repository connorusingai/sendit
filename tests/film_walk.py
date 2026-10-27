"""Film a friend (017): you film your buddy on your phone, tag them, and the clip waits on THEIR Base.

Same fake database as ui_walk.py (nothing reaches the real one).

Run:  .venv-test\\Scripts\\python.exe tests\\film_walk.py        (from dev\\sendit)

Checks:
  1. Filmer: the post form has "Who's riding?" with your friend in it.
  2. Filmer: posting for the friend calls post_for_friend (not a normal insert) and stays on the camera.
  3. Rider: Base shows "@pal filmed you" with Keep / Not me, and a badge on the Base tab.
  4. Rider: Keep calls answer_filmed_clip.
  5. Feed: a kept clip says who filmed it.
  6. Wrong rider (019): your own clip still being judged can be given to @pal from the ... menu.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ui_walk as w  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

PAL = {"id": "22222222-0000-0000-0000-000000000000", "username": "pal", "points": 300, "rating": 1000}
FRIENDSHIP = {"requester": w.UID, "addressee": PAL["id"], "status": "accepted", "created_at": "2026-10-20T12:00:00Z",
              "req": {"id": w.UID, "username": "walker", "points": 1284}, "addr": PAL}
WAITING = {**w.CLIP, "id": "f1", "status": "pending", "points_awarded": None, "trick_id": "bs360", "filmed_by": PAL["id"],
           "rider_ok": False, "resort": "Eldora"}
KEPT = {**w.CLIP, "id": "f2", "filmed_by": PAL["id"], "rider_ok": True}
OOPS = {**w.CLIP, "id": "m1", "status": "pending", "points_awarded": None, "trick_id": "180", "created_at": "2026-10-27T12:00:00Z"}
rpcs = []


def handle(route, req):
    url = req.url
    if any(f"/rpc/{f}" in url for f in ("post_for_friend", "answer_filmed_clip", "give_clip_to_friend")):
        rpcs.append(f"{url.rsplit('/', 1)[1]} {req.post_data}")
        return route.fulfill(json="new-clip-id" if "post_for_friend" in url else None)
    if req.method == "GET" and "/rest/v1/friendships" in url:
        return route.fulfill(json=[FRIENDSHIP])
    if req.method == "GET" and "/rest/v1/clips" in url and "rider_ok=eq.false" in url:
        return route.fulfill(json=[WAITING])
    if req.method == "GET" and "/rest/v1/clips" in url:
        return route.fulfill(json=[OOPS, KEPT, WAITING])   # the waiting one must stay out of the feed
    if req.method == "GET" and "/rest/v1/profiles" in url and "id=in." in url:
        return route.fulfill(json=[{"id": PAL["id"], "username": "pal"}])
    return w.handle(route, req)


def main():
    srv, logs, ok = w.serve(), [], []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"])
        ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, permissions=["camera"])
        ctx.add_init_script(f"localStorage.setItem('sb-{w.REF}-auth-token', {json.dumps(json.dumps(w.session))});")
        ctx.route(f"https://{w.REF}.supabase.co/**", handle)
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: logs.append(f"PAGEERROR: {e}"))
        pg.goto(w.URL, wait_until="networkidle"); pg.wait_for_timeout(2500)
        pg.mouse.click(195, 420); pg.wait_for_timeout(800)   # past the rank splash

        # Rider side: Base
        pg.evaluate("document.querySelector('#tabs [data-tab=lodge]').click()"); pg.wait_for_timeout(800)
        card = pg.locator("#filmed-f1")
        ok.append(("Base: '@pal filmed you' card", card.count() == 1 and "@pal filmed you" in card.inner_text().lower()))
        ok.append(("Base tab shows a badge", pg.locator("#tabs [data-tab=lodge] .badge").count() == 1))
        pg.screenshot(path=w.SHOTS / "film-1-base.png")
        if card.count():
            card.locator("[data-act=filmed-keep]").click(); pg.wait_for_timeout(1200)
        ok.append(("Keep calls answer_filmed_clip", any("answer_filmed_clip" in r and '"p_keep":true' in r for r in rpcs)))

        # Feed: credit, and the waiting clip stays out
        pg.evaluate("document.querySelector('#tabs [data-tab=feed]').click()"); pg.wait_for_timeout(2000)
        view = pg.locator("#view").inner_text()
        ok.append(("Feed: kept clip says filmed by @pal", "@pal" in view))
        ok.append(("Feed: waiting clip not shown", pg.locator("#clip-f1, [data-id=f1]").count() == 0))

        # Wrong rider: my own clip still being judged can go to @pal from the ... menu
        pg.evaluate("document.querySelector('[id=clip-m1] [data-act=clip-menu]').click()"); pg.wait_for_timeout(500)
        give = pg.locator("[data-act=give-clip]")
        ok.append(("Own judging clip: menu offers 'Wrong rider: it's @pal'", give.count() == 1 and "@pal" in give.inner_text().lower()))
        pg.screenshot(path=w.SHOTS / "film-4-wrong-rider.png")
        if give.count():
            give.click(); pg.wait_for_timeout(1200)
        ok.append(("...which calls give_clip_to_friend", any("give_clip_to_friend" in r and PAL["id"] in r for r in rpcs)))

        # Filmer side: record, pick @pal, post
        pg.evaluate("document.querySelector('#tabs [data-tab=record]').click()"); pg.wait_for_timeout(800)
        cam = pg.locator("[data-act=cam-open]")
        if cam.count():
            cam.first.click(); pg.wait_for_timeout(1500)
        pg.locator("[data-act=rec-start]").first.click(); pg.wait_for_timeout(3000)
        pg.locator("[data-act=rec-stop]").first.click()
        pg.wait_for_selector("#post-form", timeout=8000)
        ok.append(("Post form: 'Who's riding?' lists @pal", pg.locator("#post-rider option", has_text="@pal").count() == 1))
        pg.select_option("#post-rider", PAL["id"]); pg.wait_for_timeout(200)
        ok.append(("Picking @pal explains where it goes", "pal's Base" in pg.locator("#post-rider-hint").inner_text()))
        pg.screenshot(path=w.SHOTS / "film-2-post.png")
        before = len(w.writes)
        pg.select_option("#post-trick", index=1)
        pg.click("#post-btn"); pg.wait_for_timeout(3000)
        ok.append(("Post for a friend calls post_for_friend", any("post_for_friend" in r and PAL["id"] in r for r in rpcs)))
        ok.append(("...and not a normal clip insert", not any("/rest/v1/clips" in x for x in w.writes[before:])))
        ok.append(("...and stays on the camera", pg.locator("#post-form").count() == 0 and "record" in pg.locator("#tabs .on").inner_text().lower()))
        pg.screenshot(path=w.SHOTS / "film-3-after.png")
        print("   tab on:", pg.locator("#tabs .on").all_inner_texts())
        print("   toast:", pg.evaluate("document.getElementById('toast').textContent"))
        b.close()
    srv.shutdown()
    for name, good in ok:
        print("PASS" if good else "FAIL", name)
    print("page errors:", logs or "none")
    sys.exit(0 if all(g for _, g in ok) and not logs else 1)


if __name__ == "__main__":
    main()
