-- Stomped database, version 29: fixes from the 11/10 audit. NOT pasted yet: Connor pastes it in the Supabase SQL Editor.
--   1. Deleting really deletes. The app could never SEE its own files in storage (there was a rule for adding
--      and a rule for deleting, but none for looking), and Supabase needs "look" for both listing and deleting.
--      So "Delete clip" and "Delete account" left the videos online. Now you can see (only) your own files.
--   2. Comments: the 280 limit could be dodged by padding with spaces (megabytes of them). Now the comment is
--      trimmed and the real length is checked. Plus a speed limit: 10 comments a minute, 200 a day per rider.
--      Feedback gets the same real-length limit (1000).
--   3. Usernames: the app only allowed letters, numbers, _ . - but the database allowed anything, and "Connor"
--      and "connor" could both exist (an easy way to pose as someone). Now the database checks both.
--   4. Game of S.K.I.: "landed" accepted ANY clip of yours as proof, even an old one of a different trick, over
--      and over. Now the clip has to be that trick, filmed in the last 24 hours, and not used in a duel before.
--   5. Riders could back-date their own activity-log rows and reports. Now the database always stamps the time.
--   6. A pass photo path had to start with your id, but could then wander off ("../"). Now it must be one plain file.
-- Paste into Supabase > SQL Editor and click Run. No existing data is changed. Safe to run twice.

-- ---------- 1. see your own files, so the app can list and delete them ----------
drop policy if exists "see your own files" on storage.objects;
create policy "see your own files" on storage.objects for select to authenticated
  using (bucket_id in ('clips', 'passes')
         and ((storage.foldername(name))[1] = auth.uid()::text or public.am_founder()));

-- ---------- 2. comments: real length + a speed limit ----------
create or replace function public.tidy_comment() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  new.body := btrim(new.body, E' \t\n\r');
  if char_length(new.body) < 1 or char_length(new.body) > 280 then
    raise exception 'Comments are 1 to 280 characters.';
  end if;
  if (select count(*) from public.comments
       where user_id = new.user_id and created_at > now() - interval '1 minute') >= 10 then
    raise exception 'Slow down. You can comment again in a minute.';
  end if;
  if (select count(*) from public.comments
       where user_id = new.user_id and created_at > now() - interval '1 day') >= 200 then
    raise exception 'That is a lot of comments for one day. Try again tomorrow.';
  end if;
  return new;
end $$;
revoke execute on function public.tidy_comment() from public, anon, authenticated;
drop trigger if exists tidy_comment on public.comments;
create trigger tidy_comment before insert on public.comments
  for each row execute function public.tidy_comment();

alter table public.feedback drop constraint if exists feedback_body_max;
alter table public.feedback add constraint feedback_body_max check (char_length(body) <= 1000) not valid;

-- ---------- 3. usernames: same rule as the app, and no look-alike capitals ----------
create or replace function public.check_username() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if tg_op = 'UPDATE' and new.username is not distinct from old.username then return new; end if;
  if new.username !~ '^[A-Za-z0-9_.-]{3,24}$' then
    raise exception 'Username: 3 to 24 letters, numbers, _ . or -';
  end if;
  if exists (select 1 from public.profiles where lower(username) = lower(new.username) and id <> new.id) then
    raise exception 'That username is taken.' using errcode = '23505';
  end if;
  return new;
end $$;
revoke execute on function public.check_username() from public, anon, authenticated;
drop trigger if exists check_username on public.profiles;
create trigger check_username before insert or update of username on public.profiles
  for each row execute function public.check_username();

-- A second lock for two sign-ups in the same instant. Skipped (with a note) if two riders already
-- share a name in different capitals; the trigger above still protects every new name.
do $$
begin
  create unique index if not exists profiles_username_lower on public.profiles (lower(username));
exception when unique_violation then
  raise notice 'Two riders already share a username in different capitals, so the extra index was skipped.';
end $$;

-- ---------- 4. Game of S.K.I.: proof has to be a fresh clip of that trick ----------
-- Same as 003, plus the three checks marked NEW.
create or replace function public.duel_move(p_duel uuid, p_landed boolean, p_trick text default null, p_clip uuid default null)
returns void
language plpgsql security definer set search_path = public as $$
declare
  me         uuid := auth.uid();
  d          public.duels%rowtype;
  cl         public.clips%rowtype;
  other      uuid;
  my_letters int;
begin
  select * into d from public.duels where id = p_duel for update;
  if not found or me is null or me not in (d.challenger, d.opponent) then raise exception 'Duel not found'; end if;
  if d.status <> 'active' then raise exception 'This duel is over'; end if;
  if d.turn <> me then raise exception 'Not your turn'; end if;
  if p_landed and p_clip is null then raise exception 'Record your attempt to prove you landed it'; end if;
  if p_clip is not null then
    select * into cl from public.clips where id = p_clip and user_id = me;
    if not found then raise exception 'That clip is not yours'; end if;
    -- NEW (029): the right trick, filmed for this turn, never used before
    if cl.trick_id is distinct from (case when d.phase = 'set' then p_trick else d.trick_id end) then
      raise exception 'That clip is a different trick';
    end if;
    if cl.created_at < now() - interval '24 hours' then
      raise exception 'Film a fresh attempt for this duel';
    end if;
    if exists (select 1 from public.duel_moves where clip_id = p_clip) then
      raise exception 'That clip was already used in a duel';
    end if;
  end if;
  other := case when me = d.challenger then d.opponent else d.challenger end;

  if d.phase = 'set' then
    if p_trick is null or not exists (select 1 from public.tricks where id = p_trick) then
      raise exception 'Pick a trick';
    end if;
    insert into public.duel_moves (duel_id, user_id, kind, trick_id, clip_id, landed)
    values (d.id, me, 'set', p_trick, p_clip, p_landed);
    -- Landed: the other skier has to match it. Bailed: they get to set instead.
    update public.duels
       set phase = case when p_landed then 'match' else 'set' end,
           trick_id = case when p_landed then p_trick else null end,
           turn = other, updated_at = now()
     where id = d.id;
  else
    insert into public.duel_moves (duel_id, user_id, kind, trick_id, clip_id, landed)
    values (d.id, me, 'match', d.trick_id, p_clip, p_landed);
    if not p_landed then
      update public.duels
         set letters_challenger = letters_challenger + (me = d.challenger)::int,
             letters_opponent   = letters_opponent   + (me = d.opponent)::int
       where id = d.id;
    end if;
    select case when me = challenger then letters_challenger else letters_opponent end
      into my_letters from public.duels where id = d.id;
    if my_letters >= 3 then
      perform public.end_duel(d.id, other, me);  -- I spelled S-K-I
    else
      -- The setter keeps control and sets again
      update public.duels set phase = 'set', trick_id = null, turn = other, updated_at = now() where id = d.id;
    end if;
  end if;
end $$;
revoke execute on function public.duel_move(uuid, boolean, text, uuid) from public, anon;
grant execute on function public.duel_move(uuid, boolean, text, uuid) to authenticated;

-- ---------- 5. the database stamps the time, not the phone ----------
revoke insert on public.events from anon, authenticated;
grant insert (name, detail) on public.events to authenticated;
revoke insert on public.reports from anon, authenticated;
grant insert (clip_id, comment_id, profile_id, reason) on public.reports to authenticated;

-- ---------- 6. a pass photo is one plain file in your own folder ----------
create or replace function public.check_pass_photo() returns trigger
language plpgsql as $$
begin
  if new.pass_photo is not null and new.pass_photo is distinct from old.pass_photo
     and new.pass_photo !~ ('^' || new.id::text || '/[A-Za-z0-9_-]+\.(jpg|jpeg|png|webp)$') then
    raise exception 'Pass photo must be your own';
  end if;
  return new;
end $$;

-- Check: should read  1 | 1 | 1 | f | f
select (select count(*) from pg_policies where schemaname = 'storage' and policyname = 'see your own files') as can_see_own_files,
       (select count(*) from pg_trigger where tgname = 'tidy_comment')   as comment_limit,
       (select count(*) from pg_trigger where tgname = 'check_username') as username_check,
       has_column_privilege('authenticated', 'public.events', 'at', 'INSERT')          as riders_set_event_time,
       has_column_privilege('authenticated', 'public.reports', 'created_at', 'INSERT') as riders_set_report_time;
