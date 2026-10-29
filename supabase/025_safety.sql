-- 025: safety (#4, 2026-10-28). NOT pasted yet: Connor pastes it in the Supabase SQL Editor (after 024).
-- 1. Report a pass photo, like a clip or comment (011). Three reports (new accounts count half, 023) take the photo down.
-- 2. Block a rider: their clips, comments and pass leave your app, any friendship ends, and they can't send you a request.

-- ---------- 1. reports on pass photos ----------
alter table public.reports add column if not exists profile_id uuid references public.profiles on delete cascade;
alter table public.reports drop constraint if exists reports_check;   -- was: exactly one of clip / comment
alter table public.reports drop constraint if exists reports_one_thing;
alter table public.reports add constraint reports_one_thing check (num_nonnulls(clip_id, comment_id, profile_id) = 1);
create unique index if not exists reports_one_per_profile on public.reports (reporter, profile_id) where profile_id is not null;

create or replace function public.hide_reported() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if new.clip_id is not null then
    if (select coalesce(sum(public.new_account_factor(reporter)), 0) from public.reports where clip_id = new.clip_id)
         >= public.reports_needed() then
      update public.clips set hidden = true where id = new.clip_id;
    end if;
  elsif new.comment_id is not null then
    if (select coalesce(sum(public.new_account_factor(reporter)), 0) from public.reports where comment_id = new.comment_id)
         >= public.reports_needed() then
      update public.comments set hidden = true where id = new.comment_id;
    end if;
  else
    -- A reported pass loses its photo (the file stays for the founder to look at, then remove or restore)
    if (select coalesce(sum(public.new_account_factor(reporter)), 0) from public.reports where profile_id = new.profile_id)
         >= public.reports_needed() then
      update public.profiles set pass_photo = null where id = new.profile_id;
    end if;
  end if;
  return new;
end $$;

-- ---------- 2. blocking ----------
create table if not exists public.blocks (
  blocker    uuid not null default auth.uid() references public.profiles on delete cascade,
  blocked    uuid not null references public.profiles on delete cascade,
  created_at timestamptz not null default now(),
  primary key (blocker, blocked),
  check (blocker <> blocked)
);
alter table public.blocks enable row level security;
drop policy if exists "see who you blocked" on public.blocks;
create policy "see who you blocked" on public.blocks for select to authenticated using (blocker = auth.uid());
drop policy if exists "unblock" on public.blocks;
create policy "unblock" on public.blocks for delete to authenticated using (blocker = auth.uid());
revoke insert, update on public.blocks from anon, authenticated;   -- blocking goes through block_user(), which also ends the friendship

create or replace function public.block_user(p_user uuid) returns void
language plpgsql security definer set search_path = public as $$
declare me uuid := auth.uid();
begin
  if me is null then raise exception 'Not signed in'; end if;
  if p_user = me then raise exception 'You can''t block yourself'; end if;
  insert into public.blocks (blocker, blocked) values (me, p_user) on conflict do nothing;
  delete from public.friendships where (requester = me and addressee = p_user) or (requester = p_user and addressee = me);
end $$;
revoke execute on function public.block_user(uuid) from public, anon;
grant execute on function public.block_user(uuid) to authenticated;

create or replace function public.unblock_user(p_user uuid) returns void
language sql security definer set search_path = public as $$
  delete from public.blocks where blocker = auth.uid() and blocked = p_user
$$;
revoke execute on function public.unblock_user(uuid) from public, anon;
grant execute on function public.unblock_user(uuid) to authenticated;

-- No friend requests between two riders when either blocked the other
create or replace function public.no_requests_when_blocked() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if exists (select 1 from public.blocks where (blocker = new.requester and blocked = new.addressee)
                                            or (blocker = new.addressee and blocked = new.requester)) then
    raise exception 'You can''t add this rider';
  end if;
  return new;
end $$;
drop trigger if exists no_requests_when_blocked on public.friendships;
create trigger no_requests_when_blocked before insert on public.friendships
  for each row execute function public.no_requests_when_blocked();

-- Check: should read  t | t
select exists (select 1 from information_schema.columns where table_name = 'reports' and column_name = 'profile_id') as pass_reports_ready,
       exists (select 1 from pg_proc where proname = 'block_user') as blocking_ready;
