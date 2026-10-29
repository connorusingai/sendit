"""Clip links (?clip=ID): a friend's link opens that exact clip, even if they have to sign up first.

Same fake database as ui_walk.py (nothing reaches the real one).

Run:  .venv-test\\Scripts\\python.exe tests\\share_walk.py        (from dev\\sendit)

Checks:
  1. Signed out + clip link: the landing page says a friend sent a clip.
  2. Signed in + clip link: the Feed opens with that clip first.
  3. Signed in + link to a removed clip: a plain message, no errors.
  4. "Send this clip" in the ⋯ menu shares a ?clip= link.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ui_walk as w  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

SHARED = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
GONE = "99999999-8888-7777-6666-555555555555"
OTHER = {**w.CLIP, "id": SHARED, "user_id": "22222222-0000-0000-0000-000000000000", "trick_id": "bs360",
         "profiles": {"username": "pal", "points": 300}}

PAL = {"id": OTHER["user_id"], "username": "pal", "points": 300, "rating": 1000}


def handle(route, req):
    single = "vnd.pgrst.object" in req.headers.get("accept", "")   # .maybeSingle() may ask for a list or one object
    if "/rest/v1/clips" in req.url and f"id=eq.{SHARED}" in req.url:
        return route.fulfill(json=OTHER if single else [OTHER])
    if "/rest/v1/clips" in req.url and f"id=eq.{GONE}" in req.url:
        return route.fulfill(json=[])
    if "/rest/v1/profiles" in req.url and "username=eq.pal" in req.url:
        return route.fulfill(json=PAL if single else [PAL])
    return w.handle(route, req)


def page(b, signed_in, logs):
    ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    init = "navigator.share = async d => { window.__shared = d; };"
    if signed_in:
        init += f"localStorage.setItem('sb-{w.REF}-auth-token', {json.dumps(json.dumps(w.session))});"
    ctx.add_init_script(init)
    ctx.route(f"https://{w.REF}.supabase.co/**", handle)
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: logs.append(f"PAGEERROR: {e}"))
    return pg


def main():
    srv, logs, ok = w.serve(), [], []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")

        pg = page(b, False, logs)
        pg.goto(w.URL + f"?clip={SHARED}", wait_until="networkidle"); pg.wait_for_timeout(1500)
        ok.append(("signed out: 'a friend sent you a clip' note", pg.locator(".sent-you").count() == 1))
        ok.append(("signed out: link cleaned from the address bar", "clip=" not in pg.url))
        pg.screenshot(path=w.SHOTS / "share-1-landing.png")

        pg = page(b, True, logs)
        pg.goto(w.URL + f"?clip={SHARED}", wait_until="networkidle"); pg.wait_for_timeout(4000)
        first = pg.locator("#reel > .reel-item:not(.intro)").first
        ok.append(("signed in: Feed opened", pg.locator("#reel").count() == 1))
        ok.append(("signed in: shared clip is first", first.get_attribute("data-id") == SHARED if first.count() else False))
        pg.screenshot(path=w.SHOTS / "share-2-feed.png")

        pg.click(f'[id="clip-{w.CLIP["id"]}"] [data-act=clip-menu]', force=True)
        pg.wait_for_timeout(400)
        btn = pg.locator("[data-act=share-link]").first
        if btn.count():
            btn.click(); pg.wait_for_timeout(400)
            d = pg.evaluate("window.__shared") or {}
            ok.append(("menu: shares a ?clip= link", "?clip=" in d.get("url", "")))
            print("   shared text:", d.get("text"))
        else:
            ok.append(("menu: shares a ?clip= link", False))

        pg = page(b, True, logs)
        pg.goto(w.URL + f"?clip={GONE}"); pg.wait_for_timeout(2500)
        msg = pg.evaluate("document.getElementById('toast').textContent")
        ok.append(("removed clip: plain message", "removed" in msg or "Couldn't open" in msg))
        print("   toast:", msg)

        # App invites (?from=USERNAME)
        pg = page(b, False, logs)
        pg.goto(w.URL + "?from=pal", wait_until="networkidle"); pg.wait_for_timeout(1500)
        ok.append(("invite, signed out: '@pal invited you' note", "@pal invited you" in (pg.locator(".sent-you").inner_text() if pg.locator(".sent-you").count() else "")))
        pg = page(b, True, logs)
        pg.goto(w.URL + "?from=pal", wait_until="networkidle"); pg.wait_for_timeout(4000)
        ok.append(("invite, signed in: Squad shows @pal to add", pg.locator("#view").inner_text().count("pal") > 0 and pg.locator("[data-act=add-friend], [data-act=addfriend], [data-act=friend-add]").count() > 0))
        pg.screenshot(path=w.SHOTS / "share-3-invited.png")
        pg.evaluate("document.querySelector('#tabs [data-tab=lodge]').click()"); pg.wait_for_timeout(800)
        pg.evaluate("window.__shared = null; document.querySelector('.base-extra [data-act=invite]').click()"); pg.wait_for_timeout(400)
        d = pg.evaluate("window.__shared") or {}
        ok.append(("Base invite button shares ?from= link", "?from=walker" in d.get("url", "")))
        print("   invite text:", d.get("text"))
        b.close()
    srv.shutdown()
    for name, good in ok:
        print("PASS" if good else "FAIL", name)
    print("page errors:", logs or "none")
    sys.exit(0 if all(g for _, g in ok) and not logs else 1)


if __name__ == "__main__":
    main()
