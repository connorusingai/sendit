"""Trick AI in the background: the phone finds the body in a real clip, calls the trick and quietly saves one guess.
Riders and judges never see it (Connor 10/28); it only feeds rider #001's AI scorecard.

Same fake database as ui_walk.py. The pose model really runs (MediaPipe from the CDN), on a clip of Connor's
own ground 360 that stays on his laptop (sendit-ai/data/clips/my_360.mp4, never committed). Without that file
the pose part is skipped.

Run:  ..\\sendit\\.venv-test\\Scripts\\python.exe tests\\ai_walk.py
"""
import base64
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ui_walk as w  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

w.PORT = int(os.environ.get("PORT", 8131))
w.URL = f"http://127.0.0.1:{w.PORT}/app/"
OWN_360 = Path(__file__).resolve().parents[2] / "sendit-ai" / "data" / "clips" / "my_360.mp4"
OTHER = "22222222-2222-4222-8222-222222222222"
JUDGE_ME = dict(w.CLIP, id="c9", user_id=OTHER, status="pending", trick_id="360", filmed_by=None,
                profiles={"username": "rider2", "points": 0})
reads = []


def handle(route, req):
    path = req.url.split(".supabase.co", 1)[1]
    if req.method == "GET":
        reads.append(path)
    if req.method == "GET" and path.startswith("/rest/v1/clips?select"):
        return route.fulfill(json=[w.CLIP, JUDGE_ME])
    return w.handle(route, req)


def main():
    ok = []
    srv = w.serve()
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        ctx.add_init_script(f"localStorage.setItem('sb-{w.REF}-auth-token', {json.dumps(json.dumps(w.session))});"
                            f"localStorage.setItem('seen-status-{w.UID}', JSON.stringify({{c1: 'pending'}}));")
        ctx.route(f"https://{w.REF}.supabase.co/**", handle)
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: w.logs.append(f"PAGEERROR: {e}"))
        pg.on("console", lambda m: print("   console:", m.text) if "trick AI" in m.text else None)
        pg.goto(w.URL, wait_until="networkidle")
        pg.wait_for_timeout(2500)

        for sel in ("[data-act=reward-collect]", ".ru-go"):     # the welcome-back reward + rank up come first
            if pg.locator(sel).count():
                pg.click(sel); pg.wait_for_timeout(2200)
        pg.click("#tabs [data-tab=feed]"); pg.wait_for_timeout(500)
        if pg.locator("[data-act=feed-mode][data-k=judge]").count():
            pg.click("[data-act=feed-mode][data-k=judge]"); pg.wait_for_timeout(800)
        ok.append(("judging works as before", pg.locator(".reel-item.judging").count() >= 1))
        ok.append(("the AI stays in the background: no AI hint for judges", pg.locator(".reel-item.judging", has_text="% sure").count() == 0
                   and "clip_ai" not in " ".join(reads)))
        pg.screenshot(path=str(w.SHOTS / "ai-judge.png"))
        rails = pg.evaluate("__ai.TrickAI.judge([[]], 'Rails')")
        ok.append(("rails are left to the judges", rails is None))

        if OWN_360.exists():
            data = base64.b64encode(OWN_360.read_bytes()).decode()
            r = pg.evaluate("""async d => {
              const blob = await (await fetch('data:video/mp4;base64,' + d)).blob(), t0 = performance.now();
              const {poseFromVideo, TrickAI, runTrickAI} = __ai; const world = await poseFromVideo(blob);
              const g = TrickAI.judge(world, 'Park');
              await runTrickAI('c1', blob, {category: 'Park'});
              return {g, frames: world.length, found: world.filter(Boolean).length, secs: (performance.now() - t0) / 1000};
            }""", data)
            g = r["g"]
            print(f"   own 360: {r['found']}/{r['frames']} frames found, guess {g}, {r['secs']:.0f}s for pose + save")
            ok.append(("real clip: the phone finds the body", r["found"] >= r["frames"] * 0.6))
            ok.append(("real clip: calls Connor's ground 360 a 360", g["spin"] == 360))
            ok.append(("real clip: landed", g["landed"] is True))
            ok.append(("the guess is saved to clip_ai once", sum("clip_ai" in x for x in w.writes) == 1))
        else:
            print("   (my_360.mp4 not on this computer: pose test skipped)")
        pg.screenshot(path=str(w.SHOTS / "ai-1.png"))
        b.close()
    srv.shutdown()
    errs = [x for x in w.logs if "PAGEERROR" in x]
    for name, good in ok:
        print(("PASS " if good else "FAIL ") + name)
    print("page errors:", errs or "none")
    sys.exit(0 if all(g for _, g in ok) and not errs else 1)


if __name__ == "__main__":
    main()
