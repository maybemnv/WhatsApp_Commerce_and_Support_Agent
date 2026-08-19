# WhatsApp Commerce and Support Agent

Fixture-first prototype for a controlled WhatsApp commerce and support workflow.

## Run the demo

From this directory:

```powershell
python -m pip install -r requirements.txt
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8105
```

Open `http://127.0.0.1:8105/demo` and use the walkthrough controls:

1. Load the inbound WhatsApp fixture.
2. Ask the seeded catalog about the blue product.
3. Select quantity two.
4. Create the test checkout link.

The UI deliberately labels `link created` separately from payment confirmation. The current implementation is fixture-backed and does not claim live Meta/Twilio, Shopify/WooCommerce, Stripe, or HubSpot capability.

## Verify

```powershell
python -m pytest -q
npm --prefix e2e ci
npm --prefix e2e run test
```

The current verified slice is 34 Python tests plus 6 desktop/mobile Playwright
tests. It covers normalized inbound identity, replay deduplication, workspace
scoping, a deterministic fixture clock, complete reset/readiness, service-window
opening, inbox/detail APIs, product facts, quantity confirmation, payment-link
idempotency, outbound policy checks for service-window/opt-out/takeover state,
fixture order-status/delivery-event and human-handoff paths, safe browser error
handling, responsive layout, and fixture-only attribution events.

## Showcase operations

The default demo port is `8105`. Check process health and fixture readiness
separately:

```powershell
Invoke-RestMethod http://127.0.0.1:8105/health
Invoke-RestMethod http://127.0.0.1:8105/ready
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8105/demo/reset `
  -Headers @{ 'X-Workspace-ID' = 'workspace-demo' }
```

`/health` reports only that the process is alive. `/ready` confirms the seeded
catalog and order are available. Reset is repeat-safe and restores inbound,
workflow, order, delivery, outbound, and analytics fixture state. Stop the
local process with `Ctrl+C`.

The fixture clock defaults to `2026-08-09T12:00:00Z`, inside the seeded
24-hour window. Demo configuration may override it with `WHATSAPP_DEMO_NOW`.
Payment-link creation remains distinct from payment confirmation. WhatsApp,
commerce, payment, and CRM integrations are fixture-only and are not claimed
as live capabilities.

## Current boundary

- Implemented: FastAPI fixture API, in-memory conversation state, seeded blue-product catalog, responsive demo workbench, and typed commerce workflow behavior.
- Implemented: fixture approved-template registry, exact-variable/workflow validation, idempotent outbound command enqueue, and final-send policy rechecks for opt-out and human takeover.
- Next: PostgreSQL repository, signature verification, configurable opt-out/re-consent, retry/dead-letter state, appointment/CRM workflows, audit persistence, and live adapter capability checks.
- Template controls: `GET /inbox/{conversationId}/templates`, `POST /inbox/{conversationId}/outbound/templates`, and `POST /inbox/{conversationId}/outbound/{commandId}/submit`.
- Recovery controls: `POST /inbox/{conversationId}/outbound/{commandId}/fail` classifies a provider failure, and `POST /inbox/{conversationId}/outbound/{commandId}/retry` rechecks policy before retrying a bounded fixture command.
- Visual authority: the shared root `design.md` schema is adapted in `apps/web/index.html`; provider-specific capabilities remain explicitly unverified.
