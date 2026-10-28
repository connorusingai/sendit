"""Bots: a pretend rider uses the app end to end against a faked database (nothing reaches the real one).

The fake database has other riders' clips waiting to be judged and verified clips in the feed. The bot fires a clip,
comments, judges one clip landed and one bailed, records a clip with Chrome's fake camera and posts it, then opens
every screen. Each step checks that the app sent the matching write (they're only logged, never applied).

Run:  .venv-test\\Scripts\\python.exe tests\\bot_walk.py        (from dev\\sendit)
"""
import json
import time

from playwright.sync_api import sync_playwright

import ui_walk as u

OTHER = [("22222222-0000-0000-0000-00000000000%d" % i, n) for i, n in enumerate(["jess", "kai", "mo"], 1)]


def clip(i, uid, name, status, trick):
    return {"id": f"o{i}", "user_id": uid, "trick_id": trick, "combo": [], "status": status, "points_awarded": 50 if status == "verified" else 0,
            "created_at": f"2026-10-23T1{i}:00:00Z", "verified_at": "2026-10-23T15:00:00Z" if status == "verified" else None,
            "video_path": f"{uid}/o{i}.mp4", "resort": "Eldora", "grab": "No grab",
            "profiles": {"username": name, "points": 400}, "likes": [{"count": 2}], "comments": [{"count": 1}]}


CLIPS = [u.CLIP] + [clip(i, uid, n, "verified", t) for i, ((uid, n), t) in enumerate(zip(OTHER, ["360", "backflip", "cork720"]), 1)] \
        + [clip(i + 3, uid, n, "pending", t) for i, ((uid, n), t) in enumerate(zip(OTHER, ["540", "720", "misty540"]), 1)]


def handle(route, req):
    path = req.url.split(".supabase.co", 1)[1]
    if req.method == "GET" and path.startswith("/rest/v1/clips"):
        return route.fulfill(json=CLIPS)
    if req.method == "GET" and path.startswith("/rest/v1/comments"):
        return route.fulfill(json=[{"id": 1, "clip_id": "o1", "user_id": OTHER[0][0], "body": "sick", "created_at": "2026-10-23T15:00:00Z", "profiles": {"username": "jess"}}])
    return u.handle(route, req)


def step(name, fn, expect):
    before = len(u.writes)
    try:
        fn()
        new = u.writes[before:]
        ok = any(expect in w for w in new) if expect else True
        print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  (wanted a write containing {expect!r}, got {new or 'nothing'})"))
        return ok
    except Exception as e:  # noqa: BLE001  (a broken step is a FAIL, keep walking)
        print(f"FAIL {name}  ({str(e).splitlines()[0][:140]})")
        return False


def main():
    u.SHOTS.mkdir(exist_ok=True)
    srv = u.serve()
    results = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"])
        ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, permissions=["camera", "microphone"])
        ctx.add_init_script(f"localStorage.setItem('sb-{u.REF}-auth-token', {json.dumps(json.dumps(u.session))});")
        # Fake share sheet: remembers what Save handed it (the real one is the phone's)
        ctx.add_init_script("window.__shared = []; navigator.canShare = () => true;"
                            "navigator.share = async d => { window.__shared.push((d.files || []).map(f => f.name + '|' + f.type + '|' + f.size)); };")
        ctx.route(f"https://{u.REF}.supabase.co/**", handle)
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: u.logs.append(f"PAGEERROR: {e}"))
        pg.on("console", lambda m: u.logs.append(f"{m.type}: {m.text}") if m.type == "error" and "Failed to load resource" not in m.text else None)
        pg.goto(u.URL, wait_until="networkidle")
        pg.wait_for_timeout(2000)
        pg.mouse.click(195, 420)          # past the rank splash
        pg.wait_for_timeout(800)

        def tab(t):
            pg.click(f"#tabs [data-tab={t}]")
            pg.wait_for_timeout(1200)

        def fire():
            tab("feed")
            pg.locator("[data-act=like]").first.click()
            pg.wait_for_timeout(600)

        def comment():
            pg.locator("[data-act=comments]").first.click()
            pg.wait_for_timeout(800)
            f = pg.locator("form.comment-form input").first
            f.fill("bot says: clean")
            f.press("Enter")
            pg.wait_for_timeout(800)

        def judge_yes():
            tab("feed")
            pg.click("[data-act=feed-mode][data-k=judge]")  # Clips | Judge tabs on the feed (10/27)
            pg.wait_for_timeout(500)
            card = pg.locator(".reel-item.judging").first
            card.scroll_into_view_if_needed()
            pg.wait_for_timeout(600)
            pg.screenshot(path=u.SHOTS / "bot-judge-card.png")
            cid = card.get_attribute("data-id")
            card.locator("[data-act=vote][data-y='1']").click()
            pg.wait_for_timeout(3400)   # stamp, the stack moves on, then the vote saves (3s Undo window)
            print("stamp stays on the judged card:", pg.locator(f"#reel-{cid} .reel-done").count() == 1)
            pg.screenshot(path=u.SHOTS / "bot-after-vote.png")

        def judge_no():
            pg.locator("[data-act=askreason], [data-act=vote][data-y='0']").first.click()
            pg.wait_for_timeout(500)
            r = pg.locator("[data-act=vote][data-y='0']")
            if r.count():
                r.first.click()
            pg.wait_for_timeout(3400)

        def judge_undo():
            tab("feed")
            pg.click("[data-act=feed-mode][data-k=judge]")
            pg.wait_for_timeout(500)
            card = pg.locator(".reel-item.judging").first
            card.scroll_into_view_if_needed()
            cid = card.get_attribute("data-id")
            before = len(u.writes)
            card.locator("[data-act=vote][data-y='1']").click()
            pg.wait_for_timeout(600)
            pg.click(".toast-undo")
            pg.wait_for_timeout(3600)
            w = u.writes[before:]
            ok = not any("/rest/v1/votes" in x and cid in x for x in w) and pg.locator(f"#reel-{cid} [data-act=vote][data-y='1']").count() == 1
            print("PASS" if ok else "FAIL", "Undo takes a vote back (nothing saved, clip back to judge)")
            return ok

        def record_and_post():
            tab("record")
            cam = pg.locator("[data-act=cam-open]")
            if cam.count():
                cam.first.click()
                pg.wait_for_timeout(1500)
            pg.locator("[data-act=rec-start]").first.click()
            pg.wait_for_timeout(3500)
            pg.locator("[data-act=rec-stop]").first.click()
            pg.wait_for_selector("#post-form", timeout=8000)
            pg.select_option("#post-trick", index=1)
            pg.click("#post-btn")
            pg.wait_for_timeout(3000)
            # After posting: 'Save to camera roll?' and Save hands the video to the share sheet
            sheet = pg.locator("#save-sheet").count() == 1
            pg.click("[data-act=save-go]") if sheet else None
            pg.wait_for_timeout(600)
            shared = pg.evaluate("window.__shared")
            ok = sheet and len(shared) == 1 and len(shared[0]) == 1 and shared[0][0].split('|')[1].startswith('video/') and int(shared[0][0].split('|')[2]) > 0
            print("PASS" if ok else "FAIL", "save to camera roll after posting |", shared, "| sheet gone:", pg.locator("#save-sheet").count() == 0)
            assert ok

        def every_screen():
            for t in ["lodge", "feed", "record", "duels"]:
                tab(t)
            pg.click("#me-chip")
            pg.wait_for_timeout(1200)

        results.append(step("fire a clip in the feed", fire, "/rest/v1/likes"))
        results.append(step("comment on a clip", comment, "/rest/v1/comments"))
        results.append(judge_undo())
        results.append(step("judge a clip: landed", judge_yes, "/rest/v1/votes"))
        results.append(step("judge a clip: bailed", judge_no, "/rest/v1/votes"))
        results.append(step("record with the camera and post", record_and_post, "/rest/v1/clips"))
        pg.screenshot(path=u.SHOTS / "bot-after-post.png")
        results.append(step("open every screen", every_screen, None))
        pg.screenshot(path=u.SHOTS / "bot-ranks.png")
        b.close()
    srv.shutdown()
    print(f"\n{sum(results)}/{len(results)} steps passed")
    print("page errors:", u.logs or "none")
    print("writes the bot made (faked, nothing real):")
    for w in u.writes:
        print("  ", w[:150])


if __name__ == "__main__":
    main()
