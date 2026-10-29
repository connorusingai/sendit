"""Game sounds: votes, the reward and the rank up make sound, and gear > Sounds > Off silences them.

Same fake database as ui_walk.py. The browser's audio is swapped for a counter, so the test hears nothing and
just counts the notes each moment starts.

Run:  .venv-test\Scripts\python.exe tests\sound_walk.py        (from dev\sendit)
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ui_walk as w  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

w.PORT = int(os.environ.get("PORT", 8127))
w.URL = f"http://127.0.0.1:{w.PORT}/app/"
COUNT = """(() => { window.__notes = 0;
  const AC = window.AudioContext; if (!AC) return;
  for (const k of ['createOscillator', 'createBufferSource']) {
    const f = AC.prototype[k];
    AC.prototype[k] = function () { const n = f.call(this); const s = n.start.bind(n); n.start = (...a) => { window.__notes++; return s(...a); }; return n; };
  }
})();"""


def main():
    ok = []
    srv = w.serve()
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", args=["--autoplay-policy=no-user-gesture-required"])
        ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        ctx.add_init_script(COUNT)
        ctx.add_init_script(f"localStorage.setItem('sb-{w.REF}-auth-token', {json.dumps(json.dumps(w.session))});"
                            f"localStorage.setItem('seen-status-{w.UID}', JSON.stringify({{c1: 'pending'}}));")
        ctx.route(f"https://{w.REF}.supabase.co/**", w.handle)
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: w.logs.append(f"PAGEERROR: {e}"))
        pg.goto(w.URL, wait_until="networkidle")
        pg.wait_for_timeout(2500)
        notes = lambda: pg.evaluate("window.__notes")
        ok.append(("no speaker buttons left", pg.locator("[data-act=mute], .pl-mute").count() == 0))
        n0 = notes()
        pg.click("[data-act=reward-collect]")
        pg.wait_for_timeout(2200)
        ok.append(("Collect + the gate beep make sound", notes() - n0 >= 5))   # 3 collect notes + the 2-note placeholder beep
        if pg.locator(".gate").count():
            pg.wait_for_timeout(600)
            pg.click(".ru-go")
            pg.wait_for_timeout(400)
        pg.click("#acct-chip")      # the gear: account settings
        pg.wait_for_timeout(1000)
        pg.wait_for_selector("#sound-pref", timeout=6000)
        ok.append(("Sounds switch under the gear, On by default", pg.input_value("#sound-pref") == "on"))
        pg.select_option("#sound-pref", "off")
        pg.wait_for_timeout(500)
        ok.append(("Off is remembered", pg.evaluate("localStorage.getItem('sendit-sound')") == "off"))
        n1 = notes()
        pg.evaluate("document.dispatchEvent(new Event('pointerdown'))")
        pg.reload(wait_until="networkidle")
        pg.wait_for_timeout(2500)
        if pg.locator("[data-act=reward-collect]").count():
            pg.click("[data-act=reward-collect]")
            pg.wait_for_timeout(2200)
        ok.append(("Off = silent", pg.evaluate("window.__notes") == 0))
        b.close()
    srv.shutdown()
    for name, good in ok:
        print("PASS" if good else "FAIL", name)
    print(f"{sum(g for _, g in ok)}/{len(ok)} checks passed")
    print("page errors:", "; ".join(w.logs) or "none")
    sys.exit(0 if all(g for _, g in ok) and not w.logs else 1)


if __name__ == "__main__":
    main()
