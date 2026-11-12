-- Stomped database, version 30: fake accounts can't decide anything (Connor's decision, Nov 11).
-- NOT pasted yet: Connor pastes it in the Supabase SQL Editor, AFTER 029.
-- Sign-up stays instant (no email check). Instead:
--   1. A brand-new account's calls don't count until it has posted a clip or made 3 calls (its first 3 calls are
--      saved, and start counting the moment the 3rd one lands). Then they count a QUARTER until the account is
--      7 days old. After that they count fully. (023 was: half, for one day.)
--   2. Reports: 5 a day per rider. Something is hidden at 3 reports only if at least 2 of the reporters'
--      accounts are over 3 days old. Once the founder taps Keep on a clip or comment, reports can't hide it again.
--   3. Blocking now reaches the database: a rider you blocked can still tap Landed/Bailed on your clip, but their
--      call counts for nothing, and a comment they write on your clip is only ever visible to them. They are
--      never told, so there is nothing to argue with.
--   4. calls_left(): how many more calls a clip needs, for the judge screen ("needs 2 more calls").
--   5. Votes needed stays pinned at 2 (the number that is live). A never-merged change wanted 3; with new accounts
--      at a quarter that would mean 12 new-rider calls per clip.
-- Paste into Supabase > SQL Editor and click Run. No clips, points or votes change. Safe to run twice.

-- ---------- 0. the numbers (change one line, run that line) ----------
create or replace function public.need_weight() returns numeric
language sql immutable as $$ select 2::numeric $$;          -- vote weight that decides a clip
create or replace function public.new_account_days() returns int
language sql immutable as $$ select 7 $$;                   -- how long an account counts as new
create or replace function public.new_account_weight() returns numeric
language sql immutable as $$ select 0.25::numeric $$;       -- what a new account's call is worth
create or replace function public.warmup_calls() returns int
language sql immutable as $$ select 3 $$;                   -- calls before your calls count (or post one clip)
create or replace function public.reports_per_day() returns int
language sql immutable as $$ select 5 $$;
create or replace function public.reporter_min_days() returns int
language sql immutable as $$ select 3 $$;                   -- a reporter this old is "established"
create or replace function public.established_reporters_needed() returns int
language sql immutable as $$ select 2 $$;

-- ---------- 1. calls count only once you've posted or made 3 calls, then a quarter for 7 days ----------
-- "Counts yet?" lives in judge_stats (018), the table no rider can read, so nobody can watch their alts warm up.
alter table public.judge_stats add column if not exists active_at timestamptz;

-- Riders who already posted or made 3 calls keep counting.
insert into public.judge_stats as s (user_id, active_at)
select p.id, now() from public.profiles p
 where exists (select 1 from public.clips c where (c.user_id = p.id and c.filmed_by is null) or c.filmed_by = p.id)
    or (select count(*) from public.votes v where v.voter_id = p.id) >= public.warmup_calls()
on conflict (user_id) do update set active_at = now() where s.active_at is null;

-- 0 until the account has posted or made 3 calls, 0.25 while it is under 7 days old, then 1. Founders always 1.
create or replace function public.new_account_factor(p_user uuid) returns numeric
language sql stable security definer set search_path = public as $$
  select case
    when coalesce((select is_founder from public.profiles where id = p_user), false) then 1
    when (select active_at from public.judge_stats where user_id = p_user) is null then 0
    when (select created_at from public.profiles where id = p_user) > now() - make_interval(days => public.new_account_days())
      then public.new_account_weight()
    else 1 end
$$;
revoke execute on function public.new_account_factor(uuid) from public, anon, authenticated;

-- The weight of the calls on one clip: landed weight and total weight.
-- Rank weight (008) x judge score (018) x new-account factor (above); a rider the clip's owner blocked counts 0.
create or replace function public.clip_weight(p_clip uuid, out yes_w numeric, out total_w numeric)
language sql stable security definer set search_path = public as $$
  select coalesce(sum(x.w * (x.landed)::int), 0), coalesce(sum(x.w), 0)
    from (select v.landed, public.vote_weight(p.points) * public.judge_trust(p.id) as w
            from public.votes v
            join public.profiles p on p.id = v.voter_id
            join public.clips c on c.id = v.clip_id
           where v.clip_id = p_clip
             and not exists (select 1 from public.blocks b where b.blocker = c.user_id and b.blocked = v.voter_id)) x
$$;
revoke execute on function public.clip_weight(uuid) from public, anon, authenticated;

-- Decide one clip if it has enough calls. The same rules as 027's resolve_clip(), moved here so a clip can be
-- looked at again when a new rider's earlier calls start counting. The only change is where the weights come from.
create or replace function public.settle_clip(p_clip uuid) returns void
language plpgsql security definer set search_path = public as $$
declare
  yes_w     numeric;
  total_w   numeric;
  c         public.clips%rowtype;
  base      numeric;
  extra     numeric;
  totd_x    numeric;
  award     int;
  has_trick boolean;
  has_grab  boolean;
  f_call    boolean;   -- what the founder(s) said: true/false, or null if no founder voted (or founders disagree)
  is_landed boolean;
begin
  select * into c from public.clips where id = p_clip for update;
  if not found or c.status <> 'pending' then return; end if;

  -- a founder's call settles a clip that has waited more than 24 hours (027)
  select case when bool_and(v.landed) then true when not bool_or(v.landed) then false end
    into f_call
    from public.votes v join public.profiles p on p.id = v.voter_id
   where v.clip_id = c.id and p.is_founder;

  if f_call is not null and c.created_at < now() - interval '24 hours' then
    is_landed := f_call;
  else
    select w.yes_w, w.total_w into yes_w, total_w from public.clip_weight(c.id) w;   -- NEW (030)
    if total_w < public.need_weight() then return; end if;
    -- Split vote (between 30% and 70% landed)? Wait for more judges, so one joker can't sink a clip.
    -- After 6 weight of votes it's decided anyway, by the same 70% rule.
    if yes_w / total_w > 0.3 and yes_w / total_w < 0.7 and total_w < 6 then return; end if;
    is_landed := yes_w / total_w >= 0.7;
  end if;

  if is_landed then
    select t.pts into base from public.tricks t where t.id = c.trick_id;
    totd_x := case when c.totd then 2 else 1 end;

    select exists (select 1 from public.clips where user_id = c.user_id and trick_id = c.trick_id
                     and status = 'verified' and id <> c.id),
           exists (select 1 from public.clips where user_id = c.user_id and trick_id = c.trick_id
                     and grab = c.grab and status = 'verified' and id <> c.id)
      into has_trick, has_grab;

    if not has_trick then
      award := round(base * case when c.grab <> 'No grab' then 1.2 else 1 end * totd_x);
    elsif c.grab <> 'No grab' and not has_grab then
      award := round(base * 0.2 * totd_x);
    elsif c.totd and not exists (
        select 1 from public.clips x
         where x.user_id = c.user_id and x.trick_id = c.trick_id and x.totd and x.status = 'verified'
           and x.points_awarded > 0 and x.id <> c.id
           and (x.created_at at time zone 'America/Denver')::date = (c.created_at at time zone 'America/Denver')::date) then
      award := round(base);
    else
      award := 0;
    end if;

    -- Combo bonus: a chain you haven't been verified on before pays half the points of the added tricks.
    if cardinality(c.combo) > 0 and not exists (
        select 1 from public.clips where user_id = c.user_id and trick_id = c.trick_id and combo = c.combo
           and status = 'verified' and id <> c.id) then
      select coalesce(sum(t.pts), 0) into extra from public.tricks t where t.id = any(c.combo);
      award := award + round(extra * 0.5 * totd_x);
    end if;

    update public.clips set status = 'verified', points_awarded = award, verified_at = now() where id = c.id;
    update public.profiles set points = points + award where id = c.user_id;
  else
    update public.clips set status = 'rejected' where id = c.id;
  end if;
end $$;
revoke execute on function public.settle_clip(uuid) from public, anon, authenticated;

-- A rider's calls start counting: mark them, then look again at every clip they already called.
create or replace function public.activate_judge(p_user uuid) returns void
language plpgsql security definer set search_path = public as $$
declare r record;
begin
  insert into public.judge_stats as s (user_id, active_at) values (p_user, now())
  on conflict (user_id) do update set active_at = now() where s.active_at is null;
  if not found then return; end if;   -- they already counted
  for r in select v.clip_id from public.votes v join public.clips c on c.id = v.clip_id
            where v.voter_id = p_user and c.status = 'pending' order by c.created_at loop
    perform public.settle_clip(r.clip_id);
  end loop;
end $$;
revoke execute on function public.activate_judge(uuid) from public, anon, authenticated;

-- After every vote (the trigger from 001 keeps calling this): your 3rd call switches your calls on, then the clip is decided.
create or replace function public.resolve_clip() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if (select count(*) from public.votes where voter_id = new.voter_id) >= public.warmup_calls() then
    perform public.activate_judge(new.voter_id);
  end if;
  perform public.settle_clip(new.clip_id);
  return new;
end $$;

-- Posting a clip switches your calls on too (for Film a friend, that's the rider who filmed it).
create or replace function public.judge_after_post() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  perform public.activate_judge(coalesce(new.filmed_by, new.user_id));
  return new;
end $$;
revoke execute on function public.judge_after_post() from public, anon, authenticated;
drop trigger if exists judge_after_post on public.clips;
create trigger judge_after_post after insert on public.clips
  for each row execute function public.judge_after_post();

-- ---------- 2. reports: 5 a day, and fresh accounts alone can't hide anything ----------
create or replace function public.limit_reports() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if coalesce((select is_founder from public.profiles where id = new.reporter), false) then return new; end if;
  if (select count(*) from public.reports
       where reporter = new.reporter and created_at > now() - interval '1 day') >= public.reports_per_day() then
    raise exception 'That is % reports today, which is the limit. If something is still wrong, tell us in Send feedback.', public.reports_per_day();
  end if;
  return new;
end $$;
revoke execute on function public.limit_reports() from public, anon, authenticated;
drop trigger if exists limit_reports on public.reports;
create trigger limit_reports before insert on public.reports
  for each row execute function public.limit_reports();

-- 3 reports, and at least 2 of the reporters are over 3 days old (replaces 023's "new accounts count half")
create or replace function public.enough_reports(p_clip uuid, p_comment uuid, p_profile uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select count(*) >= public.reports_needed()
     and count(*) filter (where p.created_at <= now() - make_interval(days => public.reporter_min_days()))
           >= public.established_reporters_needed()
    from public.reports r join public.profiles p on p.id = r.reporter
   where (p_clip    is not null and r.clip_id    = p_clip)
      or (p_comment is not null and r.comment_id = p_comment)
      or (p_profile is not null and r.profile_id = p_profile)
$$;
revoke execute on function public.enough_reports(uuid, uuid, uuid) from public, anon, authenticated;

-- "kept" = the founder looked and said it's fine. Riders can't set it (001 and 011 lock updates).
alter table public.clips    add column if not exists kept boolean not null default false;
alter table public.comments add column if not exists kept boolean not null default false;

create or replace function public.hide_reported() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if new.clip_id is not null then
    if public.enough_reports(new.clip_id, null, null) then
      update public.clips set hidden = true where id = new.clip_id and not kept;
    end if;
  elsif new.comment_id is not null then
    if public.enough_reports(null, new.comment_id, null) then
      update public.comments set hidden = true where id = new.comment_id and not kept;
    end if;
  else
    -- A reported pass loses its photo (the file stays for the founder to look at, then remove or restore)
    if public.enough_reports(null, null, new.profile_id) then
      update public.profiles set pass_photo = null where id = new.profile_id;
    end if;
  end if;
  return new;
end $$;

-- Keep (026), plus: it stays kept.
create or replace function public.founder_keep(p_kind text, p_id uuid) returns void
language plpgsql security definer set search_path = public as $$
begin
  if not public.am_founder() then raise exception 'Founder only'; end if;
  if p_kind = 'clip' then
    delete from public.reports where clip_id = p_id;
    update public.clips set hidden = false, kept = true where id = p_id;
  elsif p_kind = 'comment' then
    delete from public.reports where comment_id = p_id;
    update public.comments set hidden = false, kept = true where id = p_id;
  elsif p_kind = 'photo' then
    delete from public.reports where profile_id = p_id;
  else raise exception 'Unknown kind'; end if;
end $$;
revoke execute on function public.founder_keep(text, uuid) from public, anon;
grant execute on function public.founder_keep(text, uuid) to authenticated;

-- ---------- 3. blocking reaches comments (votes are handled in clip_weight above) ----------
-- A blocked rider's comment on the blocker's clip is saved hidden: they still see it, nobody else ever does.
create or replace function public.hide_blocked_comment() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if exists (select 1 from public.blocks b join public.clips c on c.user_id = b.blocker
              where c.id = new.clip_id and b.blocked = new.user_id) then
    new.hidden := true;
  end if;
  return new;
end $$;
revoke execute on function public.hide_blocked_comment() from public, anon, authenticated;
drop trigger if exists hide_blocked_comment on public.comments;
create trigger hide_blocked_comment before insert on public.comments
  for each row execute function public.hide_blocked_comment();

-- ---------- 4. how many more calls a clip needs ----------
-- One number per clip that is still being judged, counted in normal (full-weight) calls and never below 1.
-- Not enough weight yet: what's missing. Enough weight but a split vote: the fewest calls that could settle it.
create or replace function public.calls_left(p_clips uuid[]) returns table (clip_id uuid, calls_left int)
language plpgsql stable security definer set search_path = public as $$
declare
  c    record;
  y    numeric;
  t    numeric;
  need numeric := public.need_weight();
begin
  if auth.uid() is null then return; end if;
  for c in select cl.id from public.clips cl
            where cl.id = any(p_clips[1:200]) and cl.status = 'pending' and not cl.hidden
              and (cl.rider_ok or cl.user_id = auth.uid()) loop
    select w.yes_w, w.total_w into y, t from public.clip_weight(c.id) w;
    clip_id := c.id;
    calls_left := greatest(1, case
      when t < need then ceil(need - t)
      else least(ceil((0.7 * t - y) / 0.3), ceil(y / 0.3 - t), ceil(6 - t)) end)::int;
    return next;
  end loop;
end $$;
revoke execute on function public.calls_left(uuid[]) from public, anon;
grant execute on function public.calls_left(uuid[]) to authenticated;

-- Check: should read  2 | 0.25 | 1 | 1 | 1 | t
-- (riders_counting = how many riders' calls count today; it should be most of your riders, not 0)
select public.need_weight() as votes_needed, public.new_account_weight() as new_account_counts,
       (select count(*) from pg_trigger where tgname = 'limit_reports')        as report_limit,
       (select count(*) from pg_trigger where tgname = 'hide_blocked_comment') as blocked_comments,
       (select count(*) from pg_proc where proname = 'calls_left')             as calls_left_ready,
       (select count(*) from public.judge_stats where active_at is not null) > 0 as riders_counting;
