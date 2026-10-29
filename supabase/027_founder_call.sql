-- Stomped database, version 27: the founder's call (Connor, Oct 28).
-- Early on there aren't enough riders to judge every clip, so clips can sit for days.
--   1. profiles.is_founder: a flag only this file (or the SQL Editor) can set. Riders can't touch it:
--      001 only lets the app change username and home_resort.
--   2. If a clip has waited MORE than 24 hours, a founder's vote settles it on the spot (landed = verified with
--      the normal points, bailed = rejected). Before 24 hours a founder's vote is just a normal vote, and the
--      usual rule (enough vote weight, 70% landed) decides everything else.
--   3. founder_queue(): every clip that still needs a call, oldest first, for the founder's "Needs a call" list.
--      Anyone else gets an empty list.
-- Judge scores (018) treat the founder's call as the right answer, so jokers who voted against it lose trust.
--
-- BEFORE YOU RUN: put your handle in the line marked >>> below (the username you sign in with, no @).
-- Paste into Supabase > SQL Editor and click Run. No clips change until a founder votes.

-- ---------- 1. the flag ----------
alter table public.profiles add column if not exists is_founder boolean not null default false;

-- >>> Connor: replace YOUR_HANDLE with your username, keep the quotes.
update public.profiles set is_founder = true where lower(username) = lower('YOUR_HANDLE');

-- ---------- 2. the founder settles clips that waited over a day ----------
-- Same as 018, plus the founder check marked below.
create or replace function public.resolve_clip() returns trigger
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
  select * into c from public.clips where id = new.clip_id for update;
  if c.status <> 'pending' then return new; end if;

  -- NEW (027): a founder's call settles a clip that has waited more than 24 hours
  select case when bool_and(v.landed) then true when not bool_or(v.landed) then false end
    into f_call
    from public.votes v join public.profiles p on p.id = v.voter_id
   where v.clip_id = c.id and p.is_founder;

  if f_call is not null and c.created_at < now() - interval '24 hours' then
    is_landed := f_call;
  else
    select coalesce(sum(vote_weight(p.points) * public.judge_trust(p.id) * (v.landed)::int), 0),
           coalesce(sum(vote_weight(p.points) * public.judge_trust(p.id)), 0)
      into yes_w, total_w
      from public.votes v join public.profiles p on p.id = v.voter_id
     where v.clip_id = c.id;

    if total_w < public.need_weight() then return new; end if;
    -- Split vote (between 30% and 70% landed)? Wait for more judges, so one joker can't sink a clip.
    -- After 6 weight of votes it's decided anyway, by the same 70% rule.
    if yes_w / total_w > 0.3 and yes_w / total_w < 0.7 and total_w < 6 then return new; end if;
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
  return new;
end $$;

-- ---------- 3. the "Needs a call" list ----------
-- Clips the founder can still vote on (same limits as the vote rule in 017: not your own, not one you filmed,
-- not hidden, not waiting on its rider), oldest first. settles = your vote decides it right away.
create or replace function public.founder_queue()
returns table (clip_id uuid, rider text, trick text, grab text, created_at timestamptz, votes int, settles boolean)
language sql stable security definer set search_path = public as $$
  select c.id, p.username, t.name, c.grab, c.created_at,
         (select count(*)::int from public.votes v where v.clip_id = c.id),
         c.created_at < now() - interval '24 hours'
    from public.clips c
    join public.profiles p on p.id = c.user_id
    left join public.tricks t on t.id = c.trick_id
   where coalesce((select f.is_founder from public.profiles f where f.id = auth.uid()), false)
     and c.status = 'pending' and c.rider_ok and not c.hidden
     and c.user_id <> auth.uid() and c.filmed_by is distinct from auth.uid()
     and not exists (select 1 from public.votes v where v.clip_id = c.id and v.voter_id = auth.uid())
   order by c.created_at
   limit 100
$$;
revoke execute on function public.founder_queue() from public, anon;
grant execute on function public.founder_queue() to authenticated;

-- Check: should read  1 | f | 1
-- (founders = 1 once YOUR_HANDLE is filled in; 0 means the handle didn't match a username)
select (select count(*) from public.profiles where is_founder) as founders,
       has_column_privilege('authenticated', 'public.profiles', 'is_founder', 'UPDATE') as riders_can_set_it,
       (select count(*) from pg_proc where proname = 'founder_queue') as queue;
