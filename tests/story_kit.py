"""Shared bits for the user-story walks (story1_walk.py ... story5_walk.py).

Each walk plays one story from the big-run brief as a rider on a phone-size screen, with the database faked the same
way as ui_walk.py (nothing reaches the real one). A check that can't even run counts as a FAIL instead of stopping
the walk, so the same file can be pointed at old code to show which checks that code fails.

Story 6 (fake accounts) is a database story: it lives in supabase/tests/test_rules.py, "Story 6".
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import bot_walk as bot  # noqa: E402,F401  (walks use bot.CLIPS, bot.OTHER)
import ui_walk as w  # noqa: E402

UID = w.UID
NEW = {**w.ME, "username": "newbie", "points": 0, "home_resort": "Eldora", "created_at": "2026-11-11T12:00:00Z"}


class Walk:
    def __init__(self, title):
        self.title, self.ok, self.errors = title, [], []

    def check(self, label, good, extra=""):
        self.ok.append((label, bool(good), str(extra)))
        return bool(good)

    def attempt(self, label, fn):
        """fn() returns True/False; if it blows up (a button that isn't there on old code), that's a FAIL."""
        try:
            return self.check(label, fn())
        except Exception as e:  # noqa: BLE001
            return self.check(label, False, str(e).splitlines()[0][:110])

    def watch(self, pg):
        pg.on("pageerror", lambda e: self.errors.append(f"PAGEERROR: {e}"))
        return pg

    def finish(self):
        print(self.title)
        for label, good, extra in self.ok:
            print(("PASS " if good else "FAIL ") + label + (f"   [{extra}]" if extra and not good else ""))
        good = sum(g for _, g, _ in self.ok)
        print(f"{good}/{len(self.ok)} checks passed")
        print("page errors:", "; ".join(self.errors) or "none")
        sys.exit(0 if good == len(self.ok) and not self.errors else 1)


def root():
    """The front page (the folder above /app/). Call after w.serve()."""
    return w.URL.rsplit("/app/", 1)[0] + "/"


def launch(p, camera=False):
    args = ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"] if camera else []
    return p.chromium.launch(channel="chrome", args=args)


def phone(b, handle, signed_in=True, init="", camera=False, **kw):
    ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True,
                        permissions=["camera", "microphone"] if camera else [], **kw)
    if signed_in:
        ctx.add_init_script(f"localStorage.setItem('sb-{w.REF}-auth-token', {json.dumps(json.dumps(w.session))});")
    if init:
        ctx.add_init_script(init)
    ctx.route(f"https://{w.REF}.supabase.co/**", handle)
    return ctx


def path_of(req):
    return req.url.split(".supabase.co", 1)[1]


def wants_one(req):
    return "vnd.pgrst.object" in req.headers.get("accept", "")


def film(pg, seconds=2.5):
    """Open the camera (Chrome's fake one), record, stop. Ends on the review screen.
    Desktop Chrome sometimes records the first take after the camera opens as 0 bytes; the app then says
    "That take didn't save" and opens the camera again, so film again like a rider would (up to 3 takes)."""
    cam = pg.locator("[data-act=cam-open]")
    if cam.count():
        cam.first.click()
        pg.wait_for_timeout(1500)
    for _ in range(3):
        pg.locator("[data-act=rec-start]").first.click()
        pg.wait_for_timeout(int(seconds * 1000))
        pg.locator("[data-act=rec-stop]").first.click()
        pg.wait_for_timeout(1200)
        if not pg.locator("[data-act=rec-start]").count():
            return
        pg.wait_for_timeout(800)


def texts(pg, sel):
    return pg.evaluate("s => [...document.querySelectorAll(s)].map(e => e.innerText.replace(/\\s+/g, ' ').trim())", sel)
