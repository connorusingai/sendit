-- Stomped database, version 14: more rail tricks, and rail combos (Connor, Oct 21).
--   1. New rail tricks: Switch 50-50, 180 On, 180 Out, Gap On, Swap, Backswap, Switch 270 Out, 450 On
--      (ski), plus Frontside Boardslide, Frontside Lipslide and Gap On (snowboard).
--   2. A rail clip can chain up to 3 more rail tricks after its first one, e.g. 270 On -> Swap -> 270 Out.
--      The first trick works exactly like before (Trick Book, grabs, Trick of the Day).
--      A NEW chain also pays a combo bonus: half the points of the tricks you added (x2 on Trick of the Day).
--      Landing the exact same chain again pays no bonus.
-- Paste into Supabase > SQL Editor and click Run. No existing data is changed.

-- ---------- 1. new rail tricks ----------
insert into public.tricks (id, name, category, pts, sport) values
  ('sw5050','Switch 50-50','Rails',12,'ski'), ('180on','180 On','Rails',18,'ski'),
  ('180out','180 Out','Rails',18,'ski'), ('gapon','Gap On','Rails',25,'ski'),
  ('swap','Swap','Rails',35,'ski'), ('backswap','Backswap','Rails',45,'ski'),
  ('sw270out','Switch 270 Out','Rails',52,'ski'), ('450on','450 On','Rails',60,'ski'),
  ('sb-fsboard','Frontside Boardslide','Rails',15,'snowboard'), ('sb-fslip','Frontside Lipslide','Rails',25,'snowboard'),
  ('sb-gapon','Gap On','Rails',25,'snowboard')
on conflict (id) do nothing;

-- ---------- 2. combos ----------
-- The tricks after the first one, in order. Empty = a normal single-trick clip.
alter table public.clips add column if not exists combo text[] not null default '{}';
grant insert (combo) on public.clips to authenticated;

-- The app can't be trusted to send a sensible chain, so the database checks it.
create or replace function public.check_combo() returns trigger
language plpgsql set search_path = public as $$
declare first public.tricks%rowtype;
begin
  new.combo := coalesce(new.combo, '{}');
  if cardinality(new.combo) = 0 then return new; end if;
  select * into first from public.tricks where id = new.trick_id;
  if first.category <> 'Rails' then raise exception 'Combos are only for rail tricks'; end if;
  if cardinality(new.combo) > 3 then raise exception 'A rail combo can have at most 4 tricks'; end if;
  if exists (select 1 from unnest(new.combo) x
              where x not in (select id from public.tricks where category = 'Rails' and sport = first.sport)) then
    raise exception 'Every trick in a combo has to be a rail trick from the same sport';
  end if;
  if new.trick_id = any(new.combo) or (select count(distinct x) from unnest(new.combo) x) <> cardinality(new.combo) then
    raise exception 'Each trick can only be in a combo once';
  end if;
  return new;
end $$;
drop trigger if exists check_combo on public.clips;
create trigger check_combo before insert on public.clips
  for each row execute function public.check_combo();

-- Same rules as 011, plus the combo bonus at the end.
create or replace function public.resolve_clip() returns trigger
language plpgsql security definer set search_path = public as $$
declare
  yes_w     numeric;
  total_w   numeric;
  c         public.clips%rowtype;
  base      numeric;
  extra     numeric;
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

  if total_w < public.need_weight() then return new; end if;

  if yes_w / total_w >= 0.7 then
    select t.pts into base from public.tricks t where t.id = c.trick_id;
    totd_x := case when c.totd then 2 else 1 end;

    select exists (select 1 from public.clips where user_id = c.user_id and trick_id = c.trick_id
                     and status = 'verified' and id <> c.id),
           exists (select 1 from public.clips where user_id = c.user_id and trick_id = c.trick_id
                     and grab = c.grab and status = 'verified' and id <> c.id)
      into has_trick, has_grab;

    if not has_trick then
      award := round(base * case when c.grab <> 'No grab' then 1.2 else 1 end * totd_x);
    elsif c.grab <> 'No grab' and not has_grab then
      award := round(base * 0.2 * totd_x);
    elsif c.totd and not exists (
        select 1 from public.clips x
         where x.user_id = c.user_id and x.trick_id = c.trick_id and x.totd and x.status = 'verified'
           and x.points_awarded > 0 and x.id <> c.id
           and (x.created_at at time zone 'America/Denver')::date = (c.created_at at time zone 'America/Denver')::date) then
      award := round(base);
    else
      award := 0;
    end if;

    -- Combo bonus: a chain you haven't been verified on before pays half the points of the added tricks.
    if cardinality(c.combo) > 0 and not exists (
        select 1 from public.clips where user_id = c.user_id and trick_id = c.trick_id and combo = c.combo
           and status = 'verified' and id <> c.id) then
      select coalesce(sum(t.pts), 0) into extra from public.tricks t where t.id = any(c.combo);
      award := award + round(extra * 0.5 * totd_x);
    end if;

    update public.clips set status = 'verified', points_awarded = award, verified_at = now() where id = c.id;
    update public.profiles set points = points + award where id = c.user_id;
  else
    update public.clips set status = 'rejected' where id = c.id;
  end if;
  return new;
end $$;

-- Check: should read  11 | t | t
select (select count(*) from public.tricks where id in ('sw5050','180on','180out','gapon','swap','backswap','sw270out',
          '450on','sb-fsboard','sb-fslip','sb-gapon')) as new_tricks_of_11,
       exists (select 1 from information_schema.columns where table_name = 'clips' and column_name = 'combo') as combo_ready,
       exists (select 1 from pg_trigger where tgname = 'check_combo') as check_ready;
