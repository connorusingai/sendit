-- Stomped database, version 19: wrong rider (Connor, Oct 27).
-- You filmed your buddy but forgot to pick them in "Who's riding?", so it posted as YOUR clip.
-- While it's still being judged, you can give it to them: it becomes a Film a friend clip (017) waiting on their Base.
--   - Only your own clip, still being judged, that you filmed yourself (not one a friend filmed of you).
--   - Only to a friend. Not for duel clips (the duel would break).
--   - Votes so far are cleared: they were judging the wrong rider.
-- Once a clip is verified it can't change hands (that would let people farm points with friends).
-- Paste into Supabase > SQL Editor and click Run. No existing data is changed.

create or replace function public.give_clip_to_friend(p_clip uuid, p_rider uuid) returns void
language plpgsql security definer set search_path = public as $$
declare c public.clips%rowtype;
begin
  select * into c from public.clips where id = p_clip for update;
  if not found or c.user_id <> auth.uid() or c.hidden then raise exception 'Not your clip'; end if;
  if c.status <> 'pending' then raise exception 'Only clips still being judged can go to a friend'; end if;
  if c.filmed_by is not null then raise exception 'A friend filmed this one for you, so it stays yours'; end if;
  if p_rider = auth.uid() then raise exception 'It''s already yours'; end if;
  if not exists (select 1 from public.friendships
                  where status = 'accepted'
                    and ((requester = auth.uid() and addressee = p_rider) or (requester = p_rider and addressee = auth.uid()))) then
    raise exception 'You can only give clips to friends';
  end if;
  if exists (select 1 from public.duel_moves where clip_id = p_clip) then
    raise exception 'This clip is part of a duel, so it can''t move';
  end if;
  if (select count(*) from public.clips where filmed_by = auth.uid() and user_id = p_rider and not rider_ok) >= 10 then
    raise exception 'They already have 10 clips from you waiting. Ask them to check Base.';
  end if;
  delete from public.votes where clip_id = p_clip;
  update public.clips set user_id = p_rider, filmed_by = auth.uid(), rider_ok = false where id = p_clip;
end $$;
revoke execute on function public.give_clip_to_friend(uuid, uuid) from public, anon;
grant execute on function public.give_clip_to_friend(uuid, uuid) to authenticated;

-- Check: should read  1
select count(*) as new_function from pg_proc where proname = 'give_clip_to_friend';
