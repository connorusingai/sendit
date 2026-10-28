-- Stomped database, version 20: your clip has to use YOUR video (security fix, Oct 27).
-- The hole: posting your own clip never checked video_path. Anyone could copy a pro's
-- landed Double Cork from the feed (paths are public), post it as their own clip,
-- and collect the points when judges verify it. "../" tricks and web links got through too,
-- including through Film a friend (017 only checked the first folder name).
-- Now every new clip's video must be '<owner id>/<name>.mp4|mov|webm', where the owner is
-- the filmer for Film a friend clips and the rider otherwise.
-- Paste into Supabase > SQL Editor and click Run. No existing data is changed.

create or replace function public.check_video_path() returns trigger
language plpgsql set search_path = public as $$
begin
  if new.video_path is not null and (
       split_part(new.video_path, '/', 1) <> coalesce(new.filmed_by, new.user_id)::text
    or new.video_path !~ '^[0-9a-f-]{36}/[A-Za-z0-9_-]+\.(mp4|mov|webm)$') then
    raise exception 'That video isn''t yours';
  end if;
  return new;
end $$;

drop trigger if exists check_video_path on public.clips;
create trigger check_video_path before insert on public.clips
  for each row execute function public.check_video_path();

-- Check: should read  1 | 0   (the 0 = clips already posted with someone else's video)
select (select count(*) from pg_trigger where tgname = 'check_video_path') as new_trigger,
       (select count(*) from public.clips
         where video_path is not null
           and split_part(video_path, '/', 1) <> coalesce(filmed_by, user_id)::text) as stolen_videos;
