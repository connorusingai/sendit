-- Stomped database, version 22: the trick AI's guess on each clip (Oct 28).
-- The filming phone looks at the video right after recording and writes ONE guess per clip:
-- how far the rider spun, flat/cork/flip, landed or not, and how sure it is. Judges see it as a hint.
-- It never changes points or votes: riders still decide. Rails are skipped (the AI can't read them yet).
-- Only the clip's own rider or filmer can add the guess, once, and nobody can edit it afterwards.
-- founder_ai_stats() is rider #001's scorecard: how often the AI agreed with what riders verified.
-- Paste into Supabase > SQL Editor and click Run, after 021. No existing data is changed.

create table if not exists public.clip_ai (
  clip_id  uuid primary key references public.clips on delete cascade,
  spin     int check (spin between 0 and 2160 and spin % 180 = 0),   -- null = can't tell
  axis     text check (axis in ('flat','off-axis','flip')),
  landed   boolean,                                                  -- null = can't tell
  sure     real not null default 0 check (sure between 0 and 1),
  note     text check (char_length(note) <= 60),                     -- why it can't tell, in plain words
  seen     real check (seen between 0 and 1),                        -- share of frames the rider was tracked
  ver      text not null default 'web-0.5' check (char_length(ver) <= 16),
  at       timestamptz not null default now()
);

alter table public.clip_ai enable row level security;
-- You can see the AI's guess on any clip you can see
drop policy if exists "read the AI guess on clips you can see" on public.clip_ai;
create policy "read the AI guess on clips you can see" on public.clip_ai for select
  using (exists (select 1 from public.clips c where c.id = clip_id));
-- Only the clip's rider or filmer adds it, and only on a clip that's still waiting for votes
drop policy if exists "add the AI guess to your own clip" on public.clip_ai;
create policy "add the AI guess to your own clip" on public.clip_ai for insert to authenticated
  with check (exists (select 1 from public.clips c where c.id = clip_id and c.status = 'pending'
                      and (c.user_id = auth.uid() or c.filmed_by = auth.uid())));
revoke all on public.clip_ai from anon;
revoke update, delete on public.clip_ai from authenticated;
grant select, insert on public.clip_ai to authenticated;
grant select on public.clip_ai to anon;

-- Rider #001's AI scorecard: on clips riders have decided, how often was the AI right?
create or replace function public.founder_ai_stats() returns jsonb
language plpgsql stable security definer set search_path = public as $$
declare
  creator constant uuid := '713e0c5f-7de1-4842-b845-d1679b4eb7b3';
begin
  if auth.uid() is distinct from creator then raise exception 'Founder only'; end if;
  return (with d as (
      select a.*, c.status, t.category,
             coalesce(substring(t.name from '(\d{3,4})')::int,
                      case when t.name ilike '%flip%' then 360 end) as want
      from public.clip_ai a join public.clips c on c.id = a.clip_id join public.tricks t on t.id = c.trick_id
      where c.status in ('verified','rejected'))
    select jsonb_build_object(
      'guessed', (select count(*) from public.clip_ai),
      'decided', (select count(*) from d),
      'landed_calls', (select count(*) from d where landed is not null),
      'landed_right', (select count(*) from d where landed = (status = 'verified')),
      'spin_calls', (select count(*) from d where spin is not null and want is not null and status = 'verified'),
      'spin_right', (select count(*) from d where spin = want and status = 'verified'),
      'cant_tell', (select count(*) from d where spin is null and landed is null)));
end $$;
revoke execute on function public.founder_ai_stats() from public, anon;
grant execute on function public.founder_ai_stats() to authenticated;

-- Check: should read  t | t | 1
select to_regclass('public.clip_ai') is not null as ai_table,
       (select relrowsecurity from pg_class where oid = 'public.clip_ai'::regclass) as locked,
       (select count(*) from pg_proc where proname = 'founder_ai_stats') as scorecard;
