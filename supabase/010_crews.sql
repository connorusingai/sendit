-- Sendit database, version 10: Crews.
-- A crew is a group of friends (like a ski club) with its own leaderboard.
-- You can be in one crew at a time. Join with the crew's 6-letter invite code.
-- Paste into Supabase > SQL Editor > New query and click Run.
-- If a popup asks about Row Level Security, pick the option that runs WITHOUT
-- enabling it: this file sets its own rules below.

create table public.crews (
  id         uuid primary key default gen_random_uuid(),
  name       text not null check (char_length(btrim(name)) between 3 and 24),
  tag        text not null check (tag ~ '^[A-Z0-9]{2,4}$'),
  code       text not null unique,           -- the invite code; only members can see it
  owner      uuid references public.profiles on delete set null,
  created_at timestamptz not null default now()
);
create unique index crews_name_unique on public.crews (lower(btrim(name)));

create table public.crew_members (
  user_id   uuid primary key references public.profiles on delete cascade,  -- one crew per person
  crew_id   uuid not null references public.crews on delete cascade,
  joined_at timestamptz not null default now()
);
create index crew_members_crew on public.crew_members (crew_id);

-- Everyone can see crews and who's in them. Nobody writes directly: the functions below do it.
alter table public.crews enable row level security;
alter table public.crew_members enable row level security;
create policy "crews are public" on public.crews for select to anon, authenticated using (true);
create policy "crew members are public" on public.crew_members for select to anon, authenticated using (true);

revoke all on public.crews, public.crew_members from anon, authenticated;
grant select (id, name, tag, owner, created_at) on public.crews to anon, authenticated;   -- not the code
grant select on public.crew_members to anon, authenticated;

-- A random 6-character code without look-alike letters (no 0/O, 1/I/L).
create or replace function public.new_crew_code() returns text
language plpgsql volatile set search_path = public as $$
declare
  abc constant text := 'ABCDEFGHJKMNPQRSTUVWXYZ23456789';
  c text;
begin
  loop
    c := '';
    for i in 1..6 loop
      c := c || substr(abc, 1 + floor(random() * length(abc))::int, 1);
    end loop;
    exit when not exists (select 1 from public.crews where code = c);
  end loop;
  return c;
end $$;

-- Your crew, including its invite code. Empty if you're not in one.
create or replace function public.my_crew()
returns table (id uuid, name text, tag text, code text, owner uuid, created_at timestamptz)
language sql stable security definer set search_path = public as $$
  select c.id, c.name, c.tag, c.code, c.owner, c.created_at
    from public.crews c join public.crew_members m on m.crew_id = c.id
   where m.user_id = auth.uid()
$$;

create or replace function public.create_crew(p_name text, p_tag text) returns uuid
language plpgsql security definer set search_path = public as $$
declare
  me uuid := auth.uid();
  new_id uuid;
begin
  if me is null then raise exception 'Sign in first.'; end if;
  if exists (select 1 from public.crew_members where user_id = me) then
    raise exception 'Leave your current crew first.';
  end if;
  if exists (select 1 from public.crews where lower(btrim(name)) = lower(btrim(p_name))) then
    raise exception 'That crew name is taken.';
  end if;
  insert into public.crews (name, tag, code, owner)
  values (btrim(p_name), upper(btrim(p_tag)), public.new_crew_code(), me)
  returning crews.id into new_id;
  insert into public.crew_members (user_id, crew_id) values (me, new_id);
  return new_id;
end $$;

create or replace function public.join_crew(p_code text) returns uuid
language plpgsql security definer set search_path = public as $$
declare
  me uuid := auth.uid();
  target uuid;
begin
  if me is null then raise exception 'Sign in first.'; end if;
  select c.id into target from public.crews c where c.code = upper(btrim(p_code));
  if target is null then raise exception 'No crew with that code.'; end if;
  if exists (select 1 from public.crew_members where user_id = me and crew_id = target) then
    return target;                                            -- already in it
  end if;
  if exists (select 1 from public.crew_members where user_id = me) then
    raise exception 'Leave your current crew first.';
  end if;
  if (select count(*) from public.crew_members where crew_id = target) >= 50 then
    raise exception 'That crew is full (50 riders).';
  end if;
  insert into public.crew_members (user_id, crew_id) values (me, target);
  return target;
end $$;

-- Leaving hands the crew to the longest-standing member. The last one out deletes it.
create or replace function public.leave_crew() returns void
language plpgsql security definer set search_path = public as $$
declare
  me uuid := auth.uid();
  cid uuid;
  heir uuid;
begin
  delete from public.crew_members where user_id = me returning crew_id into cid;
  if cid is null then return; end if;
  select user_id into heir from public.crew_members where crew_id = cid order by joined_at limit 1;
  if heir is null then
    delete from public.crews where id = cid;
  else
    update public.crews set owner = heir where id = cid and (owner = me or owner is null);
  end if;
end $$;

-- The crew owner can remove someone.
create or replace function public.kick_from_crew(p_user uuid) returns void
language plpgsql security definer set search_path = public as $$
begin
  if p_user = auth.uid() then raise exception 'Use Leave crew instead.'; end if;
  delete from public.crew_members m
   using public.crews c
   where m.user_id = p_user and m.crew_id = c.id and c.owner = auth.uid();
  if not found then raise exception 'Only the crew owner can do that.'; end if;
end $$;

-- Crew leaderboard: a crew's score is its members' points added up
-- (all time, or just the last 7 days).
create or replace function public.crew_board(p_period text default 'all')
returns table (id uuid, name text, tag text, members int, score bigint)
language sql stable set search_path = public as $$
  select c.id, c.name, c.tag, count(m.user_id)::int,
         coalesce(sum(case when p_period = 'week' then
           (select coalesce(sum(cl.points_awarded), 0) from public.clips cl
             where cl.user_id = m.user_id and cl.status = 'verified'
               and cl.verified_at >= now() - interval '7 days')
           else p.points end), 0)::bigint as score
    from public.crews c
    join public.crew_members m on m.crew_id = c.id
    join public.profiles p on p.id = m.user_id
   group by c.id
   order by score desc, c.name
   limit 50
$$;

revoke execute on function public.new_crew_code() from public, anon, authenticated;
grant execute on function public.my_crew()               to authenticated;
grant execute on function public.create_crew(text, text) to authenticated;
grant execute on function public.join_crew(text)         to authenticated;
grant execute on function public.leave_crew()            to authenticated;
grant execute on function public.kick_from_crew(uuid)    to authenticated;
grant execute on function public.crew_board(text)        to anon, authenticated;

-- ---------- Check ----------
-- The result row should read: 2 | 6
select
  (select count(*) from pg_tables where schemaname = 'public'
     and tablename in ('crews', 'crew_members')) as new_tables_of_2,
  (select count(*) from pg_proc where proname in
     ('my_crew', 'create_crew', 'join_crew', 'leave_crew', 'kick_from_crew', 'crew_board')) as crew_functions_of_6;
