"""Story 1: a friend sends me a getstomped.app link. I see a real front page that explains Stomped in 5 seconds,
tap one button, and I'm signed up in under a minute (the ?src= tag is kept).

Run:  .venv-test\\Scripts\\python.exe tests\\story1_walk.py        (from the app folder)
"""
import json
import time

from playwright.sync_api import sync_playwright

import story_kit as k
from story_kit import w

signups = []
CLIP_ID = "0a1b2c3d-1111-2222-3333-444455556666"


def handle(route, req):
    path, m = k.path_of(req), req.method
    if m == "GET" and path.startswith("/rest/v1/profiles") and "username=" in path:
        return route.fulfill(json=[])                       # the username is free
    if path.startswith("/auth/v1/signup"):
        signups.append(req.post_data or "")
        return route.fulfill(json=w.session)                # sign-up is instant (no email check), like the live setting
    if m == "GET" and path.startswith("/rest/v1/profiles"):
        return route.fulfill(json={**k.NEW, "home_resort": None} if k.wants_one(req) else [])
    if m == "GET" and path.startswith("/rest/v1/clips"):
        return route.fulfill(json=[])
    return w.handle(route, req)


def main():
    W = k.Walk("Story 1: front page -> one button -> signed up, ?src= kept")
    srv = w.serve()
    with sync_playwright() as p:
        b = k.launch(p)

        # ---- the front page, with the code library blocked (it must not need one) ----
        ctx = k.phone(b, handle, signed_in=False)
        ctx.route("**/cdn.jsdelivr.net/**", lambda r: r.abort())
        pg = W.watch(ctx.new_page())
        t0 = time.time()
        pg.goto(k.root() + "?src=ig", wait_until="domcontentloaded")
        pg.wait_for_timeout(900)
        on_root = pg.evaluate("location.pathname") == "/"
        W.check("the link opens a front page (it stays at /, no jump into the app)", on_root)
        W.attempt("...that says what Stomped is: headline + one plain sentence on the first screen",
                  lambda: "land it" in pg.locator("h1").inner_text().lower()
                  and "landed or bailed" in pg.locator(".lede").inner_text().lower()
                  and pg.locator(".lede").bounding_box()["y"] < 844)
        W.attempt("...3 steps", lambda: pg.locator("ol.steps > li").count() == 3)
        W.attempt("...exactly one Make an account button, on screen without scrolling, glove size (56px+)",
                  lambda: pg.locator("a:has-text('Make an account'), button:has-text('Make an account')").count() == 1
                  and 0 < pg.locator("#join").bounding_box()["y"] < 844 and pg.locator("#join").bounding_box()["height"] >= 56)
        faq = " | ".join(k.texts(pg, ".faq summary")).lower()
        W.check("...FAQ: free? who sees my clips? how do points work?", all(x in faq for x in ("free", "who sees my clips", "points")), faq)
        W.attempt("...the answers open with a tap (no script needed)", lambda: (pg.locator(".faq summary").nth(2).click(), pg.wait_for_timeout(200),
                  "180 is 10" in pg.locator(".faq details").nth(2).inner_text())[-1])
        foot = (pg.locator("footer").inner_text() if pg.locator("footer").count() else "").lower()
        W.check("...footer: a contact line + 'Built by two college riders'", "two college riders" in foot and "@stomped.app" in foot, foot[:80])
        W.attempt("...the button keeps ?src=ig", lambda: "src=ig" in pg.locator("#join").get_attribute("href") and "join=1" in pg.locator("#join").get_attribute("href"))
        W.check("...and nothing sideways-scrolls on a phone", pg.evaluate("document.documentElement.scrollWidth") <= 390)
        pg.screenshot(path=w.SHOTS / "story1-1-front.png")
        pg.screenshot(path=w.SHOTS / "story1-1-front-full.png", full_page=True)

        # ---- one tap: the sign-up form, nothing else in the way ----
        ctx.unroute("**/cdn.jsdelivr.net/**")
        def tap_join():
            pg.locator("#join").click()
            pg.wait_for_selector("#auth-user", timeout=8000)
            box = pg.locator("#auth-user").bounding_box()
            return "/app/" in pg.url and box["y"] < 500 and pg.locator(".land-hero").count() == 0
        W.attempt("one tap -> the sign-up form is on screen (no second pitch, no second button to find)", tap_join)
        pg.screenshot(path=w.SHOTS / "story1-2-signup.png")

        def sign_up():
            pg.fill("#auth-user", "newbie")
            pg.fill("#auth-email", "newbie@example.com")
            pg.fill("#auth-pass", "longenough1")
            pg.locator("[data-act=signup-mt][data-k=Eldora]").click()
            pg.check("#auth-agree")
            pg.click("#auth-form button[type=submit]")
            pg.wait_for_selector(".onboard", timeout=10000)
            return True
        W.attempt("3 boxes, a mountain, a checkbox, Make my pass -> I'm in (setup starts)", sign_up)
        took = time.time() - t0
        W.check("...in under a minute", took < 60, f"{took:.0f}s")
        body = signups[-1] if signups else ""
        W.check("...and the sign-up carries where I came from (src = ig)", '"src":"ig"' in body.replace(" ", ""), body[:120])
        pg.screenshot(path=w.SHOTS / "story1-3-in.png")
        ctx.close()

        # ---- scripts off entirely: still a page, still a button ----
        ctx = k.phone(b, handle, signed_in=False, java_script_enabled=False)
        pg = ctx.new_page()
        pg.goto(k.root(), wait_until="domcontentloaded")
        W.attempt("with scripts switched off it's still the whole page, and the button still goes to sign-up",
                  lambda: "land it" in pg.locator("h1").inner_text().lower() and pg.locator("#join").get_attribute("href") == "app/?join=1"
                  and pg.locator("ol.steps > li").count() == 3)
        ctx.close()

        # ---- links that belong to the app still go straight there ----
        def lands(url, signed_in=False, key=None, want=None):
            c = k.phone(b, handle, signed_in=signed_in)
            g = W.watch(c.new_page())
            g.goto(k.root() + url, wait_until="domcontentloaded")
            g.wait_for_timeout(1200)
            in_app = g.evaluate("location.pathname").endswith("/app/")
            kept = True if key is None else g.evaluate("k => localStorage.getItem(k)", key) == want
            c.close()
            return in_app and kept
        W.attempt("a clip link at the root still opens the app with that clip waiting", lambda: lands(f"?clip={CLIP_ID}", key="sendit-pending-clip", want=CLIP_ID))
        W.attempt("...a crew invite too", lambda: lands("?crew=ABC123", key="sendit-pending-crew", want="ABC123"))
        W.attempt("...and a friend's invite", lambda: lands("?from=maya", key="sendit-pending-from", want="maya"))
        W.attempt("...and a password-reset link from an email", lambda: lands("#error=access_denied&error_code=otp_expired&error_description=expired"))
        W.attempt("a rider who's already signed in skips the front page", lambda: lands("", signed_in=True))

        # ---- search engines ----
        ctx = k.phone(b, handle, signed_in=False)
        r1, r2 = ctx.request.get(k.root() + "robots.txt"), ctx.request.get(k.root() + "sitemap.xml")
        W.check("robots.txt is there and points at the sitemap", r1.status == 200 and "sitemap.xml" in r1.text().lower())
        W.check("sitemap.xml is there and lists the front page", r2.status == 200 and "https://getstomped.app/</loc>" in r2.text())
        ctx.close()
        b.close()
    srv.shutdown()
    W.finish()


if __name__ == "__main__":
    main()
