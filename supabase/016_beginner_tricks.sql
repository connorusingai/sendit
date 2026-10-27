-- Stomped database, version 16: beginner tricks + an easier Trick of the Day (Connor, Oct 27).
--   1. New easy tricks so riders who only do small spins aren't stuck at Silver: straight airs, shifties,
--      butters, nose/tail taps (both sports), Ollie + the missing Frontside 180 (snowboard).
--   2. Trick of the Day: one per sport (skiers never get a snowboard trick), and only Park and Rails tricks
--      worth 60 points or less (up to a backflip). No moguls, pipe or backcountry, and no double corks.
-- Paste into Supabase > SQL Editor and click Run. No existing data is changed.
-- Note: today's Trick of the Day may switch to a new trick right after you run this.

-- ---------- 1. beginner tricks ----------
insert into public.tricks (id, name, category, pts, sport) values
  ('straightair','Straight Air','Park',5,'ski'), ('shifty','Shifty','Park',5,'ski'),
  ('daffy','Daffy','Park',6,'ski'), ('butter180','Butter 180','Park',8,'ski'),
  ('butter360','Butter 360','Park',15,'ski'),
  ('nosetap','Nose Tap','Rails',8,'ski'), ('tailtap','Tail Tap','Rails',8,'ski'),
  ('sb-ollie','Ollie','Park',5,'snowboard'), ('sb-straightair','Straight Air','Park',5,'snowboard'),
  ('sb-shifty','Shifty','Park',5,'snowboard'), ('sb-fs180','Frontside 180','Park',10,'snowboard'),
  ('sb-butter180','Butter 180','Park',8,'snowboard'), ('sb-butter360','Butter 360','Park',15,'snowboard'),
  ('sb-nosetap','Nose Tap','Rails',8,'snowboard'), ('sb-tailtap','Tail Tap','Rails',8,'snowboard')
on conflict (id) do nothing;

-- ---------- 2. Trick of the Day: one per sport, tricks most riders can actually try ----------
-- Same daily shuffle as 002, from a shorter list. Skiers get a ski trick, snowboarders a snowboard trick.
-- Called with no arguments it still works (ski), so the old app keeps running until the new one loads.
drop function if exists public.trick_of_day(date);
create function public.trick_of_day(sp text default 'ski', d date default (now() at time zone 'America/Denver')::date)
returns text language sql stable set search_path = public as $$
  select id from public.tricks
   where sport = sp and category in ('Park','Rails') and pts <= 60
   order by md5(id || d::text) limit 1
$$;
grant execute on function public.trick_of_day(text, date) to anon, authenticated;

-- A clip earns 2x when it's the Trick of the Day for ITS sport.
create or replace function public.stamp_totd() returns trigger
language plpgsql set search_path = public as $$
begin
  new.totd := (new.trick_id = public.trick_of_day((select sport from public.tricks where id = new.trick_id)));
  return new;
end $$;

-- Check: should read  7 | 8 | 0
select (select count(*) from public.tricks where id in
          ('straightair','shifty','daffy','butter180','butter360','nosetap','tailtap')) as ski_new,
       (select count(*) from public.tricks where id like 'sb-%' and id in
          ('sb-ollie','sb-straightair','sb-shifty','sb-fs180','sb-butter180','sb-butter360','sb-nosetap','sb-tailtap')) as board_new,
       (select count(*) from generate_series(0, 365) g cross join (values ('ski'), ('snowboard')) s(sp)
          join public.tricks t on t.id = public.trick_of_day(s.sp, current_date + g)
         where t.sport <> s.sp or t.category not in ('Park','Rails') or t.pts > 60) as bad_totd_days;
