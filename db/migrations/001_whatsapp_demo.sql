-- Supabase/Postgres target for the WhatsApp commerce/support prototype.
-- The running demo remains fixture-backed until the repository, auth, and RLS
-- behavior are verified against a client-owned project.

create extension if not exists pgcrypto;

create table if not exists public.workspaces (
  id text primary key,
  name text not null,
  created_at timestamptz not null default now()
);

create table if not exists public.workspace_members (
  workspace_id text not null references public.workspaces(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null check (role in ('admin', 'operator', 'viewer')),
  primary key (workspace_id, user_id)
);

create table if not exists public.channel_connections (
  id text primary key,
  workspace_id text not null references public.workspaces(id) on delete cascade,
  provider text not null check (provider in ('meta_cloud', 'twilio_whatsapp')),
  mode text not null check (mode in ('live', 'fixture', 'blocked')),
  status text not null default 'not_configured',
  capabilities jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.customers (
  id text primary key,
  workspace_id text not null references public.workspaces(id) on delete cascade,
  channel_identity text not null,
  display_name text,
  opted_out boolean not null default false,
  created_at timestamptz not null default now(),
  unique (workspace_id, channel_identity)
);

create table if not exists public.conversations (
  id text primary key,
  workspace_id text not null references public.workspaces(id) on delete cascade,
  customer_id text not null references public.customers(id) on delete cascade,
  channel_connection_id text references public.channel_connections(id) on delete set null,
  status text not null default 'open',
  human_takeover boolean not null default false,
  handoff_task_id text,
  handoff_reason text,
  version integer not null default 1 check (version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.service_windows (
  conversation_id text primary key references public.conversations(id) on delete cascade,
  workspace_id text not null references public.workspaces(id) on delete cascade,
  opened_at timestamptz not null,
  expires_at timestamptz not null,
  status text not null check (status in ('active', 'expired', 'unknown'))
);

create table if not exists public.inbound_events (
  id text primary key,
  workspace_id text not null references public.workspaces(id) on delete cascade,
  conversation_id text references public.conversations(id) on delete set null,
  provider_event_id text not null,
  provider_message_id text not null,
  payload jsonb not null,
  occurred_at timestamptz not null,
  created_at timestamptz not null default now(),
  unique (workspace_id, provider_event_id),
  unique (workspace_id, provider_message_id)
);

create table if not exists public.messages (
  id text primary key,
  workspace_id text not null references public.workspaces(id) on delete cascade,
  conversation_id text not null references public.conversations(id) on delete cascade,
  provider_message_id text not null,
  direction text not null check (direction in ('inbound', 'outbound')),
  body_text text,
  occurred_at timestamptz not null,
  raw_payload_reference text not null,
  unique (workspace_id, provider_message_id)
);

create table if not exists public.products (
  id text primary key,
  workspace_id text not null references public.workspaces(id) on delete cascade,
  name text not null,
  description text not null,
  availability text not null,
  price_cents integer not null check (price_cents >= 0),
  currency text not null,
  source text not null,
  approved boolean not null default false
);

create table if not exists public.orders (
  id text primary key,
  workspace_id text not null references public.workspaces(id) on delete cascade,
  conversation_id text references public.conversations(id) on delete set null,
  product_id text references public.products(id) on delete set null,
  status text not null,
  tracking_id text,
  source text not null,
  updated_at timestamptz not null default now()
);

create table if not exists public.templates (
  id text primary key,
  workspace_id text not null references public.workspaces(id) on delete cascade,
  locale text not null,
  variables jsonb not null default '[]'::jsonb,
  workflow text not null,
  local_approved boolean not null default false,
  provider_approved boolean not null default false,
  unique (workspace_id, id, locale)
);

create table if not exists public.outbound_commands (
  id text primary key,
  workspace_id text not null references public.workspaces(id) on delete cascade,
  conversation_id text not null references public.conversations(id) on delete cascade,
  template_id text references public.templates(id) on delete restrict,
  idempotency_key text not null,
  variables jsonb not null default '{}'::jsonb,
  status text not null check (status in ('queued', 'sent', 'blocked', 'retryable', 'dead_letter')),
  policy_code text,
  provider_result text,
  attempts integer not null default 0,
  next_attempt_at timestamptz,
  last_error_code text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (workspace_id, idempotency_key)
);

create table if not exists public.delivery_events (
  id text primary key,
  workspace_id text not null references public.workspaces(id) on delete cascade,
  order_id text not null references public.orders(id) on delete cascade,
  provider_event_id text not null,
  status text not null,
  occurred_at timestamptz not null,
  unique (workspace_id, provider_event_id)
);

create table if not exists public.handoffs (
  id text primary key,
  workspace_id text not null references public.workspaces(id) on delete cascade,
  conversation_id text not null references public.conversations(id) on delete cascade,
  reason text not null,
  state text not null default 'open',
  context jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.audit_events (
  id uuid primary key default gen_random_uuid(),
  workspace_id text not null references public.workspaces(id) on delete cascade,
  conversation_id text references public.conversations(id) on delete set null,
  action text not null,
  actor jsonb not null default '{}'::jsonb,
  payload jsonb not null default '{}'::jsonb,
  occurred_at timestamptz not null default now()
);

create index if not exists conversations_workspace_status_idx on public.conversations(workspace_id, status);
create index if not exists outbound_commands_workspace_status_idx on public.outbound_commands(workspace_id, status, next_attempt_at);
create index if not exists audit_events_workspace_time_idx on public.audit_events(workspace_id, occurred_at);

create or replace function public.current_workspace_id()
returns text language sql stable as $$
  select nullif(current_setting('request.jwt.claims', true)::jsonb ->> 'workspace_id', '');
$$;

create or replace function public.is_workspace_member(target_workspace_id text)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.workspace_members
    where workspace_id = target_workspace_id and user_id = auth.uid()
  );
$$;

alter table public.workspaces enable row level security;
alter table public.workspace_members enable row level security;
alter table public.channel_connections enable row level security;
alter table public.customers enable row level security;
alter table public.conversations enable row level security;
alter table public.service_windows enable row level security;
alter table public.inbound_events enable row level security;
alter table public.messages enable row level security;
alter table public.products enable row level security;
alter table public.orders enable row level security;
alter table public.templates enable row level security;
alter table public.outbound_commands enable row level security;
alter table public.delivery_events enable row level security;
alter table public.handoffs enable row level security;
alter table public.audit_events enable row level security;

do $$
declare table_name text;
begin
  foreach table_name in array array[
    'channel_connections','customers','conversations','service_windows',
    'inbound_events','messages','products','orders','templates',
    'outbound_commands','delivery_events','handoffs','audit_events'
  ] loop
    execute format('drop policy if exists workspace_isolation on public.%I', table_name);
    execute format(
      'create policy workspace_isolation on public.%I using (workspace_id = public.current_workspace_id() and public.is_workspace_member(workspace_id)) with check (workspace_id = public.current_workspace_id() and public.is_workspace_member(workspace_id))',
      table_name
    );
  end loop;
end $$;

drop policy if exists workspace_member_isolation on public.workspace_members;
create policy workspace_member_isolation on public.workspace_members
  using (workspace_id = public.current_workspace_id() and public.is_workspace_member(workspace_id))
  with check (workspace_id = public.current_workspace_id());
