-- Sendit database, version 6: new grabs on a trick you already have pay just the grab.
--   New trick                   = base × 1.2 if grabbed (× 2 on Trick of the Day)
--   Same trick, new grab        = the grab's worth only: 20% of base (× 2 on Trick of the Day)
--   Exact repeat (trick + grab) = 0, except a Trick of the Day repeat pays base once that day
-- Paste into Supabase > SQL Editor and click Run. It only replaces one function, so no data changes.

create or replace function public.resolve_clip() returns trigger
language plpgsql security definer set search_path = public as $$
declare
  yes_w     numeric;
  total_w   numeric;
  c         public.clips%rowtype;
  base      numeric;
  totd_x    numeric;
  award     int;
  has_trick boolean;
  has_grab  boolean;
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
    select t.pts into base from public.tricks t where t.id = c.trick_id;
    totd_x := case when c.totd then 2 else 1 end;

    -- What has this rider already been verified on (not counting this clip)?
    select exists (select 1 from public.clips where user_id = c.user_id and trick_id = c.trick_id
                     and status = 'verified' and id <> c.id),
           exists (select 1 from public.clips where user_id = c.user_id and trick_id = c.trick_id
                     and grab = c.grab and status = 'verified' and id <> c.id)
      into has_trick, has_grab;

    if not has_trick then
      award := round(base * case when c.grab <> 'No grab' then 1.2 else 1 end * totd_x);  -- brand new trick
    elsif c.grab <> 'No grab' and not has_grab then
      award := round(base * 0.2 * totd_x);                                                  -- new grab on a known trick
    elsif c.totd and not exists (
        select 1 from public.clips x
         where x.user_id = c.user_id and x.trick_id = c.trick_id and x.totd and x.status = 'verified'
           and x.points_awarded > 0 and x.id <> c.id
           and (x.created_at at time zone 'America/Denver')::date = (c.created_at at time zone 'America/Denver')::date) then
      award := round(base);                                                                 -- Trick of the Day repeat, once
    else
      award := 0;                                                                           -- exact repeat
    end if;

    update public.clips set status = 'verified', points_awarded = award, verified_at = now() where id = c.id;
    update public.profiles set points = points + award where id = c.user_id;
  else
    update public.clips set status = 'rejected' where id = c.id;
  end if;
  return new;
end $$;

-- already_landed() from 004 is no longer used.
drop function if exists public.already_landed(uuid, text, uuid);

-- Check: should read  t
select exists (select 1 from pg_proc where proname = 'resolve_clip') as ready;
