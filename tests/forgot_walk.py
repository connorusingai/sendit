"""Forgot password: ask for a reset email, then pick a new password from the email's link.

Same fake database as ui_walk.py (nothing reaches the real one).

Run:  .venv-test\\Scripts\\python.exe tests\\forgot_walk.py        (from dev\\sendit)

Checks:
  1. Signed out, Forgot password with no email: asks for the email first, sends nothing.
  2. With an email: sends ONE reset request that links back to this page, shows the same message for everyone.
  3. Opening the email's link (type=recovery): the New password box shows instead of the rank splash.
  4. Saving it sends the new password and closes the box.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ui_walk as w  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

w.PORT = int(os.environ.get("PORT", 8124))
w.URL = f"http://127.0.0.1:{w.PORT}/app/"
sent = []


def handle(route, req):
    path = req.url.split(".supabase.co", 1)[1]
    if path.startswith("/auth/v1/recover"):
        sent.append(("recover", req.url, json.loads(req.post_data or "{}")))
        return route.fulfill(json={})
    if path.startswith("/auth/v1/user") and req.method == "PUT":
        sent.append(("update", req.url, json.loads(req.post_data or "{}")))
        return route.fulfill(json=w.user)
    return w.handle(route, req)


def toast(pg):
    pg.wait_for_timeout(500)
    return pg.evaluate("() => [...document.querySelectorAll('.toast')].map(t => t.textContent).join(' | ')")


def main():
    ok = []
    srv = w.serve()
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        # 1 + 2: signed out
        ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        ctx.route(f"https://{w.REF}.supabase.co/**", handle)
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: w.logs.append(f"PAGEERROR: {e}"))
        pg.goto(w.URL, wait_until="networkidle")
        pg.wait_for_selector("[data-act=forgot]", state="attached")
        pg.locator("[data-act=forgot]").scroll_into_view_if_needed()
        pg.click("[data-act=forgot]")
        t = toast(pg)
        ok.append(("no email -> asks for it, sends nothing", "Type your email" in t and not sent))
        pg.fill("#auth-email", "rider@example.com")
        pg.click("[data-act=forgot]")
        t = toast(pg)
        rec = [s for s in sent if s[0] == "recover"]
        ok.append(("one reset request for that email", len(rec) == 1 and rec[0][2].get("email") == "rider@example.com"))
        ok.append(("link comes back to this page", bool(rec) and "redirect_to=http%3A%2F%2F127.0.0.1" in rec[0][1]))
        ok.append(("same message for everyone", "If that email has an account" in t))
        pg.screenshot(path=w.SHOTS / "forgot-1-signin.png")
        ctx.close()

        # 3 + 4: the email's link
        ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        ctx.route(f"https://{w.REF}.supabase.co/**", handle)
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: w.logs.append(f"PAGEERROR: {e}"))
        pg.goto(w.URL + f"#access_token={w.jwt}&expires_at={w.exp}&expires_in=3600&refresh_token=fake"
                        f"&token_type=bearer&type=recovery", wait_until="networkidle")
        try:
            pg.wait_for_selector("#newpass-form", timeout=8000)
            shown = True
        except Exception:
            shown = False
        ok.append(("new password box shows", shown))
        ok.append(("no rank splash on top", pg.locator("#splash").count() == 0))
        pg.screenshot(path=w.SHOTS / "forgot-2-newpass.png")
        if shown:
            pg.fill("#newpass", "brandnewpass1")
            pg.click("#newpass-form button[type=submit]")
            t = toast(pg)
            upd = [s for s in sent if s[0] == "update"]
            ok.append(("new password sent", len(upd) == 1 and upd[0][2].get("password") == "brandnewpass1"))
            ok.append(("box closes + says saved", pg.locator("#newpass-form").count() == 0 and "Password saved" in t))
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
