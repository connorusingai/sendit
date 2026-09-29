-- Sendit database, version 5: an easier start, a harder top.
-- Trick rank thresholds, with each gap 50 points bigger than the last:
--   Bronze 0 · Silver 100 · Gold 250 · Platinum 450 · Diamond 700 · Legend 1000
-- Vote weight follows trick rank, so it has to move with the new thresholds.
-- Keep these numbers in sync with TRICK_TIERS in app/index.html.
-- Paste into Supabase > SQL Editor and click Run. It only replaces one function.

create or replace function public.vote_weight(pts int) returns numeric
language sql immutable as $$
  select case
    when pts >= 1000 then 2.25  -- Legend
    when pts >= 700  then 2.0   -- Diamond
    when pts >= 450  then 1.75  -- Platinum
    when pts >= 250  then 1.5   -- Gold
    when pts >= 100  then 1.25  -- Silver
    else 1.0                    -- Bronze
  end
$$;

-- Check: should read 1 | 1.25 | 2.25
select vote_weight(0) as bronze, vote_weight(100) as silver, vote_weight(1000) as legend;
