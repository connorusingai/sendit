-- Sendit database, version 9: "Boardslide" isn't a ski trick name.
-- Rename the two ski versions. Snowboard keeps Boardslide. Only names change, so clips are unaffected.
-- Paste into Supabase > SQL Editor and click Run.

update public.tricks set name = 'Rail Slide'        where id = 'board'   and sport = 'ski';
update public.tricks set name = 'Switch Rail Slide' where id = 'swboard' and sport = 'ski';

-- Check: should read  Rail Slide | Switch Rail Slide
select (select name from public.tricks where id = 'board')   as ski_slide,
       (select name from public.tricks where id = 'swboard') as ski_switch_slide;
