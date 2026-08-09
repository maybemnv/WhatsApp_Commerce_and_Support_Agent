# WhatsApp Commerce and Support Agent

Fixture-first prototype for a controlled WhatsApp commerce and support workflow.

## Run the demo

From this directory:

```powershell
python -m pip install -r requirements.txt
python -m uvicorn apps.api.main:app --reload
```

Open `http://127.0.0.1:8000/demo` and use the walkthrough controls:

1. Load the inbound WhatsApp fixture.
2. Ask the seeded catalog about the blue product.
3. Select quantity two.
4. Create the test checkout link.

The UI deliberately labels `link created` separately from payment confirmation. The current implementation is fixture-backed and does not claim live Meta/Twilio, Shopify/WooCommerce, Stripe, or HubSpot capability.

## Verify

```powershell
python -m pytest -q
```

The current slice covers normalized inbound identity, replay deduplication, workspace scoping, service-window opening, inbox/detail APIs, product facts, quantity confirmation, payment-link idempotency, outbound policy checks for service-window/opt-out/takeover state, fixture order-status/delivery-event and human-handoff paths, and the browser demo surface.

## Current boundary

- Implemented: FastAPI fixture API, in-memory conversation state, seeded blue-product catalog, responsive demo workbench, and typed commerce workflow behavior.
- Implemented: fixture approved-template registry, exact-variable/workflow validation, idempotent outbound command enqueue, and final-send policy rechecks for opt-out and human takeover.
- Next: PostgreSQL repository, signature verification, configurable opt-out/re-consent, retry/dead-letter state, appointment/CRM workflows, audit persistence, and live adapter capability checks.
- Template controls: `GET /inbox/{conversationId}/templates`, `POST /inbox/{conversationId}/outbound/templates`, and `POST /inbox/{conversationId}/outbound/{commandId}/submit`.
- Recovery controls: `POST /inbox/{conversationId}/outbound/{commandId}/fail` classifies a provider failure, and `POST /inbox/{conversationId}/outbound/{commandId}/retry` rechecks policy before retrying a bounded fixture command.
- Visual authority: the shared root `design.md` schema is adapted in `apps/web/index.html`; provider-specific capabilities remain explicitly unverified.
