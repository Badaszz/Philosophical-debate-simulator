create table if not exists public.app_settings (
  id text primary key check (id = 'main'),
  restrict_sign_in boolean not null default false
);

insert into public.app_settings (id, restrict_sign_in)
values ('main', false)
on conflict (id) do nothing;

create table if not exists public.allowed_users (
  email text primary key check (email = lower(email)),
  created_at timestamptz not null default now()
);

create table if not exists public.admin_users (
  email text primary key check (email = lower(email)),
  created_at timestamptz not null default now()
);

create table if not exists public.agent_usage (
  user_id uuid primary key references auth.users (id) on delete cascade,
  last_call_at timestamptz not null
);

create table if not exists public.user_request_usage (
  user_id uuid primary key references auth.users (id) on delete cascade,
  email text not null,
  total_requests bigint not null default 0 check (total_requests >= 0),
  daily_requests integer not null default 0 check (daily_requests >= 0),
  daily_date_utc date not null default ((now() at time zone 'UTC')::date),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create or replace function public.track_auth_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if new.email is not null then
    insert into public.user_request_usage (user_id, email)
    values (new.id, lower(new.email))
    on conflict (user_id) do update
      set email = excluded.email,
          updated_at = clock_timestamp();
  end if;
  return new;
end;
$$;

drop trigger if exists track_auth_user_usage on auth.users;
create trigger track_auth_user_usage
after insert or update of email on auth.users
for each row execute function public.track_auth_user();

insert into public.user_request_usage (user_id, email)
select id, lower(email)
from auth.users
where email is not null
on conflict (user_id) do update
  set email = excluded.email,
      updated_at = clock_timestamp();

grant select, insert, update, delete
  on public.app_settings, public.allowed_users, public.admin_users,
     public.agent_usage, public.user_request_usage
  to service_role;
grant usage on schema public to supabase_auth_admin;

alter table public.app_settings enable row level security;
alter table public.allowed_users enable row level security;
alter table public.admin_users enable row level security;
alter table public.agent_usage enable row level security;
alter table public.user_request_usage enable row level security;

drop function if exists public.get_agent_call_status(uuid);
drop function if exists public.claim_agent_call(uuid);

create or replace function public.get_agent_call_status(
  p_user_id uuid,
  p_email text,
  p_enforce_limits boolean
)
returns table (
  total_requests bigint,
  daily_requests integer,
  daily_limit integer,
  daily_remaining integer,
  daily_reset_at timestamptz,
  available_at timestamptz,
  remaining_seconds integer
)
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_total bigint;
  v_daily integer;
  v_today date := (clock_timestamp() at time zone 'UTC')::date;
  v_available_at timestamptz;
  v_reset_at timestamptz := ((v_today + 1)::timestamp at time zone 'UTC');
begin
  insert into public.user_request_usage as u (
    user_id, email, daily_date_utc
  )
  values (p_user_id, lower(p_email), v_today)
  on conflict (user_id) do update
    set email = excluded.email,
        daily_requests = case
          when u.daily_date_utc <> v_today then 0
          else u.daily_requests
        end,
        daily_date_utc = v_today,
        updated_at = clock_timestamp()
  returning u.total_requests, u.daily_requests
    into v_total, v_daily;

  if p_enforce_limits then
    select u.last_call_at + interval '10 minutes'
      into v_available_at
      from public.agent_usage as u
      where u.user_id = p_user_id;

    if v_available_at <= clock_timestamp() then
      v_available_at := null;
    end if;
  end if;

  return query
    select v_total,
      v_daily,
      5,
      greatest(0, 5 - v_daily),
      v_reset_at,
      v_available_at,
      case
        when v_available_at is null then 0
        else greatest(
          1,
          ceil(extract(epoch from (v_available_at - clock_timestamp())))::integer
        )
      end;
end;
$$;

create or replace function public.claim_agent_call(
  p_user_id uuid,
  p_email text,
  p_enforce_limits boolean
)
returns table (
  allowed boolean,
  limit_reason text,
  retry_after_seconds integer,
  available_at timestamptz,
  total_requests bigint,
  daily_requests integer,
  daily_limit integer,
  daily_remaining integer,
  daily_reset_at timestamptz
)
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_now timestamptz := clock_timestamp();
  v_today date := (v_now at time zone 'UTC')::date;
  v_reset_at timestamptz := (((v_now at time zone 'UTC')::date + 1)::timestamp at time zone 'UTC');
  v_total bigint;
  v_daily integer;
  v_available_at timestamptz;
  v_retry_seconds integer;
begin
  insert into public.user_request_usage as u (
    user_id, email, daily_date_utc
  )
  values (p_user_id, lower(p_email), v_today)
  on conflict (user_id) do update
    set email = excluded.email,
        daily_requests = case
          when u.daily_date_utc <> v_today then 0
          else u.daily_requests
        end,
        daily_date_utc = v_today,
        updated_at = v_now
  returning u.total_requests, u.daily_requests
    into v_total, v_daily;

  if p_enforce_limits and v_daily >= 5 then
    v_retry_seconds := greatest(
      1,
      ceil(extract(epoch from (v_reset_at - clock_timestamp())))::integer
    );
    return query select
      false, 'daily_limit'::text, v_retry_seconds, v_reset_at,
      v_total, v_daily, 5, 0, v_reset_at;
    return;
  end if;

  if p_enforce_limits then
    select u.last_call_at + interval '10 minutes'
      into v_available_at
      from public.agent_usage as u
      where u.user_id = p_user_id;

    if v_available_at > clock_timestamp() then
      v_retry_seconds := greatest(
        1,
        ceil(extract(epoch from (v_available_at - clock_timestamp())))::integer
      );
      return query select
        false, 'cooldown'::text, v_retry_seconds, v_available_at,
        v_total, v_daily, 5, greatest(0, 5 - v_daily), v_reset_at;
      return;
    end if;
  end if;

  update public.user_request_usage as u
    set total_requests = u.total_requests + 1,
        daily_requests = u.daily_requests + 1,
        updated_at = v_now
    where u.user_id = p_user_id
    returning u.total_requests, u.daily_requests
      into v_total, v_daily;

  if p_enforce_limits then
    insert into public.agent_usage as u (user_id, last_call_at)
    values (p_user_id, v_now)
    on conflict (user_id) do update
      set last_call_at = excluded.last_call_at;
    v_available_at := v_now + interval '10 minutes';
  else
    v_available_at := null;
  end if;

  return query select
    true, null::text,
    case when p_enforce_limits then 600 else 0 end,
    v_available_at,
    v_total, v_daily, 5, greatest(0, 5 - v_daily), v_reset_at;
end;
$$;

create or replace function public.before_user_created(event jsonb)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  user_email text := lower(coalesce(event -> 'user' ->> 'email', ''));
  restriction_enabled boolean;
begin
  select settings.restrict_sign_in
    into restriction_enabled
    from public.app_settings as settings
    where settings.id = 'main';

  if coalesce(restriction_enabled, false)
    and not exists (
      select 1
      from public.allowed_users as allowed
      where allowed.email = user_email
    )
    and not exists (
      select 1
      from public.admin_users as admins
      where admins.email = user_email
    )
  then
    return jsonb_build_object(
      'error',
      jsonb_build_object(
        'http_code', 403,
        'message', 'Sign-in is restricted to users on the allowed-users list.'
      )
    );
  end if;

  return '{}'::jsonb;
end;
$$;

revoke all on function public.get_agent_call_status(uuid, text, boolean) from public, anon, authenticated;
revoke all on function public.claim_agent_call(uuid, text, boolean) from public, anon, authenticated;
grant execute on function public.get_agent_call_status(uuid, text, boolean) to service_role;
grant execute on function public.claim_agent_call(uuid, text, boolean) to service_role;
revoke all on function public.before_user_created(jsonb) from public, anon, authenticated;
grant execute on function public.before_user_created(jsonb) to supabase_auth_admin;
