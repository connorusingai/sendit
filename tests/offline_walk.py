"""Mountain-proof uploads (outbox.js): clips are saved on the phone first and post when the signal comes back.

Same fake database as ui_walk.py (nothing reaches the real one). "No signal" = the fake database drops the
upload (like a dead connection); "back in range" = it answers again and the phone says it's online.
The service worker is switched off here so every upload goes through the page and can be watched.

Run:  .venv-test\\Scripts\\python.exe tests\\offline_walk.py        (from dev\\sendit)

Checks:
  1. The retry plan: backoff 5 s ... 5 min, timeouts, which errors retry, smaller clips on weak signal / low battery.
  2. A filmed clip is on the phone before Post: close the app, reopen, and Record gives it back.
  3. No signal: Post saves it, says "waiting for signal", and nothing is lost when the app closes and reopens.
  4. Back in range: it uploads by itself once, and the note at the top goes away.
  5. Signal drops between steps: the retry doesn't upload the video twice.
  6. The server refuses a saved clip: it's kept ("didn't post"), and the rider can delete it.
"""
import json

from playwright.sync_api import sync_playwright

import ui_walk as u

mode = {"storage": "ok", "insert": "ok"}
uploads, inserts, lookups = [], [], []


def handle(route, req):
    path = req.url.split(".supabase.co", 1)[1]
    if req.method == "POST" and path.startswith("/storage/v1/object/clips/") and not path.endswith(".motion.json"):
        if mode["storage"] == "abort":
            return route.abort("internetdisconnected")
        uploads.append(path)
    if req.method == "GET" and "video_path=eq." in path:
        lookups.append(path)
        return route.fulfill(json=[])
    if req.method == "POST" and path.startswith("/rest/v1/clips"):
        if mode["insert"] == "abort":
            return route.abort("internetdisconnected")
        if mode["insert"] == "500":
            return route.fulfill(status=503, json={"message": "upstream busy"})
        if mode["insert"] == "400":
            return route.fulfill(status=400, json={"message": "Pick a real trick", "code": "P0001"})
        inserts.append(req.post_data)
    return u.handle(route, req)


def main():
    u.SHOTS.mkdir(exist_ok=True)
    srv = u.serve()
    ok = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"])
        ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True,
                            permissions=["camera", "microphone"], service_workers="block")
        ctx.add_init_script(f"localStorage.setItem('sb-{u.REF}-auth-token', {json.dumps(json.dumps(u.session))});"
                            "localStorage.setItem('sendit-save-ask', 'off');")
        ctx.route(f"https://{u.REF}.supabase.co/**", handle)
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: u.logs.append(f"PAGEERROR: {e}"))
        pg.on("dialog", lambda d: d.accept())

        def open_app():
            pg.goto(u.URL, wait_until="networkidle")
            pg.wait_for_timeout(2000)
            pg.mouse.click(195, 420)          # past the rank splash
            pg.wait_for_timeout(800)

        def tab(t):
            pg.evaluate(f"document.querySelector('#tabs [data-tab={t}]').click()")
            pg.wait_for_timeout(1200)

        def record():
            tab("record")
            cam = pg.locator("[data-act=cam-open]")
            if cam.count():
                cam.first.click()
                pg.wait_for_timeout(1500)
            pg.locator("[data-act=rec-start]").first.click()
            pg.wait_for_timeout(2500)
            pg.locator("[data-act=rec-stop]").first.click()
            pg.wait_for_selector("#post-form", timeout=8000)
            pg.wait_for_timeout(800)          # the draft saves

        def post():
            pg.select_option("#post-trick", index=1)
            pg.click("#post-btn")
            pg.wait_for_timeout(2500)

        def items():
            return pg.evaluate("StompedOutbox.all().then(a => a.map(i => ({kind: i.kind, stuck: !!i.stuck, uploaded: !!i.uploaded,"
                               " attempts: i.attempts || 0, size: i.blob && i.blob.size})))")

        def chip():
            c = pg.locator("#outbox-chip")
            return "" if c.get_attribute("hidden") is not None else c.text_content()

        def toast_text():
            return pg.locator("#toast").inner_text()

        open_app()
        print("app open at", pg.url, "| outbox loaded:", pg.evaluate("typeof StompedOutbox") == "object")

        # 1. The retry plan
        plan = pg.evaluate("""() => { const O = StompedOutbox;
          return {b1: O.backoff(1), b2: O.backoff(2), b20: O.backoff(20), t4mb: O.uploadTimeout(4e6),
            net: O.isTransient({offline: true}), s503: O.isTransient({status: 503}), s400: O.isTransient({status: 400}),
            s401: O.isTransient({status: 401}), normal: O.planFor({connection: {effectiveType: '4g', downlink: 10}}),
            weak: O.planFor({connection: {effectiveType: '3g'}}), cold: O.planFor({battery: {level: 0.15, charging: false}}),
            queued: O.planFor({waiting: 2})}; }""")
        ok.append(("Backoff starts near 5 s and doubles", 4000 <= plan["b1"] <= 6000 and 8000 <= plan["b2"] <= 12000))
        ok.append(("Backoff is capped at about 5 min", plan["b20"] <= 360000))
        ok.append(("A 4 MB clip gets a few minutes before timing out", 120000 < plan["t4mb"] < 300000))
        ok.append(("No signal / server busy / login ran out retry; a refusal doesn't",
                   plan["net"] and plan["s503"] and plan["s401"] and not plan["s400"]))
        ok.append(("Good signal records normally (1.5 Mbit/s, 60 fps)", plan["normal"]["bps"] == 1500000 and plan["normal"]["fps"] == 60))
        ok.append(("Weak signal records smaller, still 60 fps", plan["weak"]["bps"] < 1500000 and plan["weak"]["fps"] == 60))
        ok.append(("Low battery records smaller at 30 fps", plan["cold"]["bps"] < 1500000 and plan["cold"]["fps"] == 30))
        ok.append(("Clips already waiting: next one records smaller", plan["queued"]["lite"]))
        saved = pg.evaluate("StompedOutbox.save({kind: 'test', id: undefined}).then(i => StompedOutbox.remove(i.id).then(() => !!i.id))")
        ok.append(("Saving without an id still gets one", saved))

        # 2. Filmed, not posted, app closed: Record gives it back
        record()
        ok.append(("Filmed clip is on the phone before Post", [i["kind"] for i in items()] == ["draft"]))
        open_app()
        tab("record")
        pg.wait_for_timeout(800)
        ok.append(("Reopened app: Record brings the unposted clip back", pg.locator("#post-form").count() == 1
                   and "still here" in toast_text()))

        # 3. No signal: Post saves it and waits
        mode["storage"] = "abort"
        post()
        its = items()
        ok.append(("No signal: the clip is saved to post later (not lost)", len(its) == 1 and its[0]["kind"] == "post" and its[0]["size"] > 0))
        ok.append(("No signal: says it'll post when back in range", "back in range" in toast_text().lower()))
        ok.append(("No signal: note at the top says 'Waiting for signal'", chip().startswith("Waiting for signal")))
        ok.append(("No signal: nothing was posted", not inserts))
        pg.screenshot(path=u.SHOTS / "offline-1-waiting.png")
        open_app()   # the app is closed and opened again, still no signal
        pg.wait_for_timeout(1000)
        its = items()
        ok.append(("Closed and reopened: the clip is still waiting", len(its) == 1 and its[0]["kind"] == "post" and its[0]["attempts"] >= 2))
        ok.append(("Closed and reopened: still says 'Waiting for signal'", chip().startswith("Waiting for signal")))

        # 4. Back in range
        mode["storage"] = "ok"
        pg.evaluate("window.dispatchEvent(new Event('online'))")
        pg.wait_for_timeout(3000)
        ok.append(("Back in range: it uploads and posts once", len(uploads) == 1 and len(inserts) == 1))
        ok.append(("Back in range: it leaves the phone's queue", items() == []))
        ok.append(("Back in range: the note goes away", chip() == ""))

        # 5. Signal drops after the video got through: the retry doesn't upload it twice
        uploads.clear(); inserts.clear(); lookups.clear()
        mode["insert"] = "abort"
        record(); post()
        its = items()
        ok.append(("Dropped mid-post: saved, video marked as uploaded", len(its) == 1 and its[0]["uploaded"] and not its[0]["stuck"]))
        mode["insert"] = "500"
        pg.evaluate("window.dispatchEvent(new Event('online'))")
        pg.wait_for_timeout(2000)
        ok.append(("Server busy: still waiting, not given up", len(items()) == 1 and not items()[0]["stuck"]))
        mode["insert"] = "ok"
        pg.evaluate("window.dispatchEvent(new Event('online'))")
        pg.wait_for_timeout(2500)
        ok.append(("Retry: video uploaded only once", len(uploads) == 1))
        ok.append(("Retry: checks it wasn't already posted, then posts once", len(lookups) >= 1 and len(inserts) == 1 and items() == []))

        # 6. The server refuses a saved clip: kept, then the rider deletes it
        mode["storage"] = "abort"
        record(); post()
        mode["storage"] = "ok"; mode["insert"] = "400"
        pg.evaluate("window.dispatchEvent(new Event('online'))")
        pg.wait_for_timeout(2500)
        its = items()
        ok.append(("Refused: the clip is kept, marked didn't post", len(its) == 1 and its[0]["stuck"]))
        ok.append(("Refused: the note says it didn't post", "didn't post" in chip()))
        pg.click("#outbox-chip"); pg.wait_for_timeout(600)
        sheet = pg.locator("#stuck-sheet")
        ok.append(("Tapping the note explains why, with Delete / Save / Try again",
                   sheet.count() == 1 and "Pick a real trick" in sheet.inner_text() and sheet.locator("[data-act=outbox-retry]").count() == 1))
        pg.screenshot(path=u.SHOTS / "offline-2-stuck.png")
        pg.click("[data-act=outbox-delete]"); pg.wait_for_timeout(800)
        ok.append(("Delete removes it (after asking)", items() == [] and chip() == ""))

        # Refused while you're still on the form: the clip stays in the recorder to fix and post again
        mode["insert"] = "400"
        record(); post()
        ok.append(("Refused on Post: the clip stays on the form", pg.locator("#post-form").count() == 1 and "Post failed" in toast_text()
                   and [i["kind"] for i in items()] == ["draft"]))
        mode["insert"] = "ok"
        b.close()
    srv.shutdown()
    for name, good in ok:
        print(("PASS " if good else "FAIL ") + name)
    print(f"\n{sum(g for _, g in ok)}/{len(ok)} checks passed")
    print("page errors:", u.logs or "none")


if __name__ == "__main__":
    main()
