-- Sendit database, version 3: snowboard tricks, friends, and Game of S.K.I. duels.
-- Paste into Supabase > SQL Editor > New query and click Run.
-- If a popup asks about Row Level Security, pick the option that runs WITHOUT
-- enabling it: this file sets its own rules below.

-- ---------- Snowboard tricks ----------
alter table public.tricks
  add column sport text not null default 'ski' check (sport in ('ski','snowboard'));

insert into public.tricks (id, name, category, pts, sport) values
  ('sb-bs180','Backside 180','Park',10,'snowboard'), ('sb-fs360','Frontside 360','Park',20,'snowboard'),
  ('sb-bs360','Backside 360','Park',22,'snowboard'), ('sb-bs540','Backside 540','Park',35,'snowboard'),
  ('sb-cab540','Cab 540','Park',40,'snowboard'), ('sb-fs720','Frontside 720','Park',50,'snowboard'),
  ('sb-bs720','Backside 720','Park',52,'snowboard'), ('sb-backflip','Backflip','Park',60,'snowboard'),
  ('sb-frontflip','Frontflip','Park',60,'snowboard'), ('sb-bscork900','Backside Cork 900','Park',75,'snowboard'),
  ('sb-dc1080','Double Cork 1080','Park',120,'snowboard'),
  ('sb-5050','50-50','Rails',10,'snowboard'), ('sb-board','Boardslide','Rails',15,'snowboard'),
  ('sb-lip','Lipslide','Rails',25,'snowboard'), ('sb-270on','270 On','Rails',40,'snowboard'),
  ('sb-fsair','Frontside Air','Pipe',15,'snowboard'), ('sb-alley','Alley-Oop','Pipe',30,'snowboard'),
  ('sb-mctwist','McTwist','Pipe',90,'snowboard'),
  ('sb-cliff15','15 ft Cliff Drop','Backcountry',40,'snowboard'),
  ('sb-bcflip','Backcountry Backflip','Backcountry',90,'snowboard');

-- Snowboard grabs join the list of allowed grabs.
alter table public.clips drop constraint clips_grab_check;
alter table public.clips add constraint clips_grab_check check (grab in
  ('No grab','Mute','Safety','Japan','Tail','Critical','Indy','Melon','Method','Stalefish','Nose'));

-- ---------- Friends ----------
-- One row per pair. Starts 'pending'; the person it was sent to can accept it.
create table public.friendships (
  requester  uuid not null default auth.uid() references public.profiles on delete cascade,
  addressee  uuid not null references public.profiles on delete cascade,
  status     text not null default 'pending' check (status in ('pending','accepted')),
  created_at timestamptz not null default now(),
  primary key (requester, addressee),
  check (requester <> addressee)
);
-- Stops A→B and B→A both existing.
create unique index friendships_pair on public.friendships
  (least(requester, addressee), greatest(requester, addressee));

alter table public.friendships enable row level security;
create policy "see your own friendships" on public.friendships for select to authenticated
  using (auth.uid() in (requester, addressee));
create policy "send friend requests" on public.friendships for insert to authenticated
  with check (requester = auth.uid() and status = 'pending');
create policy "accept requests sent to you" on public.friendships for update to authenticated
  using (addressee = auth.uid()) with check (addressee = auth.uid() and status = 'accepted');
create policy "remove a friendship" on public.friendships for delete to authenticated
  using (auth.uid() in (requester, addressee));

revoke insert, update on public.friendships from anon, authenticated;
grant insert (addressee) on public.friendships to authenticated;
grant update (status)    on public.friendships to authenticated;

-- ---------- Duels ----------
-- Game of S.K.I.: the setter lands a trick, the other skier must match it.
-- Miss a match = a letter. Three letters (S-K-I) = you lose.
create table public.duels (
  id                 uuid primary key default gen_random_uuid(),
  challenger         uuid not null references public.profiles on delete cascade,
  opponent           uuid not null references public.profiles on delete cascade,
  status             text not null default 'active' check (status in ('active','done')),
  turn               uuid,  -- whose move it is (null once the duel is over)
  phase              text not null default 'set' check (phase in ('set','match')),
  trick_id           text references public.tricks,  -- the trick to match, during 'match'
  letters_challenger int  not null default 0,
  letters_opponent   int  not null default 0,
  winner             uuid references public.profiles,
  rating_change      int,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);
create unique index one_active_duel_per_pair on public.duels
  (least(challenger, opponent), greatest(challenger, opponent)) where status = 'active';

create table public.duel_moves (
  id         bigint generated always as identity primary key,
  duel_id    uuid not null references public.duels on delete cascade,
  user_id    uuid not null references public.profiles on delete cascade,
  kind       text not null check (kind in ('set','match')),
  trick_id   text not null references public.tricks,
  clip_id    uuid references public.clips on delete set null,  -- the recorded attempt
  landed     boolean not null,
  created_at timestamptz not null default now()
);
create index duel_moves_duel_idx on public.duel_moves (duel_id, id);

alter table public.duels      enable row level security;
alter table public.duel_moves enable row level security;
create policy "see your own duels" on public.duels for select to authenticated
  using (auth.uid() in (challenger, opponent));
create policy "see moves in your duels" on public.duel_moves for select to authenticated
  using (exists (select 1 from public.duels d where d.id = duel_id and auth.uid() in (d.challenger, d.opponent)));

-- Nobody writes duels directly. Every change goes through the functions below,
-- which check whose turn it is and keep score.
revoke insert, update, delete on public.duels      from anon, authenticated;
revoke insert, update, delete on public.duel_moves from anon, authenticated;

-- Finish a duel and move ratings (chess ELO, K = 32). Internal only.
create function public.end_duel(p_duel uuid, p_winner uuid, p_loser uuid) returns void
language plpgsql security definer set search_path = public as $$
declare
  r_win  int;
  r_lose int;
  delta  int;
begin
  select rating into r_win  from public.profiles where id = p_winner;
  select rating into r_lose from public.profiles where id = p_loser;
  -- Beating someone rated above you earns more
  delta := round(32 * (1 - 1 / (1 + power(10, (r_lose - r_win) / 400.0))));
  update public.profiles set rating = rating + delta             where id = p_winner;
  update public.profiles set rating = greatest(0, rating - delta) where id = p_loser;
  update public.duels set status = 'done', winner = p_winner, rating_change = delta,
         turn = null, trick_id = null, updated_at = now()
   where id = p_duel;
end $$;
revoke execute on function public.end_duel(uuid, uuid, uuid) from public, anon, authenticated;

create function public.start_duel(p_opponent uuid) returns uuid
language plpgsql security definer set search_path = public as $$
declare
  me     uuid := auth.uid();
  new_id uuid;
begin
  if me is null then raise exception 'Sign in first'; end if;
  if not exists (select 1 from public.friendships f
                  where f.status = 'accepted'
                    and ((f.requester = me and f.addressee = p_opponent)
                      or (f.requester = p_opponent and f.addressee = me))) then
    raise exception 'You can only duel friends';
  end if;
  insert into public.duels (challenger, opponent, turn) values (me, p_opponent, me)
  returning id into new_id;
  return new_id;
exception when unique_violation then
  raise exception 'You already have a duel going with this skier';
end $$;

-- One move. In 'set': pick a trick and say whether you landed it.
-- In 'match': say whether you matched the other skier's trick.
-- Landing needs a recorded clip as proof; bails don't.
create function public.duel_move(p_duel uuid, p_landed boolean, p_trick text default null, p_clip uuid default null)
returns void
language plpgsql security definer set search_path = public as $$
declare
  me         uuid := auth.uid();
  d          public.duels%rowtype;
  other      uuid;
  my_letters int;
begin
  select * into d from public.duels where id = p_duel for update;
  if not found or me is null or me not in (d.challenger, d.opponent) then raise exception 'Duel not found'; end if;
  if d.status <> 'active' then raise exception 'This duel is over'; end if;
  if d.turn <> me then raise exception 'Not your turn'; end if;
  if p_landed and p_clip is null then raise exception 'Record your attempt to prove you landed it'; end if;
  if p_clip is not null and not exists (select 1 from public.clips where id = p_clip and user_id = me) then
    raise exception 'That clip is not yours';
  end if;
  other := case when me = d.challenger then d.opponent else d.challenger end;

  if d.phase = 'set' then
    if p_trick is null or not exists (select 1 from public.tricks where id = p_trick) then
      raise exception 'Pick a trick';
    end if;
    insert into public.duel_moves (duel_id, user_id, kind, trick_id, clip_id, landed)
    values (d.id, me, 'set', p_trick, p_clip, p_landed);
    -- Landed: the other skier has to match it. Bailed: they get to set instead.
    update public.duels
       set phase = case when p_landed then 'match' else 'set' end,
           trick_id = case when p_landed then p_trick else null end,
           turn = other, updated_at = now()
     where id = d.id;
  else
    insert into public.duel_moves (duel_id, user_id, kind, trick_id, clip_id, landed)
    values (d.id, me, 'match', d.trick_id, p_clip, p_landed);
    if not p_landed then
      update public.duels
         set letters_challenger = letters_challenger + (me = d.challenger)::int,
             letters_opponent   = letters_opponent   + (me = d.opponent)::int
       where id = d.id;
    end if;
    select case when me = challenger then letters_challenger else letters_opponent end
      into my_letters from public.duels where id = d.id;
    if my_letters >= 3 then
      perform public.end_duel(d.id, other, me);  -- I spelled S-K-I
    else
      -- The setter keeps control and sets again
      update public.duels set phase = 'set', trick_id = null, turn = other, updated_at = now() where id = d.id;
    end if;
  end if;
end $$;

create function public.forfeit_duel(p_duel uuid) returns void
language plpgsql security definer set search_path = public as $$
declare
  me uuid := auth.uid();
  d  public.duels%rowtype;
begin
  select * into d from public.duels where id = p_duel for update;
  if not found or me is null or me not in (d.challenger, d.opponent) then raise exception 'Duel not found'; end if;
  if d.status <> 'active' then raise exception 'This duel is over'; end if;
  perform public.end_duel(d.id, case when me = d.challenger then d.opponent else d.challenger end, me);
end $$;

grant execute on function public.start_duel(uuid)                       to authenticated;
grant execute on function public.duel_move(uuid, boolean, text, uuid)   to authenticated;
grant execute on function public.forfeit_duel(uuid)                     to authenticated;

-- ---------- Leaderboard, now with a friends filter ----------
drop function public.leaderboard(text, text);
create function public.leaderboard(p_period text default 'all', p_resort text default null, p_ids uuid[] default null)
returns table (id uuid, username text, home_resort text, points int, rating int, score bigint)
language sql stable set search_path = public as $$
  select p.id, p.username, p.home_resort, p.points, p.rating,
         case when p_period = 'week' then
           coalesce((select sum(c.points_awarded) from public.clips c
                      where c.user_id = p.id and c.status = 'verified'
                        and c.verified_at >= now() - interval '7 days'), 0)
         else p.points end::bigint as score
    from public.profiles p
   where (p_resort is null or p.home_resort = p_resort)
     and (p_ids is null or p.id = any(p_ids))
   order by score desc, p.username
   limit 50
$$;
grant execute on function public.leaderboard(text, text, uuid[]) to anon, authenticated;

-- ---------- Check ----------
-- The result row should read: 20 | 3 | 3
select
  (select count(*) from public.tricks where sport = 'snowboard') as snowboard_tricks_of_20,
  (select count(*) from pg_tables where schemaname = 'public'
     and tablename in ('friendships', 'duels', 'duel_moves'))  as new_tables_of_3,
  (select count(*) from pg_proc where proname in ('start_duel', 'duel_move', 'forfeit_duel')) as duel_functions_of_3;
