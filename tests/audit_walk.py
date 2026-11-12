"""Audit 11/10: one check per app bug that was fixed. Same fake database as ui_walk.py (nothing reaches the real one).

Run:  .venv-test\\Scripts\\python.exe tests\\audit_walk.py        (from dev\\sendit)

Checks:
  1. Sign-up: "Walker_1" is taken when "walker_1" exists (the check ignores capitals), and nothing is sent.
     If the database refuses a username, the rider reads plain words.
  2. Delete account: videos, motion logs AND the pass photo are deleted, all before the account itself.
  3. Judging a clip other riders decided a moment ago says so (not "You can't do that here.").
  4. Your clip got verified but isn't in the newest clips any more: you still get the reward moment.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import bot_walk as bot  # noqa: E402
import ui_walk as w  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

seen = []          # (what, detail) in the order the app asked
mode = {"signup_db_error": False, "late_votes": False, "mine_off_feed": False}
FILES = {"clips": [{"name": "a.mp4"}, {"name": "a.motion.json"}], "passes": [{"name": "pass-1.jpg"}]}


def handle(route, req):
    path, m = req.url.split(".supabase.co", 1)[1], req.method
    # 1. sign-up
    if m == "GET" and path.startswith("/rest/v1/profiles") and "username=" in path:
        seen.append(("taken?", path))
        return route.fulfill(json=[{"id": "someone"}] if "walker" in path.lower() else [])
    if path.startswith("/auth/v1/signup"):
        seen.append(("signup", req.post_data or ""))
        if mode["signup_db_error"]:
            return route.fulfill(status=500, json={"code": 500, "error_code": "unexpected_failure", "msg": "Database error saving new user"})
        return route.fulfill(json={"user": w.user, "session": None})
    # 2. delete account: the file store
    if "/storage/v1/object/list/" in path:
        bucket = path.rsplit("/", 1)[1].split("?")[0]
        seen.append(("list", bucket))
        left = FILES.get(bucket, [])
        FILES[bucket] = []          # the next look finds the folder empty
        return route.fulfill(json=left)
    if m == "DELETE" and "/storage/v1/object/" in path:
        bucket = path.rsplit("/", 1)[1].split("?")[0]
        names = json.loads(req.post_data or "{}").get("prefixes", [])
        seen.append(("remove", bucket, names))
        return route.fulfill(json=[{"name": n} for n in names])
    if "/rpc/delete_my_account" in path:
        seen.append(("delete_my_account",))
        return route.fulfill(json=None)
    # 3. a vote that arrives after the clip was decided
    if m == "POST" and path.startswith("/rest/v1/votes") and mode["late_votes"]:
        seen.append(("vote", req.post_data or ""))
        return route.fulfill(status=403, json={"code": "42501", "details": None, "hint": None,
                                               "message": 'new row violates row-level security policy for table "votes"'})
    # 4. my verified clip is NOT in everyone's newest clips, only in "my clips"
    if m == "GET" and path.startswith("/rest/v1/clips"):
        if mode["mine_off_feed"]:
            if f"user_id=eq.{w.UID}" in path:
                return route.fulfill(json=[] if "rider_ok=eq.false" in path else [w.CLIP])
            return route.fulfill(json=[c for c in bot.CLIPS if c["user_id"] != w.UID])
        return route.fulfill(json=bot.CLIPS)
    return w.handle(route, req)


def toast(pg, wait=500):
    pg.wait_for_timeout(wait)
    return pg.evaluate("() => [...document.querySelectorAll('.toast')].map(t => t.textContent).join(' | ')")


def page(b, signed_in, init=""):
    ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    if signed_in:
        ctx.add_init_script(f"localStorage.setItem('sb-{w.REF}-auth-token', {json.dumps(json.dumps(w.session))});" + init)
    ctx.add_init_script("window.confirm = () => true;")
    ctx.route(f"https://{w.REF}.supabase.co/**", handle)
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: w.logs.append(f"PAGEERROR: {e}"))
    pg.goto(w.URL, wait_until="networkidle")
    return ctx, pg


def main():
    ok = []
    w.SHOTS.mkdir(exist_ok=True)
    srv = w.serve()
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")

        # ---- 1. sign-up ----
        ctx, pg = page(b, signed_in=False)
        pg.wait_for_selector("[data-act=join][data-mode=signup]", state="attached")
        pg.locator("[data-act=join][data-mode=signup]").first.click()
        pg.wait_for_selector("#auth-user")

        def fill(name):
            pg.fill("#auth-user", name)
            pg.fill("#auth-email", "new@example.com")
            pg.fill("#auth-pass", "longenough1")
            pg.locator("[data-act=signup-mt]").first.click()
            pg.check("#auth-agree")
            pg.click("#auth-form button[type=submit]")
            return toast(pg, 900)

        t = fill("Walker_1")
        asked = [s[1] for s in seen if s[0] == "taken?"]
        ok.append(("sign-up: Walker_1 is taken when walker_1 exists", "username is taken" in t))
        ok.append(("...the check ignores capitals and treats _ as a plain character",
                   bool(asked) and "username=ilike.Walker%5C_1" in asked[-1]))
        ok.append(("...and no account was requested", not any(s[0] == "signup" for s in seen)))
        mode["signup_db_error"] = True
        t = fill("fresh_name")
        ok.append(("sign-up: a database refusal reads plainly", "taken or not allowed" in t and any(s[0] == "signup" for s in seen)))
        pg.screenshot(path=w.SHOTS / "audit-1-signup.png")
        ctx.close()

        # ---- 2. delete account ----
        seen.clear()
        ctx, pg = page(b, signed_in=True)
        pg.wait_for_selector("#acct-chip:not([hidden])")
        pg.click("#acct-chip")
        pg.wait_for_selector("[data-act=delete-account]", state="attached")
        pg.locator("[data-act=delete-account]").first.scroll_into_view_if_needed()
        pg.locator("[data-act=delete-account]").first.click()
        pg.wait_for_selector("[data-act=delete-account-yes]")
        pg.click("[data-act=delete-account-yes]")
        pg.wait_for_timeout(2500)
        removed = {s[1]: s[2] for s in seen if s[0] == "remove"}
        order = [s[0] for s in seen if s[0] in ("remove", "delete_my_account")]
        ok.append(("delete account: videos + motion logs deleted",
                   sorted(removed.get("clips", [])) == [f"{w.UID}/a.motion.json", f"{w.UID}/a.mp4"]))
        ok.append(("...the pass photo too", removed.get("passes") == [f"{w.UID}/pass-1.jpg"]))
        ok.append(("...files first, then the account, once", order == ["remove", "remove", "delete_my_account"]))
        ctx.close()

        # ---- 3. a late vote ----
        seen.clear()
        mode["late_votes"] = True
        ctx, pg = page(b, signed_in=True)
        pg.wait_for_selector(".calls")
        pg.click(".calls")
        pg.wait_for_timeout(1200)
        card = pg.locator(".judge-reel .reel-item, .judge-reel [id^=reel-]").first
        card.locator("[data-act=vote][data-y='1']").click()
        t = toast(pg, 3600)          # the vote is sent after the 3 s Undo window
        ok.append(("late vote: the vote was sent", any(s[0] == "vote" for s in seen)))
        ok.append(("...and the rider reads 'already called', not 'can't do that'",
                   "already called that one" in t and "can't do that" not in t))
        pg.screenshot(path=w.SHOTS / "audit-3-late-vote.png")
        ctx.close()
        mode["late_votes"] = False

        # ---- 4. reward for a clip that left the newest clips ----
        mode["mine_off_feed"] = True
        ctx, pg = page(b, signed_in=True, init=f"localStorage.setItem('seen-status-{w.UID}', JSON.stringify({{c1: 'pending'}}));")
        try:
            pg.wait_for_selector("#reward", timeout=8000)
            shown = True
        except Exception:
            shown = False
        ok.append(("reward moment shows for a verified clip that's no longer in the newest clips", shown))
        pg.screenshot(path=w.SHOTS / "audit-4-reward.png")
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
