# WhatsApp Commerce and Support Agent — Demo Deployment

This document describes the repeatable fixture deployment for client demos. It
does not certify production readiness or live Meta/Twilio, Shopify/WooCommerce,
Stripe, or HubSpot capability.

## Demo infrastructure

The current prototype is a single FastAPI process with in-memory state and a
static operator workbench. The target hosted infrastructure is Supabase
Postgres, with Supabase Auth/Storage added when authenticated operator state is
implemented. The current fixture slice requires:

- Python 3.11 or newer.
- One writable process directory.
- No database, queue, provider account, or cloud secret for the seeded demo.

State resets whenever the process restarts. Use the built-in reset endpoint
between walkthroughs.

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest -q
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/demo`.

For a shared client-demo machine, bind deliberately and put the process behind
an authenticated reverse proxy:

```powershell
python -m uvicorn apps.api.main:app --host 0.0.0.0 --port 8000
```

Do not expose the development server directly to the public internet.

## Supabase target

Supabase is the planned system of record for workspaces, customers,
conversations, messages, workflow state, approved templates, outbound commands,
orders, policy decisions, audit events, and handoff tasks. The target schema is
`db/migrations/001_whatsapp_demo.sql` with the seeded fixture in
`db/seed_commerce_demo.sql`. Add a repository boundary before switching the
demo from in-memory state. Supabase Auth should own operator identity and
workspace access; use Supabase Storage only for explicitly approved raw-payload
or attachment retention.

The running API currently does not connect to Supabase. Create the project and
add its secrets only after the repository adapter, authorization, migration, and
reset behavior are implemented and tested.

## Environment and secrets

There are currently no required environment variables. Do not add provider
tokens to source, `tasks.md`, browser JavaScript, or command history.

When live adapters are introduced, use a secret manager or deployment platform
secret store for provider credentials and document only variable names and
owners here. Expected future categories are:

| Category | Future purpose | Current status |
|---|---|---|
| `WHATSAPP_*` | Meta/Twilio webhook and send configuration | Not configured |
| `COMMERCE_*` | Shopify/WooCommerce catalog/order access | Not configured |
| `STRIPE_*` | Payment-link and payment-event access | Not configured |
| `HUBSPOT_*` | CRM contact/lead synchronization | Not configured |
| `SUPABASE_URL` | Supabase project URL | Future; not used |
| `SUPABASE_ANON_KEY` | Browser-safe Supabase client access | Future; not used |
| `SUPABASE_SERVICE_ROLE_KEY` | Server-side migrations/background jobs | Future secret; not used |
| `DATABASE_URL` | Supabase Postgres connection/pooling | Future; not used; state is in memory |
| `REDIS_URL` | Queue, locks, retry, and dead-letter state | Not used |

## Demo preflight

1. Start from a clean `master` checkout and install the pinned-range
   requirements.
2. Run `python -m pytest -q`; the expected current result is 22 passing tests.
3. Check `/health` and confirm `{"status":"ok","mode":"fixture"}`.
4. Open `/demo` and load the inbound fixture.
5. Walk through product facts, quantity two, checkout link creation, order
   lookup, delivery event replay, opt-out, takeover, and explicit resume.
6. Open the approved-template list, enqueue an order-status template, replay
   the enqueue request, then opt out and submit it to show the final policy
   recheck blocks the queued command.
7. Reset with:

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/demo/reset `
  -Headers @{ 'X-Workspace-ID' = 'workspace-demo' }
```

## Current operational boundaries

- The catalog, order, delivery, policy, and payment flows are deterministic
  fixtures.
- Payment-link creation is not payment confirmation.
- The policy gate covers the in-memory service window, opt-out, and takeover
  state; durable enqueue/provider-submission enforcement is not implemented.
- There is no durable audit log, background worker, retry queue, dead-letter
  store, signature verification, authentication, or authorization layer yet.
- Add a health/readiness contract, persistence, migrations, reverse proxy TLS,
  observability, backups, retention, and incident handling before any live
  client traffic.

## Release handoff checklist

- [ ] Confirm client-owned provider accounts, webhook URLs, approved templates,
  sender identity, locales, commerce catalog, payment account, CRM owner, and
  retention/deletion policy.
- [ ] Implement and verify signature validation and idempotent durable event
  storage.
- [ ] Add authenticated operator access, workspace isolation, secret storage,
  TLS, logs/metrics, backups, and incident response.
- [ ] Validate the 24-hour service window and approved-template policy at both
  enqueue and final provider submission.
- [ ] Run the acceptance traces with live/fixture/blocked labels and record the
  exact provider capabilities before calling the deployment client-ready.
