-- Run after db/migrations/001_whatsapp_demo.sql in a non-production project.
-- Local demos continue to use the in-memory fixture store.

insert into public.workspaces (id, name)
values ('workspace-demo', 'WhatsApp Commerce Demo')
on conflict (id) do update set name = excluded.name;

insert into public.channel_connections (id, workspace_id, provider, mode, status, capabilities)
values (
  'fixture-whatsapp', 'workspace-demo', 'meta_cloud', 'fixture', 'available',
  '{"inbound":"fixture","outbound":"fixture_only","live":"not_configured"}'::jsonb
)
on conflict (id) do update set capabilities = excluded.capabilities;

insert into public.products (id, workspace_id, name, description, availability, price_cents, currency, source, approved)
values (
  'blue-product-001', 'workspace-demo', 'Blue Product',
  'The seeded blue product for the commerce walkthrough.', 'available', 4900, 'USD',
  'fixture-catalog', true
)
on conflict (id) do update set approved = excluded.approved;

insert into public.templates (id, workspace_id, locale, variables, workflow, local_approved, provider_approved)
values
  ('order_status_update', 'workspace-demo', 'en-US', '["order_id","status","tracking_id"]'::jsonb, 'order_status', true, true),
  ('appointment_reminder', 'workspace-demo', 'en-US', '["appointment_at","time_zone"]'::jsonb, 'appointment_reminder', true, true),
  ('payment_link_follow_up', 'workspace-demo', 'en-US', '["payment_link"]'::jsonb, 'payment_follow_up', true, true),
  ('human_handoff_ack', 'workspace-demo', 'en-US', '["task_id"]'::jsonb, 'human_handoff', true, true),
  ('service_window_reopen', 'workspace-demo', 'en-US', '["opt_in_source"]'::jsonb, 'service_window_reopen', true, true)
on conflict (id, workspace_id, locale) do update set local_approved = excluded.local_approved, provider_approved = excluded.provider_approved;
