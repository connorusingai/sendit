r"""Play out Stomped's database rules on a throwaway Postgres, before touching the real one.

Loads supabase/001..006 into a local database (with small stand-ins for the parts of
Supabase that aren't plain Postgres: logins and file storage), then acts out real
scenarios and checks the numbers: points, grabs, one-and-done, votes, security, duels.

Setup (once):  py -3.12 -m pip install pgserver "psycopg[binary]"
Run:           py -3.12 supabase\tests\test_rules.py
"""

import sys
import tempfile
import uuid
from pathlib import Path

import pgserver
import psycopg

HERE = Path(__file__).resolve().parent
SQL_FILES = sorted((HERE.parent).glob("0*.sql"))

# Just enough of Supabase for our SQL to load: roles, auth.users + auth.uid(), storage tables.
SUPABASE_STANDINS = """
create role anon nologin;
create role authenticated nologin;
grant usage on schema public to anon, authenticated;
alter default privileges in schema public grant all on tables to anon, authenticated;
alter default privileges in schema public grant all on sequences to anon, authenticated;
alter default privileges in schema public grant execute on functions to anon, authenticated;

create schema auth;
grant usage on schema auth to anon, authenticated;
create table auth.users (id uuid primary key, email text, raw_user_meta_data jsonb default '{}');
create function auth.uid() returns uuid language sql stable as
  $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
grant execute on function auth.uid() to anon, authenticated;

create schema storage;
grant usage on schema storage to anon, authenticated;
create table storage.buckets (id text primary key, name text, public boolean,
  file_size_limit bigint, allowed_mime_types text[]);
create table storage.objects (bucket_id text, name text);
alter table storage.objects enable row level security;
create function storage.foldername(name text) returns text[] language sql immutable as
  $$ select (string_to_array(name, '/'))[1:array_length(string_to_array(name, '/'), 1) - 1] $$;
"""

results = []


def check(name, got, want):
    ok = got == want
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name:<58} got {got!r}" + ("" if ok else f"  (wanted {want!r})"))


def main():
    tmp = Path(tempfile.mkdtemp(prefix="sendit-pg-"))
    server = pgserver.get_server(tmp, cleanup_mode="delete")
    conn = psycopg.connect(server.get_uri(), autocommit=True)
    q = lambda sql, *a: conn.execute(sql, a or None)   # no params = run the text as-is (SQL files contain % signs)
    one = lambda sql, *a: conn.execute(sql, a or None).fetchone()[0]

    q(SUPABASE_STANDINS)
    # The local test Postgres may ship without time zone data; Supabase has it. Same rules, UTC clock.
    try:
        q("select now() at time zone 'America/Denver'")
        has_tz = True
    except psycopg.Error:
        has_tz = False
        print("(no time zone data here: testing on a UTC clock instead of Denver)")
    for f in SQL_FILES:
        sql = f.read_text(encoding="utf-8")
        q(sql if has_tz else sql.replace("'America/Denver'", "'UTC'"))
    print(f"Loaded {', '.join(f.name for f in SQL_FILES)}\n")

    def user(name, points=0):
        uid = str(uuid.uuid4())
        q("insert into auth.users (id, email, raw_user_meta_data) values (%s, %s, jsonb_build_object('username', %s::text))",
          uid, f"{name}@test", name)
        if points:
            q("update public.profiles set points = %s where id = %s", points, uid)
        return uid

    voters = [user(f"judge{i}") for i in range(5)]

    def post(uid, trick, grab="No grab"):
        return str(one("insert into public.clips (user_id, trick_id, grab) values (%s, %s, %s) returning id", uid, trick, grab))

    def judge(clip, landed=True, who=voters):
        for v in who:
            q("insert into public.votes (clip_id, voter_id, landed) values (%s, %s, %s)", clip, v, landed)
        return conn.execute("select status, points_awarded from public.clips where id = %s", (clip,)).fetchone()

    def land(uid, trick, grab="No grab"):
        return judge(post(uid, trick, grab))[1]

    totd = one("select public.trick_of_day()")
    plain = "360" if totd != "360" else "540"   # a trick that isn't today's Trick of the Day

    print("-- One and done, grabs pay just the grab --")
    a = user("alex")
    check("new trick with a grab: 360 Mute = 20 x 1.2", land(a, plain, "Mute"), round(20 * 1.2) if plain == "360" else round(35 * 1.2))
    base = 20 if plain == "360" else 35
    check("same trick, new grab (Safety) = 20% of base", land(a, plain, "Safety"), round(base * 0.2))
    check("exact repeat (Mute again) = 0", land(a, plain, "Mute"), 0)
    check("same trick, no grab = 0", land(a, plain), 0)
    check("rider's total is the sum", one("select points from public.profiles where id = %s", a),
          round(base * 1.2) + round(base * 0.2))

    print("\n-- Trick of the Day --")
    b = user("blake")
    t_pts = one("select pts from public.tricks where id = %s", totd)
    check(f"new trick on its day ({totd}) = 2x base", land(b, totd), t_pts * 2)
    check("landing it again the same day = 0", land(b, totd), 0)
    c = user("casey")
    q("""insert into public.clips (user_id, trick_id, grab, status, points_awarded, created_at, verified_at)
         values (%s, %s, 'No grab', 'verified', %s, now() - interval '3 days', now() - interval '3 days')""", c, totd, t_pts)
    check("already had it before today: repeat pays base once", land(c, totd), t_pts)
    check("...and only once", land(c, totd), 0)

    print("\n-- Voting --")
    d = user("drew")
    check("5 'not landed' votes -> rejected, 0 pts", judge(post(d, plain), landed=False), ("rejected", None))
    clip = post(d, plain)
    check("1 Bronze vote is not enough weight to decide (needs 2)", judge(clip, who=voters[:1])[0], "pending")
    legend = user("legend", points=1500)
    check("a Legend vote (x2.25) tips it over 2", judge(clip, who=[legend])[0], "verified")
    check("2 Bronze votes decide a clip (a 3-person friend test works)", judge(post(d, "180"), who=voters[:2])[0], "verified")
    split = post(d, "360")
    judge(split, who=voters[:1])
    check("1 yes + 1 no is a split: it waits for more judges (018)", judge(split, landed=False, who=voters[1:2])[0], "pending")
    check("...and 2 more yes votes verify it (3 of 4 = 75%)", judge(split, who=voters[2:4])[0], "verified")

    print("\n-- Security (acting as a signed-in rider) --")
    def as_user(uid, sql, *a):
        with conn.transaction():
            q("set local role authenticated")
            q("select set_config('request.jwt.claim.sub', %s, true)", uid)
            cur = conn.execute(sql, a or None)
            return cur.fetchall() if cur.description else []

    def blocked(uid, sql, *a):
        try:
            as_user(uid, sql, *a)
            return False
        except psycopg.Error:
            return True

    e = user("eli")
    check("can't post a clip already marked verified", blocked(e, "insert into public.clips (trick_id, status) values ('180', 'verified')"), True)
    check("can't give yourself points", blocked(e, "update public.profiles set points = 9999 where id = auth.uid()"), True)
    own = as_user(e, "insert into public.clips (trick_id) values ('180') returning id")[0][0]
    check("can't vote on your own clip", blocked(e, "insert into public.votes (clip_id, landed) values (%s, true)", own), True)
    check("can't write to duels directly", blocked(e, "insert into public.duels (challenger, opponent) values (auth.uid(), auth.uid())"), True)

    print("\n-- Trick list --")
    check("all ski tricks loaded (37 + 8 from 014 + 7 from 016)", one("select count(*) from public.tricks where sport = 'ski'"), 52)
    check("all snowboard tricks loaded (40 + 3 from 014 + 8 from 016)", one("select count(*) from public.tricks where sport = 'snowboard'"), 51)
    check("no duplicate trick names within a sport",
          one("select count(*) from (select sport, name from public.tricks group by 1, 2 having count(*) > 1) d"), 0)
    s = user("switchy")
    check("Switch 360 is its own trick: pays full 26", land(s, "sw360"), 26 if totd != "sw360" else 52)

    print("\n-- Friends + Game of S.K.I. --")
    p1, p2 = user("setter"), user("matcher")
    check("can't duel a stranger", blocked(p1, "select public.start_duel(%s)", p2), True)
    as_user(p1, "insert into public.friendships (addressee) values (%s)", p2)
    as_user(p2, "update public.friendships set status = 'accepted' where requester = %s", p1)
    duel = as_user(p1, "select public.start_duel(%s)", p2)[0][0]
    check("friends can start a duel", duel is not None, True)
    check("can't start a second duel with the same friend", blocked(p1, "select public.start_duel(%s)", p2), True)
    check("landing needs a clip as proof", blocked(p1, "select public.duel_move(%s, true, '540', null)", duel), True)
    for round_no in range(3):
        clip1 = as_user(p1, "insert into public.clips (trick_id) values ('540') returning id")[0][0]
        as_user(p1, "select public.duel_move(%s, true, '540', %s)", duel, clip1)      # setter lands it
        if round_no == 0:
            check("setter can't move twice in a row", blocked(p1, "select public.duel_move(%s, false, '180', null)", duel), True)
        as_user(p2, "select public.duel_move(%s, false, null, null)", duel)            # matcher misses
    row = conn.execute("select status, winner, letters_opponent, rating_change from public.duels where id = %s", (duel,)).fetchone()
    check("3 misses spells S-K-I: duel over", row[0], "done")
    check("setter won", str(row[1]), p1)
    check("equal ratings: winner gets +16", row[3], 16)
    check("ratings moved: 1016 vs 984",
          (one("select rating from public.profiles where id = %s", p1), one("select rating from public.profiles where id = %s", p2)),
          (1016, 984))

    print("\n-- Crews --")
    k1, k2, k3 = user("cap", points=300), user("mate", points=100), user("rival", points=50)
    crew = as_user(k1, "select public.create_crew('CU Freeride', 'cuf')")[0][0]
    code = as_user(k1, "select code from public.my_crew()")[0][0]
    check("creator is in the crew, tag uppercased", as_user(k1, "select tag from public.my_crew()")[0][0], "CUF")
    check("invite codes are hidden from outsiders", blocked(k3, "select code from public.crews"), True)
    check("outsiders can still see crew names", as_user(k3, "select name from public.crews")[0][0], "CU Freeride")
    check("can't join directly (must use a code)",
          blocked(k2, "insert into public.crew_members (user_id, crew_id) values (auth.uid(), %s)", crew), True)
    check("wrong code is refused", blocked(k2, "select public.join_crew('ZZZZZZ')"), True)
    as_user(k2, "select public.join_crew(%s)", code.lower())
    check("joining with the code works (any case)", one("select count(*) from public.crew_members where crew_id = %s", crew), 2)
    check("names are unique (ignoring case)", blocked(k3, "select public.create_crew('cu freeride', 'CU')"), True)
    check("one crew at a time", blocked(k2, "select public.create_crew('Second Crew', 'SC')"), True)
    as_user(k3, "select public.create_crew('Eldo Rats', 'ELDO')")
    board = as_user(k3, "select name, members, score from public.crew_board('all')")
    check("crew board: members' points add up", board, [("CU Freeride", 2, 400), ("Eldo Rats", 1, 50)])
    check("only the owner can kick", blocked(k3, "select public.kick_from_crew(%s)", k2), True)
    as_user(k1, "select public.leave_crew()")
    check("owner leaves: crew passes to the next member",
          str(one("select owner from public.crews where id = %s", crew)), k2)
    as_user(k2, "select public.leave_crew()")
    check("last one out deletes the crew", one("select count(*) from public.crews where id = %s", crew), 0)

    print("\n-- Reports, hiding, and deleting your stuff (011) --")
    poster, r1, r2, r3 = user("poster"), user("rep1"), user("rep2"), user("rep3")
    bad = post(poster, "180")
    as_user(r1, "insert into public.reports (clip_id, reason) values (%s, 'inappropriate')", bad)
    check("can't report the same clip twice", blocked(r1, "insert into public.reports (clip_id, reason) values (%s, 'spam')", bad), True)
    check("can't report for someone else",
          blocked(r1, "insert into public.reports (reporter, clip_id, reason) values (%s, %s, 'spam')", r2, bad), True)
    as_user(r2, "insert into public.reports (clip_id, reason) values (%s, 'spam')", bad)
    check("2 reports: still visible", len(as_user(r3, "select id from public.clips where id = %s", bad)), 1)
    as_user(r3, "insert into public.reports (clip_id, reason) values (%s, 'fake')", bad)
    check("3 reports: hidden from other riders", len(as_user(r1, "select id from public.clips where id = %s", bad)), 0)
    check("...but the poster still sees it", len(as_user(poster, "select id from public.clips where id = %s", bad)), 1)
    check("can't unhide it yourself", blocked(poster, "update public.clips set hidden = false where id = %s", bad), True)
    com = as_user(r1, "insert into public.comments (clip_id, body) values (%s, 'rude') returning id", own)[0][0]
    for who in (r2, r3, poster):
        as_user(who, "insert into public.reports (comment_id, reason) values (%s, 'inappropriate')", com)
    check("3 reports hide a comment", len(as_user(e, "select id from public.comments where id = %s", com)), 0)
    check("a report must name exactly one thing",
          blocked(r1, "insert into public.reports (clip_id, comment_id, reason) values (%s, %s, 'spam')", own, com), True)
    mine = post(poster, "360")
    judge(mine)
    check("can't remove someone else's clip", blocked(r1, "select public.hide_my_clip(%s)", mine), True)
    pts = one("select points from public.profiles where id = %s", poster)
    as_user(poster, "select public.hide_my_clip(%s)", mine)
    check("removing your verified clip hides it", len(as_user(r1, "select id from public.clips where id = %s", mine)), 0)
    check("...keeps your points", one("select points from public.profiles where id = %s", poster), pts)
    check("...and re-posting the trick pays 0 (no farming)", land(poster, "360"), 0 if totd != "360" else 20)
    def anon_blocked(sql):
        try:
            with conn.transaction():
                q("set local role anon"); q(sql)
            return False
        except psycopg.Error:
            return True
    check("signed-out visitors can't call delete_my_account", anon_blocked("select public.delete_my_account()"), True)
    as_user(p1, "select public.delete_my_account()")   # p1 won a duel above: the winner link must not block it
    check("delete my account: login gone", one("select count(*) from auth.users where id = %s", p1), 0)
    check("...profile gone", one("select count(*) from public.profiles where id = %s", p1), 0)
    check("...their duels gone", one("select count(*) from public.duels where challenger = %s or opponent = %s", p1, p1), 0)
    check("...the other rider's account is untouched", one("select count(*) from public.profiles where id = %s", p2), 1)

    print("\n-- Feedback (012) --")
    f1, f2 = user("tester1"), user("tester2")
    as_user(f1, "insert into public.feedback (kind, body, page) values ('bug', 'camera froze', 'record')")
    check("a rider can send feedback", one("select count(*) from public.feedback where user_id = %s", f1), 1)
    check("...and read their own back", len(as_user(f1, "select id from public.feedback")), 1)
    check("other riders can't read it", len(as_user(f2, "select id from public.feedback")), 0)
    check("can't send feedback as someone else",
          blocked(f1, "insert into public.feedback (user_id, kind, body) values (%s, 'idea', 'x')", f2), True)
    check("empty feedback is refused", blocked(f1, "insert into public.feedback (kind, body) values ('idea', '   ')"), True)
    check("unknown kind is refused", blocked(f1, "insert into public.feedback (kind, body) values ('rant', 'x')"), True)
    check("can't edit feedback after sending", blocked(f1, "update public.feedback set body = 'changed'"), True)
    check("signed-out visitors can't send feedback",
          anon_blocked("insert into public.feedback (kind, body) values ('idea', 'x')"), True)
    for i in range(19):
        as_user(f1, "insert into public.feedback (kind, body) values ('idea', %s)", f"idea {i}")
    check("21st message in a day is refused (limit 20)",
          blocked(f1, "insert into public.feedback (kind, body) values ('idea', 'one too many')"), True)

    print("\n-- Rail combos (014) --")
    check("11 new rail tricks", one("""select count(*) from public.tricks where id in ('sw5050','180on','180out','gapon',
          'swap','backswap','sw270out','450on','sb-fsboard','sb-fslip','sb-gapon')"""), 11)
    g = user("gus")
    first = "270on" if totd != "270on" else "board"   # keep Trick of the Day out of the sums
    fp = one("select pts from public.tricks where id = %s", first)
    def combo(uid, trick, chain):
        clip = as_user(uid, "insert into public.clips (trick_id, combo) values (%s, %s) returning id", trick, chain)[0][0]
        return judge(clip)[1]
    check("new combo = first trick + half the added tricks (Swap 35 + 270 Out 40)",
          combo(g, first, ["swap", "270out"]), fp + round(75 * 0.5))
    check("same combo again = 0", combo(g, first, ["swap", "270out"]), 0)
    check("same first trick, new combo = just the combo bonus", combo(g, first, ["swap"]), round(35 * 0.5))
    check("combo on a jump trick is refused", blocked(g, "insert into public.clips (trick_id, combo) values ('360', '{swap}')"), True)
    check("jump trick inside a rail combo is refused", blocked(g, "insert into public.clips (trick_id, combo) values ('5050', '{360}')"), True)
    check("snowboard trick in a ski combo is refused",
          blocked(g, "insert into public.clips (trick_id, combo) values ('5050', '{sb-5050}')"), True)
    check("more than 4 tricks is refused",
          blocked(g, "insert into public.clips (trick_id, combo) values ('5050', '{swap,backswap,270out,180out}')"), True)
    check("the same trick twice is refused", blocked(g, "insert into public.clips (trick_id, combo) values ('5050', '{swap,swap}')"), True)
    check("repeating the first trick is refused", blocked(g, "insert into public.clips (trick_id, combo) values ('5050', '{5050}')"), True)

    print("\n-- Motion logs (015) --")
    check("clips bucket takes videos and motion JSON",
          one("select allowed_mime_types from storage.buckets where id = 'clips'"),
          ["video/mp4", "video/quicktime", "video/webm", "application/json"])

    print("\n-- Beginner tricks + easier Trick of the Day (016) --")
    check("7 new ski + 8 new snowboard beginner tricks", one("""select count(*) from public.tricks where id in
          ('straightair','shifty','daffy','butter180','butter360','nosetap','tailtap','sb-ollie','sb-straightair',
           'sb-shifty','sb-fs180','sb-butter180','sb-butter360','sb-nosetap','sb-tailtap')"""), 15)
    check("Trick of the Day: own sport, Park/Rails, 60 pts max (a year, both sports)", one("""
          select count(*) from generate_series(0, 365) g cross join (values ('ski'), ('snowboard')) s(sp)
            join public.tricks t on t.id = public.trick_of_day(s.sp, current_date + g)
           where t.sport <> s.sp or t.category not in ('Park','Rails') or t.pts > 60"""), 0)
    sb_totd = one("select public.trick_of_day('snowboard')")
    sb = user("boarder")
    check("snowboard Trick of the Day pays 2x", land(sb, sb_totd), 2 * one("select pts from public.tricks where id = %s", sb_totd))
    b = user("beginner")
    check("Straight Air pays 5", land(b, "straightair"), 5 if totd != "straightair" else 10)

    print("\n-- Film a friend (017) --")
    rider, filmer, stranger = user("rider"), user("filmer"), user("stranger")
    q("insert into public.friendships (requester, addressee, status) values (%s, %s, 'accepted')", filmer, rider)
    film = lambda who, for_whom, path=None: as_user(who, "select public.post_for_friend(%s, '180', 'No grab', 'Eldora', %s)",
                                                     for_whom, path or f"{who}/x.mp4")[0][0]
    fc = film(filmer, rider)
    seen = lambda who: one("select count(*) from (select 1 from public.clips where id = %s) s", fc) if who is None else \
        len(as_user(who, "select id from public.clips where id = %s", fc))
    check("friend can film you: clip is yours, waiting", conn.execute(
          "select user_id::text, filmed_by::text, rider_ok from public.clips where id = %s", (fc,)).fetchone(), (rider, filmer, False))
    check("waiting clip: rider and filmer see it, others don't", (seen(rider), seen(filmer), seen(stranger)), (1, 1, 0))
    check("can't film a stranger", blocked(stranger, "select public.post_for_friend(%s, '180', 'No grab', null, %s)", rider, f"{stranger}/x.mp4"), True)
    check("can't post a video from someone else's folder", blocked(filmer, "select public.post_for_friend(%s, '180', 'No grab', null, %s)", rider, f"{rider}/x.mp4"), True)
    check("can't 'film' yourself this way", blocked(filmer, "select public.post_for_friend(%s, '180', 'No grab', null, %s)", filmer, f"{filmer}/x.mp4"), True)
    check("nobody can judge a clip before the rider keeps it", blocked(voters[0], "insert into public.votes (clip_id, landed) values (%s, true)", fc), True)
    check("filmer can't answer for the rider", blocked(filmer, "select public.answer_filmed_clip(%s, true)", fc), True)
    as_user(rider, "select public.answer_filmed_clip(%s, true)", fc)
    check("rider keeps it: everyone sees it", seen(stranger), 1)
    check("filmer still can't judge a clip they filmed", blocked(filmer, "insert into public.votes (clip_id, landed) values (%s, true)", fc), True)
    check("kept clip verifies and pays the RIDER", (judge(fc)[0], one("select points from public.profiles where id = %s", rider) > 0,
          one("select points from public.profiles where id = %s", filmer)), ("verified", True, 0))
    nope = film(filmer, rider)
    check("'Not me' deletes it and returns the video path", as_user(rider, "select public.answer_filmed_clip(%s, false)", nope)[0][0], f"{filmer}/x.mp4")
    check("...and it's gone", one("select count(*) from public.clips where id = %s", nope), 0)

    print("\n-- Judge score (018) --")
    honest, joker, poster = [user(f"honest{i}") for i in range(3)], user("joker"), user("poster18")
    trust = lambda uid: float(one("select public.judge_trust(%s)", uid))
    check("a new judge's vote counts fully", trust(joker), 1.0)
    for _ in range(4):   # the joker says bailed, three honest judges say landed
        c = post(poster, "180")
        judge(c, landed=False, who=[joker])
        judge(c, who=honest)
    check("4 jokes in a row: joker's vote is worth under 0.2", round(trust(joker), 2), 0.18)
    check("honest judges keep full weight", round(trust(honest[0]), 2), 1.0)
    c = post(poster, "180")
    judge(c, landed=False, who=[joker])
    check("joker + 1 honest 'landed': not enough weight yet", judge(c, who=honest[:1])[0], "pending")
    check("...a 2nd honest vote verifies it (the joke barely counts)", judge(c, who=honest[1:2])[0], "verified")
    check("nobody can read the scores from the app", blocked(joker, "select * from public.judge_stats"), True)
    check("nobody can call judge_trust from the app", blocked(joker, "select public.judge_trust(auth.uid())"), True)

    conn.close()
    print(f"\n{sum(results)}/{len(results)} passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
