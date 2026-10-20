-- Stomped database, version 12: in-app feedback for the friend test and beta.
--   Riders tap "Send feedback" (Leaderboard tab > Your profile), pick bug / confusing / idea / love it,
--   and write a line. Only the rider who sent it can read it back; Connor reads everything in
--   Supabase > Table Editor > feedback (the dashboard bypasses these rules).
--   Limit: 20 per rider per day, so one person can't flood it.
-- Paste into Supabase > SQL Editor and click Run. No existing data is changed.

create table if not exists public.feedback (
  id         bigint generated always as identity primary key,
  user_id    uuid not null default auth.uid() references public.profiles on delete cascade,
  kind       text not null check (kind in ('bug', 'confusing', 'idea', 'love')),
  body       text not null check (char_length(btrim(body)) between 1 and 1000),
  page       text check (char_length(page) <= 40),       -- which tab they were on, to find bugs faster
  created_at timestamptz not null default now()
);

alter table public.feedback enable row level security;
drop policy if exists "send feedback as yourself" on public.feedback;
create policy "send feedback as yourself" on public.feedback for insert to authenticated
  with check (user_id = auth.uid());
drop policy if exists "read your own feedback" on public.feedback;
create policy "read your own feedback" on public.feedback for select to authenticated
  using (user_id = auth.uid());
revoke update, delete on public.feedback from anon, authenticated;

create or replace function public.feedback_per_day() returns int
language sql immutable as $$ select 20 $$;

create or replace function public.limit_feedback() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if (select count(*) from public.feedback
       where user_id = new.user_id and created_at > now() - interval '1 day') >= public.feedback_per_day() then
    raise exception 'feedback limit reached for today';
  end if;
  return new;
end $$;

drop trigger if exists feedback_limit on public.feedback;
create trigger feedback_limit before insert on public.feedback
  for each row execute function public.limit_feedback();
