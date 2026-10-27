"""The "Put Stomped on your home screen" card on 3 kinds of phone: iPhone Safari, Android Chrome, and
Instagram's built-in browser (which can't install, so it says to open Safari). Plus: Later hides it, and an
already-installed app never shows it.

Same fake database as ui_walk.py (nothing reaches the real one).

Run:  .venv-test\\Scripts\\python.exe tests\\install_walk.py        (from dev\\sendit)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ui_walk as w  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
ANDROID = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Mobile Safari/537.36"
INSTA = IPHONE.replace(" Safari/604.1", " Instagram 350.0.0.0 (iPhone15,2; iOS 18_0)")
SHEET = "#install-sheet"


def open_app(b, ua, signed_in=True, extra=""):
    ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, user_agent=ua)
    if signed_in:
        ctx.add_init_script(f"localStorage.setItem('sb-{w.REF}-auth-token', {json.dumps(json.dumps(w.session))});")
    if extra:
        ctx.add_init_script(extra)
    ctx.route(f"https://{w.REF}.supabase.co/**", w.handle)
    pg = ctx.new_page()
    pg.goto(w.URL, wait_until="networkidle")
    pg.wait_for_timeout(8000)   # the card waits 6 s after sign-in
    return ctx, pg


def main():
    srv, ok = w.serve(), []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")

        ctx, pg = open_app(b, IPHONE)
        ok.append(("iPhone: card shows", pg.locator(SHEET).count() == 1))
        ok.append(("iPhone: says Share, then Add to Home Screen", "Add to Home Screen" in pg.locator(SHEET).inner_text()))
        pg.screenshot(path=w.SHOTS / "install-1-iphone.png")
        pg.click("[data-act=install-later]"); pg.wait_for_timeout(600)
        ok.append(("Later hides it", pg.locator(SHEET).count() == 0))
        pg.reload(wait_until="networkidle"); pg.wait_for_timeout(8000)
        ok.append(("Later: doesn't come back right away", pg.locator(SHEET).count() == 0))
        ctx.close()

        ctx, pg = open_app(b, ANDROID)
        ok.append(("Android: card shows with steps", "Add to Home screen" in pg.locator(SHEET).inner_text()))
        pg.screenshot(path=w.SHOTS / "install-2-android.png")
        ctx.close()

        ctx, pg = open_app(b, INSTA)
        ok.append(("Instagram: says open in Safari", "Open in Safari" in pg.locator(SHEET).inner_text()))
        pg.screenshot(path=w.SHOTS / "install-3-instagram.png")
        ctx.close()

        ctx, pg = open_app(b, INSTA, signed_in=False)
        ok.append(("Instagram, signed out: landing warns first", pg.locator(".inapp-note").count() == 1))
        pg.screenshot(path=w.SHOTS / "install-4-instagram-landing.png")
        ctx.close()

        ctx, pg = open_app(b, IPHONE, extra="Object.defineProperty(navigator, 'standalone', {get: () => true});")
        ok.append(("already on the home screen: no card", pg.locator(SHEET).count() == 0))
        ctx.close()
        b.close()
    srv.shutdown()
    for name, good in ok:
        print("PASS" if good else "FAIL", name)
    sys.exit(0 if all(g for _, g in ok) else 1)


if __name__ == "__main__":
    main()
