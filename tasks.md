# WhatsApp Commerce and Support Agent — Client Demo Prototype Tasks

**Goal:** Build a stateful WhatsApp commerce and support prototype that answers product questions from approved facts, supports a test checkout path, tracks order/support state, respects the 24-hour service window and opt-out policy, and hands work to an operator with full attribution and audit context.

**Architecture:** Use a provider-neutral conversation engine with a normalized WhatsApp webhook boundary, PostgreSQL state, Redis or queue-backed workers, workflow locks and version checks, commerce/payment/CRM adapters, approved-template controls, dead-letter handling, and an operator workbench. Deterministic fixtures are the primary demo path; one channel and one commerce provider may be validated live.

**Tech stack:** WhatsApp adapter via Meta Cloud API or Twilio, PostgreSQL, Redis/queue, operator web workspace, Shopify or WooCommerce adapter, Stripe payment-link boundary, HubSpot sync boundary, and typed tests, as bounded by `PRD.md`.

## Current status - 2026-08-19

### Verified delivered in the first vertical slice

- [x] Added a fixture-backed FastAPI API with workspace-scoped webhook, inbox, conversation-detail, reset, and commerce actions.
- [x] Normalized the inbound WhatsApp fixture with stable event/thread/message identities, replay deduplication, and provider-message collision safety.
- [x] Opened and exposed the 24-hour service window for accepted inbound messages.
- [x] Added the seeded blue-product catalog, source trace, quantity selection, idempotent test checkout link, and explicit link-created versus payment-confirmed states.
- [x] Added the responsive operator workbench using the shared root `design.md` visual schema and explicit fixture/provider boundaries.
- [x] Added regression coverage for normalization, replay, workspace scope, service-window state, product facts, quantity confirmation, payment-link idempotency, and the browser demo surface.
- [x] Added a deterministic outbound policy decision boundary for active service windows, opt-out, and human takeover, with explicit API controls and regression tests.
- [x] Added a seeded order-status lookup with safe no-match behavior and idempotent delivery-event updates for the client trace.
- [x] Added a deterministic human takeover action that creates an operator handoff brief with reason, task ID, and explicit resume behavior.
- [x] Added five fixture approved-template contracts with exact locale, variable, workflow, local-approval, and provider-approval checks at enqueue time and a final-send policy recheck.
- [x] Added idempotent outbound command storage plus regression coverage proving opt-out and human takeover block queued sends before provider submission; the fixture result is explicitly `fixture_only`.
- [x] Added bounded `timeout`/`rate_limit`/provider-unavailable retry classification, deterministic 5s/30s/5m backoff timestamps, policy recheck before retry, and dead-letter state after the retry budget; the current Python suite has 34 passing tests.
- [x] Added the Supabase/Postgres target migration, demo seed, and blank `.env.example` contract for workspace-scoped conversations, templates, outbound commands, orders, handoffs, and audit state; runtime persistence remains fixture-only until verified.
- [x] Added `deployment.md` with Supabase target infrastructure, fixture setup, no-secrets environment guidance, demo preflight, and handoff limitations.
- [x] Added a deterministic fixture clock, complete repeat-safe reset, distinct `/health` and `/ready` checks, and the `WHATSAPP_DEMO_NOW` demo configuration contract.
- [x] Added safe non-2xx browser handling, desktop/mobile Playwright coverage (6 passing tests), and a fixture-only attribution trail with reset semantics.

### Not yet complete

- [ ] Runtime PostgreSQL persistence, workers/queue, authentication/roles, provider signature verification, and durable audit/event storage remain outstanding; the Supabase schema/seed target is now documented and RLS-enabled.
- [ ] Enqueue/provider submission enforcement, configurable opt-out/re-consent, and live adapter capability checks remain outstanding; the current slice covers fixture policy gates, approved-template validation, and bounded retry/dead-letter state.
- [ ] CRM synchronization, appointment booking, durable attribution analytics, and full client handoff documentation remain outstanding; the in-memory fixture attribution panel is implemented for the showcase.

### Next work queue

1. Add persistent workspace/customer/conversation state and provider signature validation.
2. Add persistent Supabase workspace/conversation state, appointment/CRM, and append-only audit workflows with regression tests.
3. Add provider signature verification, configurable opt-out/re-consent, and the remaining client demo script, runbook, integration matrix, and acceptance report.
4. Validate one live-capable provider only after client credentials and behavior are supplied.

The full checklist below remains the source of the complete Phase 0-5 scope; this status records only verified work in the current checkout.

## Global constraints

- [ ] Select one channel provider and one commerce provider only after credentials and capabilities are verified; keep alternatives behind typed fixture adapters.
- [ ] Enforce the 24-hour service-window policy both when work is queued and immediately before provider submission.
- [ ] Separate local template approval from provider approval; validate locale, variables, workflow authorization, and opt-out before sending.
- [ ] Treat link creation, payment success, order status, delivery status, and CRM sync as separate states; never imply one from another.
- [ ] Human takeover, opt-out, closed-window, failed policy checks, duplicate events, and provider failures must win over already-queued automation.
- [ ] Use deterministic seeded conversations and label live, fixture-backed, blocked, and unknown behavior in the UI.
- [ ] Use `D:\ARC Automation Service\design.md` as the shared visual authority for genre, workbench shell, palette, typography, spacing, shape, motion, and explicit states. Adapt the information architecture to WhatsApp commerce; do not copy call or revenue content.
- [ ] Preserve PRD non-goals: no autonomous refunds/cancellations/inventory edits, omnichannel inbox, native voice calling, unverified compliance claims, or unsupported provider parity.

## Target file structure

- Create `apps/web/` for the operator inbox, customer profile, flow/template/integration/analytics/event routes, and shared components.
- Create `apps/api/` for webhook, conversation, workflow, policy, commerce, payment, CRM, handoff, and audit APIs.
- Create `workers/` for inbound normalization, workflow steps, approved outbound, retry, dead-letter, delivery, and attribution jobs.
- Create `db/migrations/` and `db/seed_commerce_demo.sql` for workspace, customer, conversation, workflow, service-window, template, order, payment, handoff, attribution, and audit state.
- Create `adapters/` for WhatsApp, Shopify/WooCommerce, Stripe, HubSpot, and test doubles.
- Create `tests/contracts/`, `tests/workflows/`, `tests/races/`, `tests/traces/`, and `tests/ui/` for policy, adapter, concurrency, end-to-end, and interface coverage.
- Create `README.md`, `.env.example`, `DEMO_SCRIPT.md`, `RUNBOOK.md`, and `INTEGRATION_MATRIX.md` for client operation.

## Phase 0 — Demo scope and contracts

- [ ] Convert PRD FR-01–FR-09, the three traces, retry/dead-letter rules, and operating targets into `tests/acceptance/acceptance_matrix.md`.
- [ ] Choose the primary demo channel from Meta Cloud API or Twilio based on available test credentials; preserve the provider-neutral adapter contract.
- [ ] Choose Shopify or WooCommerce for the first commerce path; keep the other as a fixture/status adapter.
- [ ] Seed Admin, Operator, and Viewer roles with one workspace and explicit permissions.
- [ ] Seed the “blue product” catalog, recommendation reason, test checkout/payment link, delivery event, appointment/handoff task, approved templates, campaign attribution, opt-out event, and failed retry.
- [ ] Define typed contracts for normalized webhooks, customer identity, workflow state, service windows, tools, templates, outbound commands, attribution events, and audit events.
- [ ] Add readiness checks and explicit live/fixture/blocked/unknown labels.

**Exit gate:** The happy path can run without external credentials and every provider boundary has a visible capability status.

## Phase 1 — Inbound foundation and operator shell

- [ ] Scaffold the web, API, persistence, worker, adapter, and test boundaries from the PRD architecture.
- [ ] Create workspace, customer, conversation, message, workflow, service-window, audit, role, and channel migrations with uniqueness and workspace scope.
- [ ] Normalize one inbound webhook format, verify the configured signature, quarantine invalid events, persist event and deduplication identity before acknowledgement, and return the required webhook response. (Fixture normalization and in-memory deduplication are implemented; signature verification and durable persistence remain outstanding.)
- [ ] Resolve channel identity to a workspace/customer, open or refresh the 24-hour service window, and record language/direction/attribution metadata. (Fixture workspace/customer identity and window state are implemented; durable attribution remains outstanding.)
- [ ] Add conversation-scoped locks, version checks, correlation IDs, and append-only workflow/tool/audit events.
- [ ] Build inbox, customer profile, transcript, raw-event reference, duplicate-event result, and service-window countdown surfaces.
- [ ] Add tests for signature validation, identity resolution, duplicate webhooks, invalid payloads, workspace scope, and service-window creation.

**Demo gate:** A seeded inbound message appears once, resolves the customer, opens the 24-hour window, and exposes normalized event and audit context.

## Phase 2 — Commerce, support, and stateful outcomes

- [x] Implement approved catalog retrieval with product IDs, facts, availability, source/tool trace, language preservation, and unsupported-product behavior.
- [x] Implement recommendation, product selection, quantity capture, confirmation, and interactive-message/text fallback.
- [x] Create a checkout or Stripe payment link and persist link-created separately from payment-confirmed.
- [ ] Implement one Shopify/WooCommerce order lookup path with safe identifiers, no-match clarification, multiple-match protection, timestamped source-backed status, and delivery-event updates. (A deterministic fixture order and idempotent delivery-event path are implemented; live adapter behavior remains outstanding.)
- [ ] Implement appointment field collection and confirmation; create a human task when no booking action is configured.
- [ ] Implement lead qualification, missing-field display, operator correction, and idempotent HubSpot synchronization.
- [ ] Implement explicit human-request detection, unsupported-intent handoff, operator claim/reply/resolve, pause, and explicit resume.
- [ ] Persist every state transition and tool result for the transcript and audit timeline.
- [ ] Add tests for product facts, recommendation, quantity confirmation, payment-link distinction, order no-match, multiple matches, CRM sync, and human handoff.

**Demo gate:** Product availability → recommendation → confirmation → test payment link → delivery update → human handoff works with seeded data.

## Phase 3 — Service window, templates, opt-out, retry, and dead letter

- [ ] Enforce the 24-hour window at enqueue time and again immediately before provider submission; no closed-window free-form send is permitted.
- [x] Implement the five fixture template contracts: `order_status_update`, `appointment_reminder`, `payment_link_follow_up`, `human_handoff_ack`, and `service_window_reopen`.
- [x] Validate fixture template locale, variables, local/provider approval, workflow authorization, window state, and opt-out/takeover state at enqueue and final submission.
- [x] Implement fixture opt-out state and blocked outbound commands; configurable phrases, immutable event persistence, and operator-controlled re-consent remain outstanding.
- [x] Add bounded fixture transient retry at 5 seconds, 30 seconds, and 5 minutes; do not retry permanent, invalid, opted-out, closed-window, or rejected-template commands unchanged.
- [x] Add fixture dead-letter records containing command reference, attempt count, error class, next action, policy recheck, and replay state; durable queue persistence remains outstanding.
- [x] Ensure takeover and opt-out block queued automation before provider submission, even when the work was already enqueued.
- [ ] Add race tests for takeover-vs-send, opt-out-vs-retry, duplicate webhook-vs-workflow, and closed-window-vs-template.

**Demo gate:** An expired appointment reminder uses an approved template, a simulated timeout retries, and a later opt-out prevents the queued retry from sending.

## Phase 4 — UI and shared design system

- [ ] Apply the root `design.md` schema: modern-minimal quiet technical workbench, operational stat strip, conversation review surface, supporting policy/workflow/customer/order/payment/attribution panels, floating-pill navigation, and inline operational footer.
- [ ] Use the shared brand tokens `--brand-silver`, `--brand-steel`, `--brand-blue`, `--brand-gray`, `--brand-soft`, `--brand-slate`, `--brand-ink`, and `--brand-white`.
- [ ] Use Trebuchet MS for display, Segoe UI/Arial for body, and Consolas or `ui-monospace` for IDs, timestamps, event data, policy decisions, and correlation IDs.
- [ ] Use 4-point spacing, visible 1px rules, restrained rounded corners, no gradients/glass effects, single-line controls, visible focus, and reduced-motion behavior.
- [ ] Implement `/inbox`, `/customers`, `/flows`, `/templates`, `/integrations`, `/analytics`, and `/events` with explicit loading, empty, policy-blocked, expired-window, opt-out, retry, dead-letter, and provider-degraded states.
- [ ] Build `WindowBadge`, `PolicyGate`, `RetryInspector`, `HandoffBrief`, `TemplateStatusCard`, `AttributionTrail`, and `ProductCardPreview` with text-plus-icon status.
- [ ] Provide desktop three-column conversation detail and responsive mobile tabs for transcript, customer, workflow, policy, and event views.
- [ ] Show delivery/read states only when returned by the provider; never invent message outcomes.
- [ ] Add keyboard, screen-reader, responsive, focus-retention, and reduced-motion checks.

**Exit gate:** A client can see what the agent did, which policy allowed/blocked it, what is live versus simulated, and how an operator takes over.

## Phase 5 — Attribution, analytics, and hardening

- [ ] Persist first-touch, last-touch, `unknown` source, campaign, template, workflow, handoff, opt-out, payment, delivery, and conversion events.
- [ ] Connect product → checkout → support → handoff to campaign reporting without claiming attribution where source data is missing.
- [ ] Add integration health, webhook/event inspection, blocked-action explanations, retry history, dead-letter replay, and audit visibility.
- [ ] Add concurrency protection for takeover, queued sends, duplicate events, replay, workflow transitions, CRM sync, payment links, and analytics events.
- [ ] Polish only the seeded flows and remove unsupported claims or workflow categories from the demo.
- [ ] Run unit, adapter contract, integration, race, trace, accessibility, and responsive tests.

## Canonical client demo

1. Customer sends, “Is the blue product available?”
2. Inbox shows normalized message, customer identity, active 24-hour window, language, and attribution.
3. Agent returns a source-backed product card or text fallback with availability and recommendation reason.
4. Customer selects quantity and confirms; the system creates a test checkout/payment link and clearly shows link-created, not payment-confirmed.
5. A seeded delivery event updates the conversation, order status, and attribution trail.
6. Customer requests a human; automation pauses and the operator receives transcript, workflow state, order/payment reference, tool history, and attribution.
7. Run the governance proof separately: expired reminder → approved template → simulated timeout → opt-out blocks the queued retry.
8. Show order no-match → clarification → human handoff and inspect the audit/event view.

## Validation and client handoff

- [ ] Run tests for webhook signature/normalization, deduplication, identity resolution, workflow transitions, service-window gates, template validation, opt-out, takeover, retry classification, role permissions, and audit coverage.
- [ ] Run adapter contract tests for Meta/Twilio, Shopify/WooCommerce, HubSpot, and Stripe normalized results; mark unverified capabilities instead of guessing.
- [ ] Run integration tests for persistence, queue dispatch, conversation locks, replay, delivery events, CRM sync, payment/order events, dead letters, and policy rechecks.
- [ ] Run regression tests proving duplicate webhooks do not duplicate messages, workflow transitions, CRM records, payment links, or analytics.
- [ ] Run end-to-end tests for all three PRD traces and the opt-out/takeover race.
- [ ] Validate the PRD operating targets: 100% replay/policy-block correctness, at least 70% seeded trace completion, at least 90% retry recovery, at least 95% attribution completeness, and handoff brief clarity of at least 4/5.
- [ ] Add `README.md` with setup, migrations, fixture seed/reset, demo mode, tests, environment variables, and known limitations.
- [ ] Add `DEMO_SCRIPT.md` with preflight checks, exact conversation script, expected outputs, live-vs-stub indicators, and fallback steps.
- [ ] Add `RUNBOOK.md` with webhook setup, template approval, integration health, retry/dead-letter replay, takeover, opt-out, audit history, secrets handling, and incident recovery.
- [ ] Add `INTEGRATION_MATRIX.md` identifying provider versions, webhook verification, quotas, template approval, commerce event shapes, CRM mappings, payment events, consent questions, and live/fixture/blocked/unknown status.
- [ ] Deliver a final acceptance report with demo pass/fail, tests, seeded reset proof, credential isolation, unsupported states, known limitations, and client owners for credentials, templates, integrations, and operations.

## Final acceptance gates

- [ ] The seeded commerce/support path works from inbound question through handoff.
- [ ] Service-window, template, opt-out, takeover, retry, and dead-letter rules are enforced at the final send boundary.
- [ ] Payment-link creation is not represented as payment confirmation.
- [ ] Duplicate events and replay do not duplicate messages, workflows, records, or attribution.
- [ ] The UI follows the shared `design.md` schema and exposes policy, evidence, attribution, and failure state.
- [ ] The README and demo script allow a client to reset, rehearse, fine-tune, and understand exactly what is live versus simulated.
