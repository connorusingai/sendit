-- 024: season passes (BRAND-DECISIONS.md, 2026-10-28). NOT pasted yet: Connor pastes it in the Supabase SQL Editor.
-- 1. Pass photo: any photo from the camera roll, kept in its own small public bucket ('passes').
-- 2. Rider number on the pass ("NO. 0042"), in join order.
-- 3. Seasons: last season's pass stays on your profile as a trophy, and opening day drops everyone about one tier (soft reset).
--    The reset only runs when the founder calls start_season(); nothing happens on its own.
-- Same point thresholds as before (0/100/300/600/1000/1500), so nobody's rank moves when this is pasted.

-- ---------- who's the founder (rider #001, or anyone 027 marks is_founder) ----------
-- Reads is_founder through to_jsonb so this works before and after 027 adds that column.
create or replace function public.am_founder() returns boolean
language sql stable security definer set search_path = public as $$
  select auth.uid() = '713e0c5f-7de1-4842-b845-d1679b4eb7b3'::uuid
      or coalesce((select (to_jsonb(p) ->> 'is_founder')::boolean from public.profiles p where p.id = auth.uid()), false)
$$;
grant execute on function public.am_founder() to authenticated;

-- ---------- pass photo ----------
alter table public.profiles add column if not exists pass_photo text;          -- path in the 'passes' bucket: '<user id>/pass-<time>.jpg'
alter table public.profiles add column if not exists pass_photo_at timestamptz; -- so phones fetch the new photo, not a cached old one
grant update (pass_photo, pass_photo_at) on public.profiles to authenticated;

-- Your pass can only point at a photo in your own folder (like 020 does for videos)
create or replace function public.check_pass_photo() returns trigger
language plpgsql as $$
begin
  if new.pass_photo is not null and new.pass_photo is distinct from old.pass_photo
     and split_part(new.pass_photo, '/', 1) <> new.id::text then
    raise exception 'Pass photo must be your own';
  end if;
  return new;
end $$;
drop trigger if exists check_pass_photo on public.profiles;
create trigger check_pass_photo before update of pass_photo on public.profiles
  for each row execute function public.check_pass_photo();

-- 1 MB is plenty: the app shrinks photos to 304 × 384 (about 40 KB) before uploading
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('passes', 'passes', true, 1048576, array['image/jpeg', 'image/png', 'image/webp'])
on conflict (id) do nothing;
drop policy if exists "pass photo into your own folder" on storage.objects;
create policy "pass photo into your own folder" on storage.objects for insert to authenticated
  with check (bucket_id = 'passes' and (storage.foldername(name))[1] = auth.uid()::text);
drop policy if exists "delete your own pass photos" on storage.objects;
create policy "delete your own pass photos" on storage.objects for delete to authenticated
  using (bucket_id = 'passes' and (storage.foldername(name))[1] = auth.uid()::text);

-- ---------- rider number ----------
alter table public.profiles add column if not exists pass_no int;
with n as (select id, row_number() over (order by created_at, id) as k from public.profiles)
update public.profiles p set pass_no = n.k from n where p.id = n.id and p.pass_no is null;
create sequence if not exists public.pass_no_seq;
select setval('public.pass_no_seq', coalesce((select max(pass_no) from public.profiles), 0) + 1, false);
alter table public.profiles alter column pass_no set default nextval('public.pass_no_seq');
revoke update (pass_no) on public.profiles from authenticated;

-- ---------- seasons ----------
-- The tier a point total sits in. Keep in sync with TRICK_TIERS in app/index.html.
create or replace function public.pass_tier(pts int) returns text
language sql immutable as $$
  select case when pts >= 1500 then 'rat' when pts >= 1000 then 'tblack' when pts >= 600 then 'dblack'
              when pts >= 300 then 'black' when pts >= 100 then 'blue' else 'green' end
$$;

-- Old seasons' passes, one per rider per season. Public, like profiles; only start_season() writes here.
create table if not exists public.season_passes (
  user_id    uuid not null references public.profiles on delete cascade,
  season     text not null check (season ~ '^[0-9]{2}/[0-9]{2}$'),   -- '26/27'
  tier       text not null,
  points     int  not null,
  created_at timestamptz not null default now(),
  primary key (user_id, season)
);
alter table public.season_passes enable row level security;
drop policy if exists "season passes are public" on public.season_passes;
create policy "season passes are public" on public.season_passes for select to anon, authenticated using (true);
revoke insert, update, delete on public.season_passes from anon, authenticated;

-- Opening day (founder only): keep everyone's pass as a trophy, then drop each rider to the bottom of the tier below.
-- Green stays green. The Trick Book doesn't change, so tricks you already landed still don't pay twice.
-- Returns how many riders moved down. Run it once:  select public.start_season('26/27');  (the season that just ended)
create or replace function public.start_season(p_ended text) returns int
language plpgsql security definer set search_path = public as $$
declare moved int;
begin
  if not public.am_founder() then raise exception 'Founder only'; end if;
  if exists (select 1 from public.season_passes where season = p_ended) then raise exception 'Season % was already closed', p_ended; end if;
  insert into public.season_passes (user_id, season, tier, points)
    select id, p_ended, public.pass_tier(points), points from public.profiles where points > 0;
  update public.profiles set points = case
      when points >= 1500 then 1000 when points >= 1000 then 600 when points >= 600 then 300
      when points >= 300 then 100 else 0 end
    where points >= 100;
  get diagnostics moved = row_count;
  return moved;
end $$;
revoke execute on function public.start_season(text) from public, anon;
grant execute on function public.start_season(text) to authenticated;

-- Check: should read  t | t | t
select exists (select 1 from storage.buckets where id = 'passes') as photo_bucket,
       not exists (select 1 from public.profiles where pass_no is null) as everyone_numbered,
       exists (select 1 from pg_proc where proname = 'start_season') as seasons_ready;
