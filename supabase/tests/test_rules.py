r"""Play out Sendit's database rules on a throwaway Postgres, before touching the real one.

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
    check("4 votes is not enough weight to decide", judge(clip, who=voters[:4])[0], "pending")
    legend = user("legend", points=1500)
    check("a Legend vote (x2.25) tips it over 5", judge(clip, who=[legend])[0], "verified")

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
    check("switch + rail tricks loaded (ski)", one("select count(*) from public.tricks where sport = 'ski'"), 37)
    check("switch + rail tricks loaded (snowboard)", one("select count(*) from public.tricks where sport = 'snowboard'"), 40)
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

    conn.close()
    print(f"\n{sum(results)}/{len(results)} passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
