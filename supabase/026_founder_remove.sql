-- 026: the founder can remove any clip or pass photo, and sees everything riders reported (#4, 2026-10-28).
-- NOT pasted yet: Connor pastes it in the Supabase SQL Editor (after 024 and 025).
-- "Founder" = rider #001, or anyone 027 (judge-invite) marks is_founder. See am_founder() in 024.

-- Take a clip down for everyone. Returns its video path so the app deletes the file too.
create or replace function public.founder_remove_clip(p_clip uuid) returns text
language plpgsql security definer set search_path = public as $$
declare path text;
begin
  if not public.am_founder() then raise exception 'Founder only'; end if;
  update public.clips set hidden = true where id = p_clip returning video_path into path;
  if not found then raise exception 'No such clip'; end if;
  return path;
end $$;
revoke execute on function public.founder_remove_clip(uuid) from public, anon;
grant execute on function public.founder_remove_clip(uuid) to authenticated;

-- Take a pass photo down. Returns the photo's path so the app deletes the file too.
create or replace function public.founder_remove_photo(p_user uuid) returns text
language plpgsql security definer set search_path = public as $$
declare path text;
begin
  if not public.am_founder() then raise exception 'Founder only'; end if;
  select pass_photo into path from public.profiles where id = p_user;
  update public.profiles set pass_photo = null where id = p_user;
  return path;
end $$;
revoke execute on function public.founder_remove_photo(uuid) from public, anon;
grant execute on function public.founder_remove_photo(uuid) to authenticated;

-- The founder may delete any clip video or pass photo file (riders can still only delete their own)
drop policy if exists "founder removes files" on storage.objects;
create policy "founder removes files" on storage.objects for delete to authenticated
  using (bucket_id in ('clips', 'passes') and public.am_founder());

-- Everything reported, one row per thing, most reported first:
-- kind (clip / comment / photo), id (clip, comment or rider id), whose it is, how many reports, the reasons, hidden yet?
create or replace function public.founder_reports() returns jsonb
language plpgsql stable security definer set search_path = public as $$
begin
  if not public.am_founder() then raise exception 'Founder only'; end if;
  return coalesce((select jsonb_agg(x order by x.reports desc, x.last desc) from (
    select 'clip' as kind, r.clip_id as id, p.username as owner, count(*) as reports,
           string_agg(distinct r.reason, ', ') as reasons, bool_or(c.hidden) as hidden, max(r.created_at) as last
      from public.reports r join public.clips c on c.id = r.clip_id join public.profiles p on p.id = c.user_id
     group by r.clip_id, p.username
    union all
    select 'comment', r.comment_id, p.username, count(*), string_agg(distinct r.reason, ', '), bool_or(m.hidden), max(r.created_at)
      from public.reports r join public.comments m on m.id = r.comment_id join public.profiles p on p.id = m.user_id
     group by r.comment_id, p.username
    union all
    select 'photo', r.profile_id, p.username, count(*), string_agg(distinct r.reason, ', '), bool_or(p.pass_photo is null), max(r.created_at)
      from public.reports r join public.profiles p on p.id = r.profile_id
     group by r.profile_id, p.username
  ) x), '[]'::jsonb);
end $$;
revoke execute on function public.founder_reports() from public, anon;
grant execute on function public.founder_reports() to authenticated;

-- "Keep": the founder looked and it's fine. Clears its reports and un-hides a clip or comment.
-- (A photo that 3 reports took down stays down; the rider just picks it again.)
create or replace function public.founder_keep(p_kind text, p_id uuid) returns void
language plpgsql security definer set search_path = public as $$
begin
  if not public.am_founder() then raise exception 'Founder only'; end if;
  if p_kind = 'clip' then
    delete from public.reports where clip_id = p_id; update public.clips set hidden = false where id = p_id;
  elsif p_kind = 'comment' then
    delete from public.reports where comment_id = p_id; update public.comments set hidden = false where id = p_id;
  elsif p_kind = 'photo' then
    delete from public.reports where profile_id = p_id;
  else raise exception 'Unknown kind'; end if;
end $$;
revoke execute on function public.founder_keep(text, uuid) from public, anon;
grant execute on function public.founder_keep(text, uuid) to authenticated;

-- Check: should read  4
select count(*) as founder_tools from pg_proc
 where proname in ('founder_remove_clip', 'founder_remove_photo', 'founder_reports', 'founder_keep');
