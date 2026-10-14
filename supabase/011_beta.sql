-- Stomped database, version 11: ready for a beta with real riders.
--   1. A clip needs 3 vote weight to be decided (was 5), so a small group of friends can verify each other.
--      Change it later with one line:  create or replace function public.need_weight() returns numeric
--                                       language sql immutable as $$ select 5::numeric $$;
--   2. Reports: any rider can report a clip or comment. Three different riders reporting it hides it from
--      everyone except the person who posted it.
--   3. Riders can remove their own clip even after it's verified (its video goes, its points stay, so
--      deleting and re-posting can't farm points), and delete their whole account.
-- Paste into Supabase > SQL Editor and click Run. No existing data is changed.

-- ---------- 1. vote threshold ----------
create or replace function public.need_weight() returns numeric
language sql immutable as $$ select 3::numeric $$;

create or replace function public.resolve_clip() returns trigger
language plpgsql security definer set search_path = public as $$
declare
  yes_w     numeric;
  total_w   numeric;
  c         public.clips%rowtype;
  base      numeric;
  totd_x    numeric;
  award     int;
  has_trick boolean;
  has_grab  boolean;
begin
  select * into c from public.clips where id = new.clip_id for update;
  if c.status <> 'pending' then return new; end if;

  select coalesce(sum(vote_weight(p.points) * (v.landed)::int), 0),
         coalesce(sum(vote_weight(p.points)), 0)
    into yes_w, total_w
    from public.votes v join public.profiles p on p.id = v.voter_id
   where v.clip_id = c.id;

  if total_w < public.need_weight() then return new; end if;

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

    update public.clips set status = 'verified', points_awarded = award, verified_at = now() where id = c.id;
    update public.profiles set points = points + award where id = c.user_id;
  else
    update public.clips set status = 'rejected' where id = c.id;
  end if;
  return new;
end $$;

-- ---------- 2. hidden clips and comments ----------
alter table public.clips    add column if not exists hidden boolean not null default false;
alter table public.comments add column if not exists hidden boolean not null default false;

drop policy if exists "anyone can read clips" on public.clips;
create policy "anyone can read clips that aren't hidden" on public.clips for select
  using (not hidden or user_id = auth.uid());
drop policy if exists "anyone can read comments" on public.comments;
create policy "anyone can read comments that aren't hidden" on public.comments for select
  using (not hidden or user_id = auth.uid());

-- Clients may never set hidden themselves; only the report trigger and hide_my_clip() do.
-- (001 and 002 already block client updates; repeated here so this file is safe on its own.)
revoke update on public.clips from anon, authenticated;
revoke update on public.comments from anon, authenticated;

create table if not exists public.reports (
  id         bigint generated always as identity primary key,
  reporter   uuid not null default auth.uid() references public.profiles on delete cascade,
  clip_id    uuid references public.clips on delete cascade,
  comment_id uuid references public.comments on delete cascade,
  reason     text not null check (reason in ('inappropriate', 'spam', 'fake', 'other')),
  created_at timestamptz not null default now(),
  check ((clip_id is null) <> (comment_id is null))   -- exactly one thing is reported
);
create unique index if not exists reports_one_per_clip    on public.reports (reporter, clip_id)    where clip_id is not null;
create unique index if not exists reports_one_per_comment on public.reports (reporter, comment_id) where comment_id is not null;

alter table public.reports enable row level security;
drop policy if exists "report as yourself" on public.reports;
create policy "report as yourself" on public.reports for insert to authenticated
  with check (reporter = auth.uid());
drop policy if exists "see your own reports" on public.reports;
create policy "see your own reports" on public.reports for select to authenticated
  using (reporter = auth.uid());

create or replace function public.reports_needed() returns int
language sql immutable as $$ select 3 $$;

create or replace function public.hide_reported() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if new.clip_id is not null then
    if (select count(*) from public.reports where clip_id = new.clip_id) >= public.reports_needed() then
      update public.clips set hidden = true where id = new.clip_id;
    end if;
  else
    if (select count(*) from public.reports where comment_id = new.comment_id) >= public.reports_needed() then
      update public.comments set hidden = true where id = new.comment_id;
    end if;
  end if;
  return new;
end $$;
drop trigger if exists hide_reported on public.reports;
create trigger hide_reported after insert on public.reports
  for each row execute function public.hide_reported();

-- ---------- 3. your own clips and your account ----------
-- Hide one of your own clips for good. Returns its video path so the app can delete the file.
create or replace function public.hide_my_clip(p_clip uuid) returns text
language plpgsql security definer set search_path = public as $$
declare path text;
begin
  update public.clips set hidden = true where id = p_clip and user_id = auth.uid() returning video_path into path;
  if not found then raise exception 'Not your clip'; end if;
  return path;
end $$;
revoke execute on function public.hide_my_clip(uuid) from public, anon;
grant execute on function public.hide_my_clip(uuid) to authenticated;

-- Delete your account and everything in it (profile, clips, votes, likes, comments, friends, duels).
-- The app deletes your video files first, because files live outside these tables.
create or replace function public.delete_my_account() returns void
language plpgsql security definer set search_path = public, auth as $$
declare me uuid := auth.uid();
begin
  if me is null then raise exception 'Not signed in'; end if;
  update public.duels set winner = null where winner = me;   -- the only link that would block the delete
  delete from auth.users where id = me;                      -- profiles and everything under them cascade
end $$;
revoke execute on function public.delete_my_account() from public, anon;
grant execute on function public.delete_my_account() to authenticated;

-- Check: should read  3 | t | t
select public.need_weight() as votes_needed,
       exists (select 1 from information_schema.tables where table_name = 'reports') as reports_ready,
       exists (select 1 from pg_proc where proname = 'delete_my_account') as delete_ready;
