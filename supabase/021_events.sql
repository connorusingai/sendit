-- Stomped database, version 21: a small event log + the Founder dashboard (Oct 28).
-- The app writes one row when a signed-in rider does something worth counting (opens a tab, starts
-- recording, posts, votes, shares an invite...). Only the event name and a short detail like the tab
-- name: never what anyone types, never video, never location.
-- Riders can only ADD their own events; nobody can read them from the app. The one way to read them
-- is founder_stats(), which only answers rider #001 (Connor) and returns counts for his dashboard.
-- Deleting your account deletes your events (cascade).
-- Paste into Supabase > SQL Editor and click Run. No existing data is changed.

create table if not exists public.events (
  id      bigint generated always as identity primary key,
  user_id uuid not null default auth.uid() references auth.users on delete cascade,
  name    text not null check (name ~ '^[a-z_]{2,32}$'),
  detail  text check (char_length(detail) <= 40),
  at      timestamptz not null default now()
);
create index if not exists events_at_idx on public.events (at desc);
create index if not exists events_user_idx on public.events (user_id, at desc);

alter table public.events enable row level security;
drop policy if exists "add your own events" on public.events;
create policy "add your own events" on public.events
  for insert to authenticated with check (user_id = auth.uid());
-- no select / update / delete policies: the app can't read or change the log
revoke all on public.events from anon;
revoke select, update, delete on public.events from authenticated;
grant insert on public.events to authenticated;

-- A buggy or spammy phone can't flood it: 120 events a minute per rider, then quietly dropped.
create or replace function public.events_rate_limit() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if (select count(*) from public.events where user_id = new.user_id and at > now() - interval '1 minute') >= 120 then
    return null;
  end if;
  return new;
end $$;
drop trigger if exists events_rate_limit on public.events;
create trigger events_rate_limit before insert on public.events
  for each row execute function public.events_rate_limit();

-- The Founder dashboard. Only rider #001 gets an answer; everyone else gets an error.
create or replace function public.founder_stats() returns jsonb
language plpgsql stable security definer set search_path = public, auth as $$
declare
  creator constant uuid := '713e0c5f-7de1-4842-b845-d1679b4eb7b3';
begin
  if auth.uid() is distinct from creator then raise exception 'Founder only'; end if;
  return jsonb_build_object(
    'riders', (select count(*) from public.profiles),
    'new_7d', (select count(*) from public.profiles where created_at > now() - interval '7 days'),
    'active_1d', (select count(distinct user_id) from public.events where at > now() - interval '1 day'),
    'active_7d', (select count(distinct user_id) from public.events where at > now() - interval '7 days'),
    'signups_by_day', (select coalesce(jsonb_agg(jsonb_build_object('day', d, 'n', n) order by d), '[]') from (
        select (created_at at time zone 'America/Denver')::date as d, count(*) as n from public.profiles
        where created_at > now() - interval '14 days' group by 1) s),
    'by_src', (select coalesce(jsonb_agg(jsonb_build_object('src', src, 'n', n) order by n desc), '[]') from (
        select coalesce(nullif(u.raw_user_meta_data->>'src', ''), 'direct') as src, count(*) as n
        from auth.users u join public.profiles p on p.id = u.id group by 1) s),
    'funnel', jsonb_build_object(
        'signed_up', (select count(*) from public.profiles),
        'set_up', (select count(*) from public.profiles where home_resort is not null),
        'filmed', (select count(distinct user_id) from public.events where name = 'record_start'),
        'posted', (select count(distinct user_id) from public.clips),
        'judged', (select count(distinct voter_id) from public.votes),
        'friended', (select count(distinct x) from (
                      select requester as x from public.friendships where status = 'accepted'
                      union all select addressee from public.friendships where status = 'accepted') f)),
    'top_events_7d', (select coalesce(jsonb_agg(jsonb_build_object('name', k, 'n', n) order by n desc), '[]') from (
        select name || coalesce(':' || detail, '') as k, count(*) as n from public.events
        where at > now() - interval '7 days' group by 1 order by 2 desc limit 15) s),
    'riders_list', (select coalesce(jsonb_agg(r order by r->>'joined' desc), '[]') from (
        select jsonb_build_object('username', p.username, 'joined', p.created_at,
          'src', coalesce(nullif(u.raw_user_meta_data->>'src', ''), 'direct'),
          'last_seen', (select max(at) from public.events e where e.user_id = p.id),
          'events', (select count(*) from public.events e where e.user_id = p.id),
          'clips', (select count(*) from public.clips c where c.user_id = p.id),
          'votes', (select count(*) from public.votes v where v.voter_id = p.id)) as r
        from public.profiles p join auth.users u on u.id = p.id
        order by p.created_at desc limit 50) s)
  );
end $$;
revoke execute on function public.founder_stats() from public, anon;
grant execute on function public.founder_stats() to authenticated;

-- Check: should read  t | t | 1
select to_regclass('public.events') is not null as events_table,
       (select relrowsecurity from pg_class where oid = 'public.events'::regclass) as locked,
       (select count(*) from pg_proc where proname = 'founder_stats') as dashboard;
