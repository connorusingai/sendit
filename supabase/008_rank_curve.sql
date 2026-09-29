-- Sendit database, version 8: trick rank on an upward curve.
-- Tier n needs 50 × n × (n+1) points, so each gap is 100 bigger than the last:
--   Bronze 0 · Silver 100 · Gold 300 · Platinum 600 · Diamond 1000 · Legend 1500
-- Replaces the 005 ladder (the trick list roughly doubled in 007).
-- Keep in sync with TRICK_TIERS in app/index.html.
-- Paste into Supabase > SQL Editor and click Run. It only replaces one function.

create or replace function public.vote_weight(pts int) returns numeric
language sql immutable as $$
  select case
    when pts >= 1500 then 2.25  -- Legend
    when pts >= 1000 then 2.0   -- Diamond
    when pts >= 600  then 1.75  -- Platinum
    when pts >= 300  then 1.5   -- Gold
    when pts >= 100  then 1.25  -- Silver
    else 1.0                    -- Bronze
  end
$$;

-- Check: should read 1.25 | 2 | 2.25
select vote_weight(100) as silver, vote_weight(1000) as diamond, vote_weight(1500) as legend;
