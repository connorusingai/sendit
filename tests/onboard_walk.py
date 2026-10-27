"""A brand-new rider's first minute: 2-tap setup, Start here on Base, the Record hint, Record in the middle of the tabs.

Same fake database as ui_walk.py (nothing reaches the real one).

Run:  .venv-test\\Scripts\\python.exe tests\\onboard_walk.py        (from dev\\sendit)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ui_walk as w  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

NEW = {**w.ME, "username": "newbie", "points": 0, "home_resort": None}


def handle(route, req):
    single = "vnd.pgrst.object" in req.headers.get("accept", "")
    path = req.url.split(".supabase.co", 1)[1]
    if req.method == "GET" and path.startswith("/rest/v1/profiles"):
        return route.fulfill(json=NEW if single else [])
    if req.method == "GET" and path.startswith("/rest/v1/clips"):
        return route.fulfill(json=[])
    return w.handle(route, req)


def main():
    srv, logs, ok = w.serve(), [], []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        ctx.add_init_script(f"localStorage.setItem('sb-{w.REF}-auth-token', {json.dumps(json.dumps(w.session))});")
        ctx.route(f"https://{w.REF}.supabase.co/**", handle)
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: logs.append(f"PAGEERROR: {e}"))
        pg.goto(w.URL, wait_until="networkidle"); pg.wait_for_timeout(2500)

        ok.append(("setup shows for a new rider", pg.locator(".onboard").count() == 1))
        pg.screenshot(path=w.SHOTS / "onboard-1-sport.png")
        pg.click("[data-act=ob-sport][data-k=ski]"); pg.wait_for_timeout(300)
        ok.append(("step 2: home mountain", pg.locator("[data-act=ob-resort]").count() > 3))
        pg.screenshot(path=w.SHOTS / "onboard-2-resort.png")
        pg.click("[data-act=ob-resort][data-k=Eldora]"); pg.wait_for_timeout(1500)
        ok.append(("home mountain saved", any("PATCH /rest/v1/profiles" in x and "Eldora" in x for x in w.writes)))
        ok.append(("setup closed, on Base", pg.locator(".onboard").count() == 0 and pg.locator(".lodge.base2").count() == 1))
        ok.append(("Start here list on Base", pg.locator(".lodge .start").count() == 1))
        ok.append(("Record hint showing", pg.locator("#rec-hint").count() == 1))
        pg.screenshot(path=w.SHOTS / "onboard-3-base.png")

        tabs = pg.locator("#tabs > button")
        ok.append(("5 tabs, Record in the middle", tabs.count() == 5 and "rec-tab" in (tabs.nth(2).get_attribute("class") or "")))
        pg.mouse.click(30, 300); pg.wait_for_timeout(300)
        ok.append(("hint gone after a tap", pg.locator("#rec-hint").count() == 0))
        pg.click("#tabs [data-act=me]"); pg.wait_for_timeout(1200)
        ok.append(("Profile tab opens your profile", pg.locator(".prof-head").count() == 1))
        pg.screenshot(path=w.SHOTS / "onboard-4-profile.png")

        pg.reload(wait_until="networkidle"); pg.wait_for_timeout(2500)
        ok.append(("setup + hint don't come back", pg.locator(".onboard").count() == 0 and pg.locator("#rec-hint").count() == 0))
        b.close()
    srv.shutdown()
    for name, good in ok:
        print("PASS" if good else "FAIL", name)
    print("page errors:", logs or "none")
    sys.exit(0 if all(g for _, g in ok) and not logs else 1)


if __name__ == "__main__":
    main()
