-- Stomped database, version 18: judge score (Connor, Oct 27). Friends were voting "bailed" on clips as a joke.
--   1. Every judge has a hidden score: how often their vote matched the final result. Nobody can see it.
--      Trust = ((matches + 3) / (votes + 3))^2, so a new judge starts at 1 and a judge who keeps voting against
--      everyone ends up with votes worth almost nothing. (4 wrong out of 4 = 0.18 of a vote.)
--   2. Split votes (between 30% and 70% landed) wait for more judges instead of rejecting, so a joker gets
--      outvoted (and their score drops) instead of deciding the clip. After 6 weight of votes it's decided anyway.
-- Paste into Supabase > SQL Editor and click Run. Fills in scores from the votes already cast. No clips change.

-- ---------- 1. the hidden score ----------
create table if not exists public.judge_stats (
  user_id uuid primary key references public.profiles on delete cascade,
  agree   int not null default 0,   -- votes that matched how the clip ended up
  total   int not null default 0    -- votes on clips that have been decided
);
alter table public.judge_stats enable row level security;   -- no policies: nobody can read or write it from the app
revoke all on public.judge_stats from anon, authenticated;

create or replace function public.judge_trust(p_user uuid) returns numeric
language sql stable security definer set search_path = public as $$
  select coalesce((select power((agree + 3)::numeric / (total + 3), 2) from public.judge_stats where user_id = p_user), 1)
$$;
revoke execute on function public.judge_trust(uuid) from public, anon, authenticated;

-- When a clip is decided, every judge who voted on it gets +1 vote, and +1 match if they called it right.
create or replace function public.score_judges() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.judge_stats as s (user_id, agree, total)
  select v.voter_id, (v.landed = (new.status = 'verified'))::int, 1
    from public.votes v where v.clip_id = new.id
  on conflict (user_id) do update set agree = s.agree + excluded.agree, total = s.total + 1;
  return new;
end $$;
drop trigger if exists score_judges on public.clips;
create trigger score_judges after update of status on public.clips
  for each row when (old.status = 'pending' and new.status in ('verified', 'rejected'))
  execute function public.score_judges();

-- Scores from the votes already cast (only fills in judges who have no score yet, so running this twice is safe).
insert into public.judge_stats (user_id, agree, total)
select v.voter_id, sum((v.landed = (c.status = 'verified'))::int), count(*)
  from public.votes v join public.clips c on c.id = v.clip_id
 where c.status in ('verified', 'rejected')
 group by v.voter_id
on conflict (user_id) do nothing;

-- ---------- 2. verify with the score, and wait on split votes ----------
-- Same rules as 014, with two changes marked in the vote count and right after need_weight().
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
begin
  select * into c from public.clips where id = new.clip_id for update;
  if c.status <> 'pending' then return new; end if;

  select coalesce(sum(vote_weight(p.points) * public.judge_trust(p.id) * (v.landed)::int), 0),
         coalesce(sum(vote_weight(p.points) * public.judge_trust(p.id)), 0)
    into yes_w, total_w
    from public.votes v join public.profiles p on p.id = v.voter_id
   where v.clip_id = c.id;

  if total_w < public.need_weight() then return new; end if;
  -- Split vote (between 30% and 70% landed)? Wait for more judges, so one joker can't sink a clip.
  -- After 6 weight of votes it's decided anyway, by the same 70% rule.
  if yes_w / total_w > 0.3 and yes_w / total_w < 0.7 and total_w < 6 then return new; end if;

  if yes_w / total_w >= 0.7 then
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

-- Check: should read  t | 1
select exists (select 1 from pg_trigger where tgname = 'score_judges') as scoring_on,
       public.judge_trust('00000000-0000-0000-0000-000000000000') as new_judge_trust;
