-- Stomped database, version 31: the founder's vouch, and a 72-hour clock on Game of S.K.I. turns.
-- Paste into Supabase > SQL Editor and click Run, after 030. Safe to run twice. No existing data is changed.
--
-- 1. Vouch. Under 030 a new account's calls count 0 until it posts or makes 3 calls, then a quarter until it is
--    7 days old. If 20 riders join in the same week that is 8 of their calls per clip. The founder can vouch for a
--    rider they know in real life: their calls count fully from that moment, and clips they already called are
--    looked at again. Only the founder can vouch, and vouching can be undone. Fake accounts never get vouched.
-- 2. S.K.I. clock. FEATURES.md says each turn has 72 hours. Nothing ends by itself (weekend riders don't lose a
--    game while they're in class): once the other rider's turn has waited 72 hours, the rider waiting on them
--    can claim the win. If nobody ever moved (the challenger never set a first trick), it is cancelled instead,
--    with no rating change.

-- ---------- knobs: change one number, paste again ----------
create or replace function public.duel_turn_hours() returns int
language sql immutable as $$ select 72 $$;

-- ---------- 1. vouch ----------
-- In judge_stats (018), the table no rider can read, so nobody can see who is vouched.
alter table public.judge_stats add column if not exists vouched_at timestamptz;

-- Same as 030, plus: vouched riders count fully from the start.
create or replace function public.new_account_factor(p_user uuid) returns numeric
language sql stable security definer set search_path = public as $$
  select case
    when coalesce((select is_founder from public.profiles where id = p_user), false) then 1
    when (select vouched_at from public.judge_stats where user_id = p_user) is not null then 1
    when (select active_at from public.judge_stats where user_id = p_user) is null then 0
    when (select created_at from public.profiles where id = p_user) > now() - make_interval(days => public.new_account_days())
      then public.new_account_weight()
    else 1 end
$$;
revoke execute on function public.new_account_factor(uuid) from public, anon, authenticated;

create or replace function public.vouch(p_user uuid, p_on boolean default true) returns void
language plpgsql security definer set search_path = public as $$
declare r record;
begin
  if not public.am_founder() then raise exception 'Founder only'; end if;
  if not exists (select 1 from public.profiles where id = p_user) then raise exception 'Rider not found'; end if;
  insert into public.judge_stats as s (user_id, vouched_at) values (p_user, case when p_on then now() end)
  on conflict (user_id) do update set vouched_at = case when p_on then coalesce(s.vouched_at, now()) end;
  if not p_on then return; end if;
  -- their calls on clips still waiting count fully now
  for r in select v.clip_id from public.votes v join public.clips c on c.id = v.clip_id
            where v.voter_id = p_user and c.status = 'pending' order by c.created_at loop
    perform public.settle_clip(r.clip_id);
  end loop;
end $$;
revoke execute on function public.vouch(uuid, boolean) from public, anon;
grant execute on function public.vouch(uuid, boolean) to authenticated;

-- Founder dashboard: riders under 7 days old, and how much their calls count right now.
create or replace function public.founder_new_riders()
returns table (id uuid, username text, joined timestamptz, vouched boolean, counts numeric)
language plpgsql stable security definer set search_path = public as $$
begin
  if not public.am_founder() then raise exception 'Founder only'; end if;
  return query
    select p.id, p.username, p.created_at, s.vouched_at is not null, public.new_account_factor(p.id)
      from public.profiles p left join public.judge_stats s on s.user_id = p.id
     where not coalesce(p.is_founder, false)
       and p.created_at > now() - make_interval(days => public.new_account_days())
     order by p.created_at desc
     limit 60;
end $$;
revoke execute on function public.founder_new_riders() from public, anon;
grant execute on function public.founder_new_riders() to authenticated;

-- ---------- 2. S.K.I. clock ----------
alter table public.duels add column if not exists timed_out boolean not null default false;

create or replace function public.claim_duel(p_duel uuid) returns text
language plpgsql security definer set search_path = public as $$
declare
  me uuid := auth.uid();
  d  public.duels%rowtype;
begin
  select * into d from public.duels where id = p_duel for update;
  if not found or me is null or me not in (d.challenger, d.opponent) then raise exception 'Duel not found'; end if;
  if d.status <> 'active' then raise exception 'This duel is over'; end if;
  if d.turn = me then raise exception 'It''s your turn'; end if;
  if d.updated_at > now() - make_interval(hours => public.duel_turn_hours()) then
    raise exception 'They still have time to move';
  end if;
  if not exists (select 1 from public.duel_moves where duel_id = d.id) then
    -- nobody ever moved: no winner, no rating change
    update public.duels set status = 'done', turn = null, trick_id = null, rating_change = 0,
           timed_out = true, updated_at = now() where id = d.id;
    return 'cancelled';
  end if;
  perform public.end_duel(d.id, me, d.turn);
  update public.duels set timed_out = true where id = d.id;
  return 'won';
end $$;
revoke execute on function public.claim_duel(uuid) from public, anon;
grant execute on function public.claim_duel(uuid) to authenticated;

-- Check: should read  72 | t | t | 3
select public.duel_turn_hours() as hours_per_turn,
       exists (select 1 from information_schema.columns where table_name = 'judge_stats' and column_name = 'vouched_at') as has_vouch,
       exists (select 1 from information_schema.columns where table_name = 'duels' and column_name = 'timed_out') as has_clock,
       (select count(*) from pg_proc where proname in ('vouch', 'founder_new_riders', 'claim_duel')) as new_functions_of_3;
