"""Rank up moment (Brawl Stars / Apex style): a verified clip pushes you from Bronze into Silver.

Same fake database as ui_walk.py (nothing reaches the real one).

Run:  .venv-test\\Scripts\\python.exe tests\\rankup_walk.py [video_dir]      (from dev\\sendit)

Checks:
  1. Collect on the STOMPED reward opens the rank up, with the old badge, banner NEW TIER and the new rank name.
  2. Mid-way (after the hit) the new badge is showing; frames saved in tests/shots/rankup-*.png.
  3. First tap skips to the end, the Let's go button closes it.
With a video_dir, also records the whole thing as a .webm there.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ui_walk as w  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

w.PORT = int(os.environ.get("PORT", 8125))
w.URL = f"http://127.0.0.1:{w.PORT}/app/"
w.ME["points"] = int(os.environ.get("POINTS", 105))   # 105 = just crossed into blue (100)
w.CLIP["points_awarded"] = w.ME["points"]
VIDEO = sys.argv[1] if len(sys.argv) > 1 else None


def main():
    ok = []
    w.SHOTS.mkdir(exist_ok=True)
    srv = w.serve()
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        extra = {"record_video_dir": VIDEO, "record_video_size": {"width": 390, "height": 844}} if VIDEO else {}
        ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, **extra)
        ctx.add_init_script(f"localStorage.setItem('sb-{w.REF}-auth-token', {json.dumps(json.dumps(w.session))});"
                            f"localStorage.setItem('seen-status-{w.UID}', JSON.stringify({{c1: 'pending'}}));"
                            "localStorage.setItem('install-later', String(Date.now() + 864e5));")
        ctx.route(f"https://{w.REF}.supabase.co/**", w.handle)
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: w.logs.append(f"PAGEERROR: {e}"))
        pg.goto(w.URL, wait_until="networkidle")
        pg.wait_for_selector("[data-act=reward-collect]", timeout=8000)
        pg.wait_for_timeout(1500)
        pg.click("[data-act=reward-collect]")
        pg.wait_for_selector(".gate", timeout=3000)
        txt = lambda s: pg.locator(s).inner_text() if pg.locator(s).count() else ""
        # The gate (DESIGN.md 10/28): the old pass taps the reader, the light goes green, the SAME pass scans into the next tier
        ok.append(("rank up opens on the old green pass", "green" in pg.locator(".gate .g-old").inner_html()))
        ok.append(("...with the next tier underneath it", "blue" in pg.locator(".gate .g-new").inner_html()))
        ok.append(("says tap in.", txt("#g-word") == "tap in."))
        at = 0
        for ms, name in [(300, "1-ready"), (700, "2-tap"), (1000, "3-beep"), (1600, "4-scan"), (2600, "5-done")]:
            pg.wait_for_timeout(ms - at)
            at = ms
            pg.screenshot(path=w.SHOTS / f"rankup-{name}.png")
            if name == "3-beep":
                ok.append(("gate light turns green on the tap", pg.locator(".gate.lit").count() == 1))
        ok.append(("ends on blue.", txt("#g-word") == "blue."))
        ok.append(("says how far to black", "to black" in txt("#g-sub")))
        pg.mouse.click(195, 120)                     # tap the background once it's done: closes
        pg.wait_for_timeout(500)
        ok.append(("a tap when it's done closes it", pg.locator(".gate").count() == 0))

        ctx.close()
        if VIDEO:
            print("video:", pg.video.path())
        b.close()
    srv.shutdown()
    for name, good in ok:
        print("PASS" if good else "FAIL", name)
    print(f"{sum(g for _, g in ok)}/{len(ok)} checks passed")
    print("page errors:", "; ".join(w.logs) or "none")
    sys.exit(0 if all(g for _, g in ok) and not w.logs else 1)


if __name__ == "__main__":
    main()
