-- Stomped database, version 17: Film a friend (Connor, Oct 27).
-- Your buddy films you on THEIR phone, in the app, and tags you as the rider.
--   1. The clip belongs to the rider (points, trick book, profile) and remembers who filmed it.
--   2. It stays out of the feed and judging until the rider taps Keep. "Not me" deletes it.
--   3. Only friends can film each other, and the filmer can't judge a clip they filmed.
-- Paste into Supabase > SQL Editor and click Run. No existing data is changed.

-- ---------- 1. who filmed it, and has the rider said yes ----------
alter table public.clips
  add column if not exists filmed_by uuid references public.profiles on delete set null,
  add column if not exists rider_ok  boolean not null default true;   -- false = waiting for the rider

-- Waiting clips are only visible to the rider and the filmer.
drop policy if exists "anyone can read clips that aren't hidden" on public.clips;
create policy "anyone can read clips that aren't hidden" on public.clips for select
  using ((not hidden and rider_ok) or user_id = auth.uid() or (filmed_by = auth.uid() and not hidden));

-- Same as 001, plus: no votes on waiting or hidden clips, and never on a clip you filmed.
drop policy if exists "vote on other people's pending clips" on public.votes;
create policy "vote on other people's pending clips" on public.votes for insert to authenticated
  with check (
    voter_id = auth.uid()
    and exists (select 1 from public.clips c
                where c.id = clip_id and c.status = 'pending' and c.rider_ok and not c.hidden
                  and c.user_id <> auth.uid() and c.filmed_by is distinct from auth.uid())
  );

-- ---------- 2. post a clip for a friend ----------
-- The app can't insert a clip for someone else (001 locks user_id to you), so this function does it
-- after checking: you're friends, it's not yourself, and the video is in YOUR storage folder.
create or replace function public.post_for_friend(p_rider uuid, p_trick text, p_grab text, p_resort text,
                                                  p_video_path text, p_combo text[] default '{}')
returns uuid language plpgsql security definer set search_path = public as $$
declare new_id uuid;
begin
  if auth.uid() is null then raise exception 'Sign in first'; end if;
  if p_rider = auth.uid() then raise exception 'Pick "Me" to post your own clip'; end if;
  if not exists (select 1 from public.friendships
                  where status = 'accepted'
                    and ((requester = auth.uid() and addressee = p_rider) or (requester = p_rider and addressee = auth.uid()))) then
    raise exception 'You can only film friends';
  end if;
  if p_video_path is null or split_part(p_video_path, '/', 1) <> auth.uid()::text then
    raise exception 'That video isn''t yours';
  end if;
  if (select count(*) from public.clips where filmed_by = auth.uid() and user_id = p_rider and not rider_ok) >= 10 then
    raise exception 'They already have 10 clips from you waiting. Ask them to check Base.';
  end if;
  insert into public.clips (user_id, filmed_by, rider_ok, trick_id, grab, resort, video_path, combo)
  values (p_rider, auth.uid(), false, p_trick, coalesce(p_grab, 'No grab'), p_resort, p_video_path, coalesce(p_combo, '{}'))
  returning id into new_id;
  return new_id;
end $$;
revoke execute on function public.post_for_friend(uuid, text, text, text, text, text[]) from public, anon;
grant execute on function public.post_for_friend(uuid, text, text, text, text, text[]) to authenticated;

-- ---------- 3. the rider answers ----------
-- Keep = it goes to the feed and judging. Not me = it's deleted.
-- Returns the video path when deleted, so the filmer's app can tidy up the file later.
create or replace function public.answer_filmed_clip(p_clip uuid, p_keep boolean) returns text
language plpgsql security definer set search_path = public as $$
declare path text;
begin
  if p_keep then
    update public.clips set rider_ok = true, created_at = now()   -- fresh in the feed from the moment you keep it
     where id = p_clip and user_id = auth.uid() and not rider_ok;
    if not found then raise exception 'Nothing waiting for you there'; end if;
    return null;
  end if;
  delete from public.clips where id = p_clip and user_id = auth.uid() and not rider_ok returning video_path into path;
  if not found then raise exception 'Nothing waiting for you there'; end if;
  return path;
end $$;
revoke execute on function public.answer_filmed_clip(uuid, boolean) from public, anon;
grant execute on function public.answer_filmed_clip(uuid, boolean) to authenticated;

-- Check: should read  2 | 2
select (select count(*) from information_schema.columns
         where table_schema = 'public' and table_name = 'clips' and column_name in ('filmed_by', 'rider_ok')) as new_columns,
       (select count(*) from pg_proc where proname in ('post_for_friend', 'answer_filmed_clip')) as new_functions;
