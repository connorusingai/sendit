-- Sendit database, version 1: accounts, clips, community voting, leaderboard.
-- Paste this whole file into Supabase > SQL Editor > New query, then click Run.
-- Duels come in a later file (002), once this part works.
--
-- The big idea: the app (the web page) is never trusted to decide anything that
-- matters. It can post a clip and cast a vote. Deciding "verified" and handing out
-- points happens here, inside the database, where nobody can tamper with it.

-- ---------- Trick catalog ----------
-- Points live in the database so the app can't make up its own.
create table public.tricks (
  id       text primary key,
  name     text not null,
  category text not null check (category in ('Park','Rails','Pipe','Moguls','Backcountry')),
  pts      int  not null check (pts > 0)
);

insert into public.tricks (id, name, category, pts) values
  ('180','180','Park',10), ('360','360','Park',20), ('540','540','Park',35), ('720','720','Park',50),
  ('misty540','Misty 540','Park',45), ('rodeo540','Rodeo 540','Park',55), ('backflip','Backflip','Park',60),
  ('cork720','Cork 720','Park',70), ('dc1080','Double Cork 1080','Park',120),
  ('board','Boardslide','Rails',15), ('lip','Lipslide','Rails',25), ('270on','270 On','Rails',40),
  ('switchup','Switch-Up','Rails',45),
  ('alley360','Alley-Oop 360','Pipe',45), ('flair','Flair','Pipe',65),
  ('spread','Spread Eagle','Moguls',10), ('iron','Iron Cross','Moguls',15), ('mog360','Mogul 360','Moguls',35),
  ('cliff15','15 ft Cliff Drop','Backcountry',40), ('bcflip','Backcountry Backflip','Backcountry',90);

-- ---------- Profiles ----------
-- Supabase keeps logins in its own auth.users table. Each login gets one profile here.
create table public.profiles (
  id          uuid primary key references auth.users on delete cascade,
  username    text unique not null check (char_length(username) between 3 and 24),
  home_resort text,
  points      int not null default 0,     -- trick rank
  rating      int not null default 1000,  -- duel rank (ELO), used once duels arrive
  created_at  timestamptz not null default now()
);

-- Make a profile automatically whenever someone signs up.
create function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, username)
  values (new.id, coalesce(new.raw_user_meta_data->>'username', 'skier_' || left(new.id::text, 8)));
  return new;
end $$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ---------- Clips ----------
create table public.clips (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null default auth.uid() references public.profiles on delete cascade,
  trick_id       text not null references public.tricks,
  grab           text not null default 'No grab'
                 check (grab in ('No grab','Mute','Safety','Japan','Tail','Critical')),
  resort         text,
  video_path     text,  -- where the video sits in Storage, e.g. '<user id>/<clip id>.mp4'
  status         text not null default 'pending' check (status in ('pending','verified','rejected')),
  points_awarded int,
  created_at     timestamptz not null default now()
);
create index clips_status_idx on public.clips (status, created_at desc);

-- ---------- Votes ----------
create table public.votes (
  clip_id    uuid not null references public.clips on delete cascade,
  voter_id   uuid not null default auth.uid() references public.profiles on delete cascade,
  landed     boolean not null,
  reason     text check (reason in ('fell','wrong_trick','cant_see')),
  created_at timestamptz not null default now(),
  primary key (clip_id, voter_id)  -- one vote per person per clip
);

-- ---------- Scoring rules (same numbers as the prototype) ----------
-- Higher trick rank = your vote counts more.
create function public.vote_weight(pts int) returns numeric
language sql immutable as $$
  select case
    when pts >= 5000 then 2.25  -- Legend
    when pts >= 3500 then 2.0   -- Diamond
    when pts >= 2000 then 1.75  -- Platinum
    when pts >= 1000 then 1.5   -- Gold
    when pts >= 500  then 1.25  -- Silver
    else 1.0                    -- Bronze
  end
$$;

-- After every vote: once enough weight has voted, decide the clip.
-- NEED_WEIGHT = 5 and NEED_SHARE = 0.7, as in the prototype.
create function public.resolve_clip() returns trigger
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
    select round(t.pts * case when c.grab <> 'No grab' then 1.2 else 1 end)
      into award from public.tricks t where t.id = c.trick_id;
    update public.clips set status = 'verified', points_awarded = award where id = c.id;
    update public.profiles set points = points + award where id = c.user_id;
  else
    update public.clips set status = 'rejected' where id = c.id;
  end if;
  return new;
end $$;

create trigger on_vote_cast
  after insert on public.votes
  for each row execute function public.resolve_clip();

-- ---------- Who can do what (Row Level Security) ----------
-- With RLS on, every request is refused unless a policy below allows it.
alter table public.tricks   enable row level security;
alter table public.profiles enable row level security;
alter table public.clips    enable row level security;
alter table public.votes    enable row level security;

create policy "anyone can read tricks"   on public.tricks   for select using (true);
create policy "anyone can read profiles" on public.profiles for select using (true);
create policy "anyone can read clips"    on public.clips    for select using (true);

create policy "edit your own profile" on public.profiles for update to authenticated
  using (id = auth.uid()) with check (id = auth.uid());

create policy "post your own clips" on public.clips for insert to authenticated
  with check (user_id = auth.uid());

create policy "delete your own pending clips" on public.clips for delete to authenticated
  using (user_id = auth.uid() and status = 'pending');

-- You only see your own votes, so judges stay anonymous.
create policy "see your own votes" on public.votes for select to authenticated
  using (voter_id = auth.uid());

create policy "vote on other people's pending clips" on public.votes for insert to authenticated
  with check (
    voter_id = auth.uid()
    and exists (select 1 from public.clips c
                where c.id = clip_id and c.status = 'pending' and c.user_id <> auth.uid())
  );

-- Column locks: RLS decides which ROWS you can touch; these decide which COLUMNS.
-- Without them, you could post a clip already marked 'verified' or set your own points.
revoke insert, update on public.profiles from anon, authenticated;
grant update (username, home_resort) on public.profiles to authenticated;

revoke insert, update on public.clips from anon, authenticated;
grant insert (trick_id, grab, resort, video_path) on public.clips to authenticated;

revoke insert, update on public.votes from anon, authenticated;
grant insert (clip_id, landed, reason) on public.votes to authenticated;

-- ---------- Video storage ----------
-- 50 MB is the free plan's per-file cap. Videos are public to watch, so the feed works,
-- but you can only upload into a folder named after your own user id.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('clips', 'clips', true, 52428800, array['video/mp4','video/quicktime','video/webm']);

create policy "upload into your own folder" on storage.objects for insert to authenticated
  with check (bucket_id = 'clips' and (storage.foldername(name))[1] = auth.uid()::text);

create policy "delete your own videos" on storage.objects for delete to authenticated
  using (bucket_id = 'clips' and (storage.foldername(name))[1] = auth.uid()::text);
