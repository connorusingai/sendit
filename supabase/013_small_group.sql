-- Stomped database, version 13: let a small group verify each other.
--   A clip needed 3 vote weight, and a new (Bronze) rider's vote weighs 1. You can't judge your own clip,
--   so in a 3-person friend test every clip could get at most 2 votes and NOTHING would ever be verified.
--   Now 2 is enough. The 70% rule still applies, so with 2 judges both have to say "landed".
--   Raise it again once there are more riders (same one line, with 3 or 5).
-- Paste into Supabase > SQL Editor and click Run. No existing data is changed.

create or replace function public.need_weight() returns numeric
language sql immutable as $$ select 2::numeric $$;

-- Check: should read  2
select public.need_weight() as votes_needed;
