-- Sendit database, version 2: Trick of the Day, likes, comments, weekly leaderboard.
-- Paste into Supabase > SQL Editor > New query and click Run, same as 001.
-- If a popup asks about Row Level Security, pick the option that runs WITHOUT
-- enabling it: this file sets its own rules below.

-- ---------- Trick of the Day ----------
-- Everyone gets the same trick all day (Denver time), and nobody can choose it.
-- md5 of "trick id + date" shuffles the list differently each day.
create function public.trick_of_day(d date default (now() at time zone 'America/Denver')::date)
returns text language sql stable set search_path = public as $$
  select id from public.tricks order by md5(id || d::text) limit 1
$$;

-- totd: was this the Trick of the Day when it was posted? The database stamps it
-- itself, so the app can't claim a bonus it didn't earn.
alter table public.clips
  add column totd        boolean not null default false,
  add column verified_at timestamptz;

create function public.stamp_totd() returns trigger
language plpgsql set search_path = public as $$
begin
  new.totd := (new.trick_id = public.trick_of_day());
  return new;
end $$;

create trigger before_clip_insert
  before insert on public.clips
  for each row execute function public.stamp_totd();

-- Same verification rules as 001, plus: Trick of the Day clips earn 2x,
-- and we record when each clip was verified (for the weekly leaderboard).
create or replace function public.resolve_clip() returns trigger
language plpgsql security definer set search_path = public as $$
declare
  yes_w   numeric;
  total_w numeric;
  c       public.clips%rowtype;
  award   int;
begin
  select * into c from public.clips where id = new.clip_id for update;
  if c.status <> 'pending' then return new; end if;

  select coalesce(sum(vote_weight(p.points) * (v.landed)::int), 0),
         coalesce(sum(vote_weight(p.points)), 0)
    into yes_w, total_w
    from public.votes v join public.profiles p on p.id = v.voter_id
   where v.clip_id = c.id;

  if total_w < 5 then return new; end if;

  if yes_w / total_w >= 0.7 then
    select round(t.pts
                 * case when c.grab <> 'No grab' then 1.2 else 1 end
                 * case when c.totd then 2 else 1 end)
      into award from public.tricks t where t.id = c.trick_id;
    update public.clips set status = 'verified', points_awarded = award, verified_at = now() where id = c.id;
    update public.profiles set points = points + award where id = c.user_id;
  else
    update public.clips set status = 'rejected' where id = c.id;
  end if;
  return new;
end $$;

-- ---------- Likes ----------
create table public.likes (
  clip_id    uuid not null references public.clips on delete cascade,
  user_id    uuid not null default auth.uid() references public.profiles on delete cascade,
  created_at timestamptz not null default now(),
  primary key (clip_id, user_id)  -- one like per person per clip
);

-- ---------- Comments ----------
create table public.comments (
  id         uuid primary key default gen_random_uuid(),
  clip_id    uuid not null references public.clips on delete cascade,
  user_id    uuid not null default auth.uid() references public.profiles on delete cascade,
  body       text not null check (char_length(btrim(body)) between 1 and 280),
  created_at timestamptz not null default now()
);
create index comments_clip_idx on public.comments (clip_id, created_at);

-- ---------- Rules ----------
alter table public.likes    enable row level security;
alter table public.comments enable row level security;

create policy "anyone can read likes"    on public.likes    for select using (true);
create policy "anyone can read comments" on public.comments for select using (true);

create policy "like as yourself" on public.likes for insert to authenticated
  with check (user_id = auth.uid());
create policy "unlike your own likes" on public.likes for delete to authenticated
  using (user_id = auth.uid());

create policy "comment as yourself" on public.comments for insert to authenticated
  with check (user_id = auth.uid());
create policy "delete your own comments" on public.comments for delete to authenticated
  using (user_id = auth.uid());

revoke insert, update on public.likes    from anon, authenticated;
revoke insert, update on public.comments from anon, authenticated;
grant insert (clip_id)       on public.likes    to authenticated;
grant insert (clip_id, body) on public.comments to authenticated;

-- ---------- Leaderboard ----------
-- period: 'all' = total points, 'week' = points verified in the last 7 days.
-- resort: only skiers whose home mountain matches (null = everyone).
create function public.leaderboard(p_period text default 'all', p_resort text default null)
returns table (id uuid, username text, home_resort text, points int, score bigint)
language sql stable set search_path = public as $$
  select p.id, p.username, p.home_resort, p.points,
         case when p_period = 'week' then
           coalesce((select sum(c.points_awarded) from public.clips c
                      where c.user_id = p.id and c.status = 'verified'
                        and c.verified_at >= now() - interval '7 days'), 0)
         else p.points end::bigint as score
    from public.profiles p
   where p_resort is null or p.home_resort = p_resort
   order by score desc, p.username
   limit 50
$$;

grant execute on function public.trick_of_day(date)          to anon, authenticated;
grant execute on function public.leaderboard(text, text)     to anon, authenticated;

-- ---------- Check ----------
-- The result row should read: 2 | (a trick id) | 1
select
  (select count(*) from pg_tables where schemaname = 'public' and tablename in ('likes', 'comments')) as new_tables_of_2,
  public.trick_of_day() as todays_trick,
  (select count(*) from pg_trigger where tgname = 'before_clip_insert') as new_trigger_of_1;
