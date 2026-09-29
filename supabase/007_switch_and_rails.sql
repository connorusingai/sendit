-- Sendit database, version 7: switch tricks and a full set of rail tricks.
-- Switch versions of spins and flips are worth about 30% more than the regular trick.
-- Paste into Supabase > SQL Editor and click Run. It only adds tricks.

insert into public.tricks (id, name, category, pts, sport) values
  -- Ski: switch spins and flips
  ('sw180','Switch 180','Park',13,'ski'), ('sw360','Switch 360','Park',26,'ski'),
  ('sw540','Switch 540','Park',46,'ski'), ('sw720','Switch 720','Park',65,'ski'),
  ('swbackflip','Switch Backflip','Park',78,'ski'), ('swcork720','Switch Cork 720','Park',91,'ski'),
  ('swdc1080','Switch Double Cork 1080','Park',156,'ski'),
  -- Ski: rails
  ('5050','50-50','Rails',8,'ski'), ('nosepress','Nose Press','Rails',20,'ski'),
  ('tailpress','Tail Press','Rails',20,'ski'), ('swboard','Switch Boardslide','Rails',20,'ski'),
  ('swlip','Switch Lipslide','Rails',32,'ski'), ('270out','270 Out','Rails',40,'ski'),
  ('sw270on','Switch 270 On','Rails',52,'ski'), ('blind270','Blind 270 On','Rails',55,'ski'),
  ('pretzel270','Pretzel 270 Out','Rails',55,'ski'), ('450out','450 Out','Rails',55,'ski'),
  -- Snowboard: switch spins (a "Cab" is a switch frontside spin)
  ('sb-halfcab','Half-Cab','Park',13,'snowboard'), ('sb-cab360','Cab 360','Park',26,'snowboard'),
  ('sb-swbs360','Switch Backside 360','Park',29,'snowboard'), ('sb-swbs540','Switch Backside 540','Park',46,'snowboard'),
  ('sb-cab720','Cab 720','Park',65,'snowboard'), ('sb-swbackflip','Switch Backflip','Park',78,'snowboard'),
  ('sb-cabdc1080','Cab Double Cork 1080','Park',156,'snowboard'),
  -- Snowboard: rails
  ('sb-sw5050','Switch 50-50','Rails',13,'snowboard'), ('sb-bsboard','Backside Boardslide','Rails',20,'snowboard'),
  ('sb-nosepress','Nose Press','Rails',20,'snowboard'), ('sb-tailpress','Tail Press','Rails',20,'snowboard'),
  ('sb-50','5-0','Rails',20,'snowboard'), ('sb-swboard','Switch Boardslide','Rails',20,'snowboard'),
  ('sb-noseslide','Nose Slide','Rails',25,'snowboard'), ('sb-tailslide','Tail Slide','Rails',25,'snowboard'),
  ('sb-bslip','Backside Lipslide','Rails',30,'snowboard'), ('sb-switchup','Switch-Up','Rails',45,'snowboard'),
  ('sb-bs270on','Backside 270 On','Rails',45,'snowboard'), ('sb-fs270out','Frontside 270 Out','Rails',45,'snowboard'),
  ('sb-blunt','Blunt Slide','Rails',45,'snowboard');

-- Check: should read  17 | 20
select (select count(*) from public.tricks where sport = 'ski'       and id in
          ('sw180','sw360','sw540','sw720','swbackflip','swcork720','swdc1080','5050','nosepress','tailpress',
           'swboard','swlip','270out','sw270on','blind270','pretzel270','450out')) as ski_added_of_17,
       (select count(*) from public.tricks where sport = 'snowboard' and id like 'sb-%'
          and id in ('sb-halfcab','sb-cab360','sb-swbs360','sb-swbs540','sb-cab720','sb-swbackflip','sb-cabdc1080',
           'sb-sw5050','sb-bsboard','sb-nosepress','sb-tailpress','sb-50','sb-swboard','sb-noseslide','sb-tailslide',
           'sb-bslip','sb-switchup','sb-bs270on','sb-fs270out','sb-blunt')) as snowboard_added_of_20;
