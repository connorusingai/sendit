-- Sendit database, version 4: one and done.
-- A trick pays points only the FIRST time it's verified for you. Repeats pay 0.
-- Grabs don't make it a new trick (a Mute 360 and a Safety 360 are both a 360).
-- One exception, so Trick of the Day still matters to riders who already have it:
-- a repeat of the Trick of the Day pays normal points, once, on the day it's featured.
-- Paste into Supabase > SQL Editor and click Run. It only replaces functions, so no data changes.
-- Safe to run again if you already ran an earlier version of this file.

drop function if exists public.repeat_multiplier(int);

-- Has this rider already been verified on this trick (not counting this clip)?
create or replace function public.already_landed(p_user uuid, p_trick text, p_clip uuid) returns boolean
language sql stable set search_path = public as $$
  select exists (select 1 from public.clips
                  where user_id = p_user and trick_id = p_trick and status = 'verified' and id <> p_clip)
$$;

create or replace function public.resolve_clip() returns trigger
language plpgsql security definer set search_path = public as $$
declare
  yes_w   numeric;
  total_w numeric;
  c       public.clips%rowtype;
  base    numeric;
  award   int;
begin
  select * into c from public.clips where id = new.clip_id for update;
  if c.status <> 'pending' then return new; end if;

  select coalesce(sum(vote_weight(p.points) * (v.landed)::int), 0),
         coalesce(sum(vote_weight(p.points)), 0)
    into yes_w, total_w
    from public.votes v join public.profiles p on p.id = v.voter_id
   where v.clip_id = c.id;

  if total_w < 5 then return new; end if;

  if yes_w / total_w >= 0.7 then
    select t.pts * case when c.grab <> 'No grab' then 1.2 else 1 end
      into base from public.tricks t where t.id = c.trick_id;

    if not already_landed(c.user_id, c.trick_id, c.id) then
      award := round(base * case when c.totd then 2 else 1 end);    -- new trick: full points (2x on Trick of the Day)
    elsif c.totd and not exists (
        select 1 from public.clips x
         where x.user_id = c.user_id and x.trick_id = c.trick_id and x.totd and x.status = 'verified'
           and x.points_awarded > 0 and x.id <> c.id
           and (x.created_at at time zone 'America/Denver')::date = (c.created_at at time zone 'America/Denver')::date) then
      award := round(base);                                          -- Trick of the Day repeat: normal points, once that day
    else
      award := 0;                                                    -- repeat: counts, but no points
    end if;

    update public.clips set status = 'verified', points_awarded = award, verified_at = now() where id = c.id;
    update public.profiles set points = points + award where id = c.user_id;
  else
    update public.clips set status = 'rejected' where id = c.id;
  end if;
  return new;
end $$;

-- Check: should read  t
select exists (select 1 from pg_proc where proname = 'already_landed') as ready;
