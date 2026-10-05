-- Model Portfolio Lab: saved portfolios for the "Build your own portfolio" page.
-- Run once in the Supabase SQL editor (Project > SQL Editor > New query > paste > Run).
create table if not exists public.portfolios (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  name text not null default 'Untitled',
  data jsonb not null,
  is_public boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists portfolios_user_idx on public.portfolios (user_id, updated_at desc);

alter table public.portfolios enable row level security;

-- Owners see their own rows; anyone (signed in or not) can read a row its owner has shared.
drop policy if exists "read own or shared" on public.portfolios;
create policy "read own or shared" on public.portfolios for select using (auth.uid() = user_id or is_public);
drop policy if exists "insert own" on public.portfolios;
create policy "insert own" on public.portfolios for insert with check (auth.uid() = user_id);
drop policy if exists "update own" on public.portfolios;
create policy "update own" on public.portfolios for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
drop policy if exists "delete own" on public.portfolios;
create policy "delete own" on public.portfolios for delete using (auth.uid() = user_id);

-- Keep updated_at honest even if a client forgets to set it.
create or replace function public.touch_updated_at() returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end $$;
drop trigger if exists portfolios_touch on public.portfolios;
create trigger portfolios_touch before update on public.portfolios for each row execute function public.touch_updated_at();

-- A saved portfolio is at most 400 KB of JSON (a few dozen holdings with their fetched history).
alter table public.portfolios drop constraint if exists portfolios_data_size;
alter table public.portfolios add constraint portfolios_data_size check (pg_column_size(data) < 400000);

-- Table privileges. Newer Supabase projects no longer grant these automatically, and without them every
-- read and save from the website fails with "permission denied for table portfolios". Row level security
-- above still decides which rows each visitor can see or change.
grant usage on schema public to anon, authenticated;
grant select on public.portfolios to anon;
grant select, insert, update, delete on public.portfolios to authenticated;
