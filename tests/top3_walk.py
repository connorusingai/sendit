"""Critique top 3 (10/30): the can't-reach screen, the full-screen camera, and the post form.

Same fake database as ui_walk.py (nothing reaches the real one).

Run:  ..\sendit\.venv-test\Scripts\python.exe tests\top3_walk.py      (from the repo folder)

Checks:
  1. Database down: a signed-in rider sees "can't reach stomped", not the signed-out page, and it recovers by itself.
  2. Camera: fills the screen with no tabs, the stop button says what it does.
  3. Post form: Post is on screen without scrolling, and nothing posts until a trick is picked.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ui_walk as w  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

down = {"on": True}


def handle(route, req):
    if down["on"] and "/rest/v1/" in req.url and "tricks" not in req.url:
        return route.fulfill(status=500, json={"message": "database down"})
    return w.handle(route, req)


def on_screen(pg, sel):
    return pg.evaluate("""s => { const r = document.querySelector(s).getBoundingClientRect();
        return r.top >= 0 && r.bottom <= innerHeight && r.width > 0; }""", sel)


def main():
    srv, logs, ok = w.serve(), [], []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"])
        ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, permissions=["camera"])
        ctx.add_init_script(f"localStorage.setItem('sb-{w.REF}-auth-token', {json.dumps(json.dumps(w.session))});")
        ctx.route(f"https://{w.REF}.supabase.co/**", handle)
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: logs.append(f"PAGEERROR: {e}"))

        # 1. Database down, then back
        pg.goto(w.URL, wait_until="load"); pg.wait_for_timeout(2500)
        ok.append(("Down: can't-reach screen shows", pg.locator(".cant-reach").count() == 1))
        ok.append(("Down: no signed-out page", pg.locator("text=Make an account").count() == 0))
        ok.append(("Down: Try again and Sign out both there", pg.locator("[data-act=retry-load]").count() == 1 and pg.locator("[data-act=load-signout]").count() == 1))
        pg.screenshot(path=w.SHOTS / "top3-1-cant-reach.png")
        down["on"] = False
        pg.wait_for_timeout(7000)
        ok.append(("Back: recovers by itself", pg.locator(".cant-reach").count() == 0 and pg.locator("#tabbar").is_visible()))
        pg.mouse.click(195, 420); pg.wait_for_timeout(800)   # past the rank splash

        # 2. Camera
        pg.evaluate("document.querySelector('#tabs [data-tab=record]').click()"); pg.wait_for_timeout(800)
        ok.append(("Before the camera opens, tabs still show", pg.locator("#tabbar").is_visible()))
        pg.locator("[data-act=cam-open]").first.click(); pg.wait_for_timeout(1500)
        size = pg.evaluate("(() => { const r = document.querySelector('.cam').getBoundingClientRect(); return [r.width, r.height]; })()")
        ok.append(("Camera fills the screen", size == [390, 844]))
        ok.append(("Camera: no tab bar", not pg.locator("#tabbar").is_visible()))
        pg.screenshot(path=w.SHOTS / "top3-2-camera.png")
        pg.locator("[data-act=rec-start]").first.click(); pg.wait_for_timeout(2500)
        stop = pg.locator("[data-act=rec-stop]").first
        ok.append(("Stop button says Stop recording", stop.get_attribute("aria-label") == "Stop recording"))
        ok.append(("Timer has no typed dot", "●" not in pg.locator("#rec-timer").inner_text()))
        pg.screenshot(path=w.SHOTS / "top3-3-recording.png")
        stop.click()

        # 3. Post form
        pg.wait_for_selector("#post-form", timeout=8000); pg.wait_for_timeout(500)
        ok.append(("Review: tab bar back", pg.locator("#tabbar").is_visible()))
        ok.append(("Post on screen without scrolling", on_screen(pg, "#post-btn")))
        ok.append(("Post not hidden behind the tabs", pg.evaluate("document.querySelector('#post-btn').getBoundingClientRect().bottom <= document.querySelector('#tabbar').getBoundingClientRect().top")))
        ok.append(("No trick picked by default", pg.input_value("#post-trick") == ""))
        pg.screenshot(path=w.SHOTS / "top3-4-review.png")
        before = len(w.writes)
        pg.click("#post-btn"); pg.wait_for_timeout(800)
        ok.append(("Post without a trick does nothing", pg.locator("#post-form").count() == 1 and len(w.writes) == before))
        pg.select_option("#post-trick", index=1); pg.wait_for_timeout(200)
        ok.append(("Picking a trick shows its points", pg.locator("#post-pts").inner_text() != "0"))
        pg.click("#post-btn"); pg.wait_for_timeout(3000)
        ok.append(("Post with a trick goes through", pg.locator("#post-form").count() == 0))
        b.close()
    srv.shutdown()
    for name, good in ok:
        print("PASS" if good else "FAIL", name)
    print("page errors:", logs or "none")
    sys.exit(0 if all(g for _, g in ok) and not logs else 1)


if __name__ == "__main__":
    main()
