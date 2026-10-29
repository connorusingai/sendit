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

    def user(name, points=0, new=False):
        uid = str(uuid.uuid4())
        q("insert into auth.users (id, email, raw_user_meta_data) values (%s, %s, jsonb_build_object('username', %s::text))",
          uid, f"{name}@test", name)
        if points:
            q("update public.profiles set points = %s where id = %s", points, uid)
        if not new:   # test riders are a few days old unless a check is about brand-new accounts (023)
            q("update public.profiles set created_at = now() - interval '3 days' where id = %s", uid)
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

    print("\n-- Wrong rider (019) --")
    give = "select public.give_clip_to_friend(%s, %s)"
    oops = as_user(filmer, "insert into public.clips (trick_id, video_path) values ('180', %s) returning id", f"{filmer}/y.mp4")[0][0]
    q("insert into public.votes (clip_id, voter_id, landed) values (%s, %s, true)", oops, voters[0])
    check("can't give your clip to a stranger", blocked(filmer, give, oops, stranger), True)
    check("someone else can't give your clip away", blocked(stranger, give, oops, rider), True)
    as_user(filmer, give, oops, rider)
    check("given to the friend: theirs, filmed by you, waiting", conn.execute(
          "select user_id::text, filmed_by::text, rider_ok from public.clips where id = %s", (oops,)).fetchone(), (rider, filmer, False))
    check("...and the old votes are cleared", one("select count(*) from public.votes where clip_id = %s", oops), 0)
    check("rider can't pass a friend-filmed clip on", blocked(rider, give, oops, filmer), True)
    done = as_user(filmer, "insert into public.clips (trick_id) values ('180') returning id")[0][0]
    judge(done)
    check("verified clips can't change hands", blocked(filmer, give, done, rider), True)

    print("\n-- Your clip, your video (020) --")
    thief, pro = user("thief"), user("pro")
    mine = "insert into public.clips (trick_id, video_path) values ('dc1080', %s)"
    check("can't post someone else's video as your clip", blocked(thief, mine, f"{pro}/landed.mp4"), True)
    check("can't sneak out of your folder with ../", blocked(thief, mine, f"{thief}/../{pro}/landed.mp4"), True)
    check("can't point the clip at a web link", blocked(thief, mine, "https://example.com/landed.mp4"), True)
    check("...but your own video posts fine", blocked(thief, mine, f"{thief}/{uuid.uuid4()}.webm"), False)
    check("film a friend can't sneak out with ../ either", blocked(filmer, "select public.post_for_friend(%s, '180', 'No grab', null, %s)",
          rider, f"{filmer}/../{stranger}/x.mp4"), True)

    print("\n-- Event log + Founder dashboard (021) --")
    rider21, nosy = user("rider21"), user("nosy21")
    creator = "713e0c5f-7de1-4842-b845-d1679b4eb7b3"
    q("insert into auth.users (id, email, raw_user_meta_data) values (%s, 'c@test', jsonb_build_object('username', 'cdoraz', 'src', 'ig'))", creator)
    log = "insert into public.events (name, detail) values (%s, %s)"
    check("a rider can log their own event", blocked(rider21, log, "tab", "feed"), False)
    check("...but not one for someone else", blocked(rider21, "insert into public.events (user_id, name) values (%s, 'tab')", nosy), True)
    check("names are plain words only", blocked(rider21, log, "drop table;", None), True)
    check("nobody can read the log from the app", blocked(nosy, "select count(*) from public.events"), True)
    check("nobody can erase the log from the app", blocked(rider21, "delete from public.events"), True)
    for _ in range(130):
        as_user(rider21, log, "record_start", None)
    check("spam: 120 a minute max, the rest dropped", one("select count(*) from public.events where user_id = %s", rider21), 120)
    check("riders can't open the Founder dashboard", blocked(nosy, "select public.founder_stats()"), True)
    st = as_user(creator, "select public.founder_stats()")[0][0]
    check("rider #001 can", (st["riders"] > 0, st["funnel"]["filmed"] >= 1, any(r["username"] == "rider21" for r in st["riders_list"])), (True, True, True))
    check("...and sees where sign-ups came from", any(x["src"] == "ig" for x in st["by_src"]), True)
    as_user(rider21, "select public.delete_my_account()")
    check("deleting your account deletes your events", one("select count(*) from public.events where user_id = %s", rider21), 0)

    print("\n-- Trick AI guesses (022) --")
    ai_r, ai_x = user("airider"), user("aistranger")
    ai_clip = as_user(ai_r, "insert into public.clips (trick_id) values ('360') returning id")[0][0]
    guess = "insert into public.clip_ai (clip_id, spin, axis, landed, sure, seen) values (%s, %s, 'flat', true, 0.7, 0.9)"
    check("someone else can't add a guess to your clip", blocked(ai_x, guess, ai_clip, 360), True)
    check("the AI can't claim a spin that isn't a trick (370)", blocked(ai_r, guess, ai_clip, 370), True)
    check("your phone adds the AI guess to your clip", blocked(ai_r, guess, ai_clip, 360), False)
    check("...only once", blocked(ai_r, guess, ai_clip, 360), True)
    check("...and nobody can change it", blocked(ai_r, "update public.clip_ai set spin = 720 where clip_id = %s", ai_clip), True)
    check("the guess stays in the background: riders can't read it", blocked(ai_x, "select spin from public.clip_ai"), True)
    check("...not even on their own clip", blocked(ai_r, "select spin from public.clip_ai"), True)
    judge(ai_clip)
    check("riders can't open the AI scorecard", blocked(ai_x, "select public.founder_ai_stats()"), True)
    sc = as_user(creator, "select public.founder_ai_stats()")[0][0]
    check("rider #001's scorecard: AI was right on the verified 360", (sc["spin_calls"], sc["spin_right"], sc["landed_right"]), (1, 1, 1))
    late = as_user(ai_r, "insert into public.clips (trick_id) values ('180') returning id")[0][0]
    judge(late)
    check("no guesses added after riders decided", blocked(ai_r, guess, late, 180), True)

    print("\n-- Fake accounts count half for their first day (023) --")
    cheat, alt1, alt2, alt3 = user("cheater"), user("alt1", new=True), user("alt2", new=True), user("alt3", new=True)
    fake = post(cheat, "540")
    judge(fake, who=[alt1, alt2])
    check("2 brand-new accounts can't verify your clip anymore", one("select status from public.clips where id = %s", fake), "pending")
    judge(fake, who=[voters[0]])
    check("...but one real rider + 2 new ones can (1 + 0.5 + 0.5)", one("select status from public.clips where id = %s", fake), "verified")
    target = post(d, "180")
    for r in (alt1, alt2, alt3):
        as_user(r, "insert into public.reports (clip_id, reason) values (%s, 'spam')", target)
    check("3 brand-new accounts can't hide someone's clip", one("select hidden from public.clips where id = %s", target), False)
    q("update public.profiles set created_at = now() - interval '2 days' where id = any(%s)", [alt1, alt2, alt3])
    check("after a day they count fully", one("select public.new_account_factor(%s)", alt1), 1)

    print("\n-- Season passes (024) --")
    p1, p2 = user("passer1"), user("passer2")
    n1, n2 = one("select pass_no from public.profiles where id = %s", p1), one("select pass_no from public.profiles where id = %s", p2)
    check("every rider gets a pass number, in join order", (n1 is not None, n2 == n1 + 1), (True, True))
    check("nobody can change their pass number", blocked(p1, "update public.profiles set pass_no = 1 where id = %s", p1), True)
    check("your pass photo can be a photo in your folder", blocked(p1, "update public.profiles set pass_photo = %s where id = %s", f"{p1}/pass-1.jpg", p1), False)
    check("...but not someone else's photo", blocked(p1, "update public.profiles set pass_photo = %s where id = %s", f"{p2}/pass-1.jpg", p1), True)
    check("...and nobody else can change your photo", as_user(p2, "update public.profiles set pass_photo = null where id = %s returning id", p1), [])
    check("tiers: same thresholds as before", [one("select public.pass_tier(%s)", x) for x in (0, 99, 100, 300, 600, 1000, 1499, 1500)],
          ["green", "green", "blue", "black", "dblack", "tblack", "tblack", "rat"])
    sr, gr = user("seasoned", points=840), user("greenie", points=50)
    check("riders can't start a new season", blocked(sr, "select public.start_season('26/27')"), True)
    as_user(creator, "select public.start_season('26/27')")
    check("opening day: double black (840) drops to black (300)", one("select points from public.profiles where id = %s", sr), 300)
    check("...green stays where it was", one("select points from public.profiles where id = %s", gr), 50)
    check("...and last season's pass stays as a trophy", as_user(sr, "select tier, points from public.season_passes where user_id = %s", sr), [("dblack", 840)])
    check("a season can only be closed once", blocked(creator, "select public.start_season('26/27')"), True)
    check("nobody can write trophies by hand", blocked(sr, "insert into public.season_passes (user_id, season, tier, points) values (%s, '30/31', 'rat', 9999)", sr), True)

    print("\n-- Reports on passes + blocking (025) --")
    pic = user("pic")
    as_user(pic, "update public.profiles set pass_photo = %s where id = %s", f"{pic}/pass-1.jpg", pic)
    for r in voters[:2]:
        as_user(r, "insert into public.reports (profile_id, reason) values (%s, 'inappropriate')", pic)
    check("2 reports on a pass photo: it stays", one("select pass_photo from public.profiles where id = %s", pic) is not None, True)
    check("the same rider can't report it twice", blocked(voters[0], "insert into public.reports (profile_id, reason) values (%s, 'spam')", pic), True)
    as_user(voters[2], "insert into public.reports (profile_id, reason) values (%s, 'inappropriate')", pic)
    check("3 reports take the photo down", one("select pass_photo from public.profiles where id = %s", pic), None)
    check("a report is still one thing at a time", blocked(voters[3], "insert into public.reports (profile_id, clip_id, reason) values (%s, %s, 'spam')", pic, target), True)
    bl, bd = user("blocker"), user("blockee")
    q("insert into public.friendships (requester, addressee, status) values (%s, %s, 'accepted')", bl, bd)
    as_user(bl, "select public.block_user(%s)", bd)
    check("blocking ends the friendship", one("select count(*) from public.friendships where requester = %s", bl), 0)
    check("...and they can't send you a request", blocked(bd, "insert into public.friendships (addressee) values (%s)", bl), True)
    check("...or you them, until you unblock", blocked(bl, "insert into public.friendships (addressee) values (%s)", bd), True)
    check("you see who you blocked", len(as_user(bl, "select blocked from public.blocks")), 1)
    check("they can't see that you blocked them", as_user(bd, "select blocked from public.blocks"), [])
    check("blocks only go through block_user", blocked(bd, "insert into public.blocks (blocked) values (%s)", bl), True)
    as_user(bl, "select public.unblock_user(%s)", bd)
    check("unblock, then a request works again", blocked(bl, "insert into public.friendships (addressee) values (%s)", bd), False)

    print("\n-- Founder removes (026) --")
    bad_clip = post(d, "540")
    check("riders can't remove someone's clip", blocked(voters[0], "select public.founder_remove_clip(%s)", bad_clip), True)
    as_user(voters[0], "insert into public.reports (clip_id, reason) values (%s, 'inappropriate')", bad_clip)
    rep = as_user(creator, "select public.founder_reports()")[0][0]
    check("the founder sees reported clips and photos", ({"clip", "photo"} <= {x["kind"] for x in rep}), True)
    check("riders can't see the report list", blocked(voters[0], "select public.founder_reports()"), True)
    path = as_user(creator, "select public.founder_remove_clip(%s)", bad_clip)[0][0]
    check("the founder can remove any clip (and gets the file to delete)", (one("select hidden from public.clips where id = %s", bad_clip), path is None or isinstance(path, str)), (True, True))
    as_user(creator, "select public.founder_keep('clip', %s)", bad_clip)
    check("Keep clears its reports and brings it back", (one("select hidden from public.clips where id = %s", bad_clip),
          one("select count(*) from public.reports where clip_id = %s", bad_clip)), (False, 0))
    as_user(p1, "update public.profiles set pass_photo = %s where id = %s", f"{p1}/pass-2.jpg", p1)
    check("riders can't remove someone's photo", blocked(p2, "select public.founder_remove_photo(%s)", p1), True)
    check("the founder can remove any pass photo", as_user(creator, "select public.founder_remove_photo(%s)", p1)[0][0], f"{p1}/pass-2.jpg")
    check("...and it's gone from the pass", one("select pass_photo from public.profiles where id = %s", p1), None)
    print("\n-- The founder's call settles clips that waited over a day (027) --")
    boss, wannabe, rider27 = user("boss27"), user("wannabe27"), user("rider27")
    check("a rider can't make themselves founder", blocked(wannabe, "update public.profiles set is_founder = true where id = auth.uid()"), True)
    check("...and the column really can't be written", one("select has_column_privilege('authenticated', 'public.profiles', 'is_founder', 'UPDATE')"), False)
    q("update public.profiles set is_founder = true where id = %s", boss)
    old = lambda cid: q("update public.clips set created_at = now() - interval '25 hours' where id = %s", cid)
    fresh = post(rider27, "180")
    check("under 24h, the founder's vote is just one vote", judge(fresh, who=[boss])[0], "pending")
    check("...and the normal rule still decides it", judge(fresh, who=[voters[0]])[0], "verified")
    stale = post(rider27, "360"); old(stale)
    joker = user("joker27")
    judge(stale, landed=False, who=[joker])
    check("queue: an old clip shows up, marked 'your call settles it'",
          [(str(r[0]) == stale, r[6]) for r in as_user(boss, "select * from public.founder_queue()") if str(r[0]) == stale], [(True, True)])
    check("queue: oldest first", [str(r[0]) for r in as_user(boss, "select * from public.founder_queue()")][0], stale)
    check("riders get an empty queue", as_user(wannabe, "select count(*) from public.founder_queue()")[0][0], 0)
    check("over 24h, founder says landed -> verified with normal points", judge(stale, who=[boss]), ("verified", 20))
    check("...the joker who said bailed loses trust", one("select agree from public.judge_stats where user_id = %s", joker), 0)
    check("...and it leaves the queue", any(str(r[0]) == stale for r in as_user(boss, "select * from public.founder_queue()")), False)
    junk = post(rider27, "540"); old(junk)
    check("over 24h, founder says bailed -> rejected", judge(junk, landed=False, who=[boss])[0], "rejected")
    own = post(boss, "180"); old(own)
    check("the founder still can't judge their own clip", blocked(boss, "insert into public.votes (clip_id, landed) values (%s, true)", own), True)
    check("...and it's not in their queue", any(str(r[0]) == own for r in as_user(boss, "select * from public.founder_queue()")), False)

    print("\n-- Crew invite links (028) --")
    cap, mate, drifter = user("cap28"), user("mate28"), user("drifter28")
    as_user(cap, "select public.create_crew('Link Crew', 'LNK')")
    code = one("select code from public.crews where name = 'Link Crew'")
    info = as_user(mate, "select * from public.crew_invite_info(%s)", code.lower())
    check("the link shows who invited you (any case)", info, [("Link Crew", "LNK", 1)])
    check("a wrong code shows nothing", as_user(mate, "select * from public.crew_invite_info('ZZZZZZ')"), [])
    check("signed-out visitors can see who invited them", anon_blocked(f"select * from public.crew_invite_info('{code}')"), False)
    check("signed-out visitors can't join", anon_blocked(f"select public.join_crew_link('{code}')"), True)
    as_user(mate, "select public.join_crew_link(%s)", code)
    crew_of = lambda u: (conn.execute("select c.name from public.crew_members m join public.crews c on c.id = m.crew_id where m.user_id = %s", (u,)).fetchone() or [None])[0]
    check("tapping the link puts you in the crew", crew_of(mate), "Link Crew")
    check("tapping it again is fine", blocked(mate, "select public.join_crew_link(%s)", code), False)
    as_user(drifter, "select public.create_crew('Other Crew', 'OTH')")
    check("in another crew: it asks first", blocked(drifter, "select public.join_crew_link(%s)", code), True)
    check("...and doesn't move you", crew_of(drifter), "Other Crew")
    as_user(drifter, "select public.join_crew_link(%s, true)", code)
    check("say yes and you switch crews", crew_of(drifter), "Link Crew")
    check("...your old crew (just you) is gone", one("select count(*) from public.crews where name = 'Other Crew'"), 0)
    check("a bad link explains itself", blocked(mate, "select public.join_crew_link('ZZZZZZ', true)"), True)
    newbie = str(uuid.uuid4())
    q("insert into auth.users (id, email, raw_user_meta_data) values (%s, 'nb@test', jsonb_build_object('username', 'newbie28', 'crew', %s::text))", newbie, code.lower())
    check("backstop: signing up from the link joins at account creation", crew_of(newbie), "Link Crew")
    oops = str(uuid.uuid4())
    q("insert into auth.users (id, email, raw_user_meta_data) values (%s, 'oops@test', jsonb_build_object('username', 'oops28', 'crew', 'NOPE'))", oops)
    check("...a broken code never blocks sign-up", (one("select count(*) from public.profiles where id = %s", oops), crew_of(oops)), (1, None))

    conn.close()
    print(f"\n{sum(results)}/{len(results)} passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
