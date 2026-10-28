-- Stomped database, version 23: fake accounts can't cheat (Oct 28).
-- Sign-up stays instant (no email check, Connor's call). Instead, for its first 24 hours a new account's
-- votes and reports count HALF. So 2 throwaway accounts can no longer verify your own clip, and 3 can no
-- longer hide someone's. Real new riders barely notice: after a day they count fully.
-- Paste into Supabase > SQL Editor and click Run. No existing data is changed.

-- 1 for accounts older than a day, 0.5 for brand-new ones
create or replace function public.new_account_factor(p_user uuid) returns numeric
language sql stable security definer set search_path = public as $$
  select case when (select created_at from public.profiles where id = p_user) > now() - interval '24 hours'
              then 0.5 else 1 end
$$;
revoke execute on function public.new_account_factor(uuid) from public, anon, authenticated;

-- Votes: judge trust (018) now also halves for a new account. resolve_clip() already multiplies by it.
create or replace function public.judge_trust(p_user uuid) returns numeric
language sql stable security definer set search_path = public as $$
  select coalesce((select power((agree + 3)::numeric / (total + 3), 2) from public.judge_stats where user_id = p_user), 1)
         * public.new_account_factor(p_user)
$$;
revoke execute on function public.judge_trust(uuid) from public, anon, authenticated;

-- Reports: hide at 3 report WEIGHT instead of 3 reports (011), with new accounts counting half
create or replace function public.hide_reported() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if new.clip_id is not null then
    if (select coalesce(sum(public.new_account_factor(reporter)), 0) from public.reports where clip_id = new.clip_id)
         >= public.reports_needed() then
      update public.clips set hidden = true where id = new.clip_id;
    end if;
  else
    if (select coalesce(sum(public.new_account_factor(reporter)), 0) from public.reports where comment_id = new.comment_id)
         >= public.reports_needed() then
      update public.comments set hidden = true where id = new.comment_id;
    end if;
  end if;
  return new;
end $$;

-- Check: should read  1 | 0.5
select public.new_account_factor((select id from public.profiles order by created_at limit 1)) as oldest_rider,
       0.5 as new_rider_counts;
