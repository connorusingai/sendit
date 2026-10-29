-- Stomped database, version 28: one invite link per crew (Connor, Oct 28).
-- The link is getstomped.app/app/?crew=CODE (the crew's existing 6-letter code from 010, so old codes keep working).
-- Tapping it, even from iMessage or an Instagram DM, opens Stomped, signs you up or in, and puts you in the crew.
--   1. crew_invite_info(code): the crew's name, tag and size, so the sign-up screen can say "You're invited to X".
--      Works signed out. It only answers for a correct code, and never shows the code itself.
--   2. join_crew_link(code, switch): joins the crew. If you're already in another crew it says so, and with
--      switch = true it moves you (leave + join in one step, so a full or wrong crew never leaves you crewless).
--   3. Backstop: the app also puts the code in the new account's sign-up info. When the account is created the
--      database joins the crew right away, so it still works if sign-up finishes in a different browser.
--      If anything goes wrong there, sign-up still succeeds (it just skips the crew).
-- Paste into Supabase > SQL Editor and click Run. No existing data is changed.

-- ---------- 1. who invited me? ----------
create or replace function public.crew_invite_info(p_code text)
returns table (name text, tag text, members int)
language sql stable security definer set search_path = public as $$
  select c.name, c.tag, (select count(*)::int from public.crew_members m where m.crew_id = c.id)
    from public.crews c
   where c.code = upper(btrim(p_code))
$$;
grant execute on function public.crew_invite_info(text) to anon, authenticated;

-- ---------- 2. join from the link ----------
create or replace function public.join_crew_link(p_code text, p_switch boolean default false) returns uuid
language plpgsql security definer set search_path = public as $$
declare
  me uuid := auth.uid();
  target uuid;
  cur uuid;
begin
  if me is null then raise exception 'Sign in first.'; end if;
  select c.id into target from public.crews c where c.code = upper(btrim(p_code));
  if target is null then raise exception 'That invite link is old or mistyped. Ask your friend for a new one.'; end if;
  select crew_id into cur from public.crew_members where user_id = me;
  if cur = target then return target; end if;                       -- already in it
  if (select count(*) from public.crew_members where crew_id = target) >= 50 then
    raise exception 'That crew is full (50 riders).';
  end if;
  if cur is not null then
    if not p_switch then raise exception 'Already in a crew.'; end if;  -- the app asks "Switch crews?" first
    perform public.leave_crew();
  end if;
  insert into public.crew_members (user_id, crew_id) values (me, target);
  return target;
end $$;
revoke execute on function public.join_crew_link(text, boolean) from public, anon;
grant execute on function public.join_crew_link(text, boolean) to authenticated;

-- ---------- 3. backstop: join at sign-up ----------
-- Runs right after on_auth_user_created (001) makes the profile (same-moment triggers run in name order).
create or replace function public.join_invited_crew() returns trigger
language plpgsql security definer set search_path = public as $$
declare target uuid;
begin
  begin
    select c.id into target from public.crews c
     where c.code = upper(btrim(new.raw_user_meta_data->>'crew'));
    if target is not null and (select count(*) from public.crew_members where crew_id = target) < 50 then
      insert into public.crew_members (user_id, crew_id) values (new.id, target) on conflict (user_id) do nothing;
    end if;
  exception when others then
    null;   -- never block a sign-up over a crew
  end;
  return new;
end $$;
revoke execute on function public.join_invited_crew() from public, anon, authenticated;
drop trigger if exists on_auth_user_joins_crew on auth.users;
create trigger on_auth_user_joins_crew
  after insert on auth.users
  for each row when (new.raw_user_meta_data ? 'crew')
  execute function public.join_invited_crew();

-- Check: should read  3 | t
select (select count(*) from pg_proc where proname in ('crew_invite_info', 'join_crew_link', 'join_invited_crew')) as functions_of_3,
       exists (select 1 from pg_trigger where tgname = 'on_auth_user_joins_crew') as signup_backstop_on;
