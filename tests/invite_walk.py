"""Crew invite links (028) and the founder's "Needs a call" queue (027).

Same fake database as ui_walk.py (nothing reaches the real one).

Run:  .venv-test\\Scripts\\python.exe tests\\invite_walk.py        (from dev\\sendit)

Checks:
  1. Signed out, ?crew=abc234 says "You're invited to <crew>", cleans the address bar, and sign-up sends crew ABC234.
  2. In Instagram's browser the code stays in the address bar, so "Open in Safari" keeps it.
  3. Signed in with no crew: the link joins right away (join_crew_link, no switch) and opens Squad > Crew.
  4. Signed in and already in another crew: it asks, and Yes switches (p_switch true).
  5. A founder sees "Needs a call" on Me with the 24h clips marked, and the button opens the judge stack.
  6. A normal rider sees no queue.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ui_walk as w  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

w.PORT = int(os.environ.get("PORT", 8147))
w.URL = f"http://127.0.0.1:{w.PORT}/app/"
CREW = {"name": "Boulder Park Rats", "tag": "BPR", "members": 4}
OLD_CREW = {"id": "oc1", "name": "Old Crew", "tag": "OLD", "code": "OLDOLD", "owner": "x", "created_at": "2026-10-01T00:00:00Z"}
QUEUE = [
    {"clip_id": "q1", "rider": "shredder", "trick": "360", "grab": "Mute", "created_at": "2026-10-20T12:00:00Z", "votes": 1, "settles": True},
    {"clip_id": "q2", "rider": "newkid", "trick": "180", "grab": "No grab", "created_at": "2099-01-01T00:00:00Z", "votes": 0, "settles": False},
]
state = {"founder": False, "my_crew": []}
signups, rpcs = [], []


def handle(route, req):
    path = req.url.split(".supabase.co", 1)[1]
    if path.startswith("/auth/v1/signup"):
        signups.append(json.loads(req.post_data or "{}"))
        return route.fulfill(json={"user": None, "session": None})
    if "/rpc/" in path:
        name = path.split("/rpc/", 1)[1].split("?")[0]
        rpcs.append((name, json.loads(req.post_data or "{}")))
        if name == "crew_invite_info":
            return route.fulfill(json=[CREW])
        if name == "my_crew":
            return route.fulfill(json=state["my_crew"])
        if name == "join_crew_link":
            return route.fulfill(json="new-crew-id")
        if name == "founder_queue":
            return route.fulfill(json=QUEUE if state["founder"] else [])
    if path.startswith("/rest/v1/profiles") and "vnd.pgrst.object" in req.headers.get("accept", ""):
        return route.fulfill(json={**w.ME, "is_founder": state["founder"]})
    return w.handle(route, req)


def signed_in(b, ua=None):
    ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, user_agent=ua)
    ctx.add_init_script(f"localStorage.setItem('sb-{w.REF}-auth-token', {json.dumps(json.dumps(w.session))});"
                        f"localStorage.setItem('seen-status-{w.UID}', JSON.stringify({{c1: 'verified'}}));")
    ctx.route(f"https://{w.REF}.supabase.co/**", handle)
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: w.logs.append(f"PAGEERROR: {e}"))
    return ctx, pg


def main():
    ok = []
    srv = w.serve()
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")

        # 1. signed out
        ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        ctx.route(f"https://{w.REF}.supabase.co/**", handle)
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: w.logs.append(f"PAGEERROR: {e}"))
        pg.goto(w.URL + "?crew=abc234&src=ig", wait_until="networkidle")
        pg.wait_for_timeout(800)
        ok.append(("sign-in screen names the crew", "invited to Boulder Park Rats" in pg.locator(".sent-you").first.inner_text()))
        ok.append(("crew code cleaned out of the address", "crew=" not in pg.url))
        pg.click("[data-act=join][data-mode=signup]") if pg.locator("[data-act=join][data-mode=signup]").count() else pg.click("[data-act=authmode]")
        pg.wait_for_selector("#auth-user")
        pg.fill("#auth-user", "crewkid")
        pg.fill("#auth-email", "crewkid@example.com")
        pg.fill("#auth-pass", "longenough1")
        pg.click(".mt-pick [data-k=Eldora]"); pg.check("#auth-agree")
        pg.click("#auth-form button[type=submit]")
        pg.wait_for_timeout(1200)
        data = signups[0].get("data", {}) if signups else {}
        ok.append(("sign-up carries crew ABC234 (database backstop)", data.get("crew") == "ABC234" and data.get("src") == "ig"))
        pg.screenshot(path=w.SHOTS / "invite-signedout.png")
        ctx.close()

        # 2. Instagram's browser keeps the code in the address bar
        ig = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 350.0.0"
        ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, user_agent=ig)
        ctx.route(f"https://{w.REF}.supabase.co/**", handle)
        pg = ctx.new_page()
        pg.goto(w.URL + "?crew=ABC234", wait_until="networkidle")
        ok.append(("Instagram: code stays for Open in Safari", "crew=ABC234" in pg.url))
        ctx.close()

        # 3. signed in, no crew: joins right away
        rpcs.clear()
        ctx, pg = signed_in(b)
        pg.goto(w.URL + "?crew=ABC234", wait_until="networkidle")
        pg.wait_for_timeout(2500)
        joins = [a for n, a in rpcs if n == "join_crew_link"]
        ok.append(("signed in: joins via the link, no switch", joins == [{"p_code": "ABC234", "p_switch": False}]))
        ok.append(("...and lands on Squad > Crew", pg.locator(".squad-seg [data-k=crew].on").count() == 1))
        pg.screenshot(path=w.SHOTS / "invite-joined.png")
        ctx.close()

        # 4. already in another crew: asks, Yes switches
        rpcs.clear()
        state["my_crew"] = [OLD_CREW]
        asked = []
        ctx, pg = signed_in(b)
        pg.on("dialog", lambda d: (asked.append(d.message), d.accept()))
        pg.goto(w.URL + "?crew=ABC234", wait_until="networkidle")
        pg.wait_for_timeout(2500)
        joins = [a for n, a in rpcs if n == "join_crew_link"]
        ok.append(("in another crew: asks first", bool(asked) and "Old Crew" in asked[0] and "Boulder Park Rats" in asked[0]))
        ok.append(("...Yes switches", joins == [{"p_code": "ABC234", "p_switch": True}]))
        ctx.close()
        state["my_crew"] = []

        # 5. founder queue
        state["founder"] = True
        ctx, pg = signed_in(b)
        pg.goto(w.URL, wait_until="networkidle")
        pg.wait_for_timeout(1500)
        pg.mouse.click(195, 420)
        pg.wait_for_timeout(600)
        pg.click("#tabs [data-act=me]")
        pg.wait_for_timeout(1200)
        card = pg.locator(".fdash", has_text="Needs a call")
        ok.append(("founder sees Needs a call (2)", card.count() == 1 and "Needs a call (2)" in card.inner_text()))
        ok.append(("...24h clip marked 'your call settles it'", card.count() == 1 and card.inner_text().count("your call settles it") == 1))
        pg.screenshot(path=w.SHOTS / "invite-founder-queue.png", full_page=True)
        if card.count():
            card.locator("[data-act=fq-judge]").click()
            pg.wait_for_timeout(900)
        ok.append(("...Judge oldest first opens the judge stack", pg.locator(".judge-reel").count() == 1))
        ctx.close()

        # 6. normal rider: no queue
        state["founder"] = False
        ctx, pg = signed_in(b)
        pg.goto(w.URL, wait_until="networkidle")
        pg.wait_for_timeout(1500)
        pg.mouse.click(195, 420)
        pg.wait_for_timeout(600)
        pg.click("#tabs [data-act=me]")
        pg.wait_for_timeout(1200)
        ok.append(("normal rider: no queue", pg.locator(".fdash", has_text="Needs a call").count() == 0 and pg.locator(".me .pass").count() >= 1))
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
