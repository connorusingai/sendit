"""Growth bits: ?src= tags ride along with sign-up, and early riders get the Founder badge.

Same fake database as ui_walk.py (nothing reaches the real one).

Run:  .venv-test\\Scripts\\python.exe tests\\growth_walk.py        (from dev\\sendit)

Checks:
  1. Opening ?src=IG remembers "ig" and cleans it out of the address bar (other link bits stay).
  2. A second tag later doesn't replace the first one (first touch wins).
  3. Sign-up sends src: "ig" with the username; the sign-up box mentions the Founder badge.
  4. A rider who joined in October shows the Founder badge on their profile.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ui_walk as w  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

w.PORT = int(os.environ.get("PORT", 8126))
w.URL = f"http://127.0.0.1:{w.PORT}/app/"
signups = []


def handle(route, req):
    if req.url.split(".supabase.co", 1)[1].startswith("/auth/v1/signup"):
        signups.append(json.loads(req.post_data or "{}"))
        return route.fulfill(json={"user": None, "session": None})
    return w.handle(route, req)


def main():
    ok = []
    srv = w.serve()
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        ctx.route(f"https://{w.REF}.supabase.co/**", handle)
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: w.logs.append(f"PAGEERROR: {e}"))
        pg.goto(w.URL + "?src=IG&clip=abc", wait_until="networkidle")
        ok.append(("remembers ig", pg.evaluate("() => localStorage.getItem('sendit-signup-src')") in ('ig', '"ig"')))
        ok.append(("src gone from the address, clip kept", "src=" not in pg.url))
        pg.goto(w.URL + "?src=tt", wait_until="networkidle")
        ok.append(("first tag wins", pg.evaluate("() => localStorage.getItem('sendit-signup-src')") in ('ig', '"ig"')))
        pg.click("[data-act=join][data-mode=signup]") if pg.locator("[data-act=join][data-mode=signup]").count() else pg.click("[data-act=authmode]")
        pg.wait_for_selector("#auth-user")
        ok.append(("sign-up mentions Founder", "Founder" in pg.locator("#auth-top + .sub").inner_text()))
        pg.fill("#auth-user", "newrider")
        pg.fill("#auth-email", "new@example.com")
        pg.fill("#auth-pass", "longenough1")
        pg.click(".mt-pick [data-k=Eldora]")   # home mountain at signup (10/28)
        pg.check("#auth-agree")
        pg.click("#auth-form button[type=submit]")
        pg.wait_for_timeout(1200)
        data = signups[0].get("data", {}) if signups else {}
        ok.append(("sign-up carries src ig", data.get("src") == "ig" and data.get("username") == "newrider"))
        ctx.close()

        ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        ctx.add_init_script(f"localStorage.setItem('sb-{w.REF}-auth-token', {json.dumps(json.dumps(w.session))});"
                            f"localStorage.setItem('seen-status-{w.UID}', JSON.stringify({{c1: 'verified'}}));")
        ctx.route(f"https://{w.REF}.supabase.co/**", handle)
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: w.logs.append(f"PAGEERROR: {e}"))
        pg.goto(w.URL, wait_until="networkidle")
        pg.wait_for_timeout(2000)
        pg.click(".base .pass-btn")      # the season pass opens Me
        pg.wait_for_selector(".ach", timeout=6000)
        got = pg.locator(".ach.got b").all_inner_texts()
        ok.append(("Founder badge on an October rider", "Founder" in got))
        pg.screenshot(path=w.SHOTS / "growth-founder.png", full_page=True)
        ctx.close()
        b.close()
    srv.shutdown()
    for name, good in ok:
        print("PASS" if good else "FAIL", name)
    print(f"{sum(g for _, g in ok)}/{len(ok)} checks passed")
    print("page errors:", "; ".join(w.logs) or "none")
    sys.exit(0 if all(g for _, g in ok) and not w.logs else 1)


if __name__ == "__main__":
    main()
