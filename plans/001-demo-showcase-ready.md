# Plan 001: Make the WhatsApp fixture demo time-stable and browser-verified

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report; do not improvise. When done, update the status row for this plan in
> `plans/README.md` unless a reviewer dispatched you and told you they maintain
> the index.
>
> **Drift check (run first)**: `git diff --stat ccfb867..HEAD -- apps/api apps/web requirements.txt tests README.md deployment.md tasks.md .env.example e2e`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MED
- **Depends on**: none
- **Category**: bug, tests, dx, docs, direction
- **Planned at**: commit `ccfb867`, 2026-08-19
- **Issue**: omit unless published explicitly by the operator

## Why this matters

The repository has a useful fixture-backed WhatsApp workbench, but its seeded
event is dated `2026-08-09` while the service uses the current system clock.
The documented suite therefore fails on the current date and the primary
browser flow is blocked by the closed service window. Reset also leaves mutable
order and delivery-event state behind. This plan keeps the default showcase on
API port `8105`, adds an injected fixture clock and complete reset/readiness
contract, verifies the browser flow at desktop/mobile widths, and adds only a
small fixture attribution trail rather than a durable analytics architecture.

## Current state

- `apps/api/main.py` — FastAPI application. `create_app()` sets
  `app.state.clock = lambda: datetime.now(timezone.utc)` and passes it into
  `CommerceService` (`apps/api/main.py:15-28`). It exposes `/health` returning a
  static process/mode payload (`apps/api/main.py:31-33`) and `/demo/reset` that
  clears conversations, messages, workflows, outbound commands, and
  idempotency entries (`apps/api/main.py:400-429`).
- `apps/api/inbound.py` — in-memory inbound state. The store owns events,
  conversations, and messages (`apps/api/inbound.py:68-79`) and has no complete
  reset method.
- `apps/api/commerce.py` — mutable commerce fixture. `CommerceDemoStore` owns
  products, workflows, orders, delivery-event dedupe, outbound commands, and
  idempotency (`apps/api/commerce.py:114-121`). `__post_init__` seeds one order
  only when the order map is empty (`apps/api/commerce.py:123-139`), while
  delivery updates mutate the order and event map (`apps/api/commerce.py:331-361`).
- `apps/web/index.html` — static browser workbench. The load action posts a
  fixed `2026-08-09T10:00:00Z` event (`apps/web/index.html:152-172`). The
  request helper does not check `response.ok`, and `askCatalog()` consumes any
  error payload as if it were product data (`apps/web/index.html:149-185`).
- `tests/test_demo.py` — only asserts that HTML strings and fixture controls
  exist (`tests/test_demo.py:6-13`); it does not execute a browser flow.
- `requirements.txt` — uses broad ranges for FastAPI, HTTPX, pytest, and
  Uvicorn (`requirements.txt:1-4`), with no lock or constraints file.
- `deployment.md` — documents port 8000, expects 25 passing tests, checks only
  `/health`, and documents reset at `/demo/reset` (`deployment.md:21-40,
  78-98`). The showcase port for this plan is 8105.
- `tasks.md` — records 25 tests as delivered (`tasks.md:22-26`) while also
  recording attribution analytics as incomplete (`tasks.md:28-32`). The
  required showcase contract asks for lightweight attribution analytics and
  time-stable fixtures, not durable production analytics.

Fresh read-only verification at the planned SHA: the suite produced 15 passed
and 10 failures, with product-question/template tests blocked by
`service_window_closed`. A reset probe showed that delivery remained a
duplicate and the order remained delivered after reset. Do not treat those
results as acceptable completion evidence.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Backend tests | `python -B -m pytest -p no:cacheprovider -q` | exit 0; all existing and new tests pass |
| API start | `python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8105` | process listens on 8105 |
| Process health | `Invoke-RestMethod http://127.0.0.1:8105/health` | process status is `ok`, mode is `fixture` |
| Fixture readiness | `Invoke-RestMethod http://127.0.0.1:8105/ready` | catalog and demo fixture dependencies are ready |
| Fixture reset | `Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8105/demo/reset -Headers @{ 'X-Workspace-ID' = 'workspace-demo' }` | reset succeeds and returns workspace/mode/seed status |
| Browser dependencies | `npm --prefix e2e ci` | exit 0 using committed lockfile |
| Browser smoke | `npm --prefix e2e run test` | desktop and mobile specs pass |

If the executor chooses a Python Playwright package instead of the planned
`e2e` Node package, document the equivalent install and browser-install command
before using it. Do not install dependencies during this read-only planning
session; dependency installation belongs to the executor branch.

## Suggested executor toolkit

- Follow existing FastAPI `TestClient` patterns in `tests/test_api.py` and
  domain-service patterns in `tests/test_commerce.py` and
  `tests/test_templates.py`.
- Use a small Playwright package under `e2e/` so the static HTML demo can be
  tested without changing the application stack. Configure its web server to
  start Uvicorn on 8105 and reuse an already-running local server when desired.
- Invoke `superpowers:test-driven-development` before behavior changes and
  `superpowers:verification-before-completion` before making completion claims.
- Keep all analytics data in memory and explicitly fixture-labeled.

## Scope

**In scope** (the only files this plan may modify):

- `apps/api/main.py`
- `apps/api/inbound.py`
- `apps/api/commerce.py`
- `apps/api/policy.py` only if required to accept the injected clock cleanly
- `tests/test_api.py`
- `tests/test_inbound.py`
- `tests/test_commerce.py`
- `tests/test_policy.py`
- `tests/test_templates.py`
- `tests/test_reset.py` (create if keeping reset tests separate)
- `tests/test_analytics.py` (create if keeping analytics tests separate)
- `tests/test_demo.py`
- `requirements.txt` or one new `requirements-dev.txt` if the exact install
  contract is documented
- `.env.example`
- `README.md`
- `deployment.md`
- `tasks.md`
- `apps/web/index.html`
- `e2e/package.json` (create)
- `e2e/package-lock.json` (create)
- `e2e/playwright.config.ts` (create)
- `e2e/demo.spec.ts` (create)
- `plans/README.md` and this plan file

**Out of scope** (do NOT touch, even though they look related):

- `db/migrations/001_whatsapp_demo.sql` and `db/seed_commerce_demo.sql` — no
  durable migration or seed work is required for this fixture plan.
- Any Meta/Twilio, Shopify/WooCommerce, Stripe, HubSpot, Supabase, Redis,
  signature, authentication, authorization, worker, queue, or TLS code.
- Any broad campaign analytics, attribution warehouse, or production reporting
  architecture. The plan adds only a small in-memory fixture trail.
- Any root workspace file or another product repository.

## Git workflow

- Branch: `feat/demo-showcase-ready` from the planned SHA.
- Commit checkpoint 1 after clock, reset, readiness, and regression tests.
- Commit checkpoint 2 after browser error handling, browser smoke, and docs.
- Commit checkpoint 3 after lightweight attribution analytics and final
  verification.
- Match the repository's concise commit style and include exact verification
  commands in the handoff.
- Do not push, open a PR, or merge unless the operator separately authorizes
  publishing. Local commits are sufficient for this plan.

## Steps

### Step 1: Make fixture time injectable and reset complete

1. Add a fixture-clock contract. In fixture mode, default the application to a
   deterministic UTC timestamp that is inside the seeded 24-hour window. Allow
   an explicit environment override such as `WHATSAPP_DEMO_NOW`; document only
   the variable name and that values are demo configuration. Keep a separate
   system-clock option available for future live behavior.
2. Ensure every `CommerceService` created by the app uses the injected clock.
   Update direct service tests to pass a fixed clock explicitly so they never
   depend on the host date.
3. Add `InMemoryConversationStore.reset()` to clear inbound events,
   conversations, and messages.
4. Add `CommerceDemoStore.reset()` to restore the seeded order snapshot and
   clear delivery events, workflows, outbound commands, and idempotency maps.
   Do not clear the static product catalog unless the method is rebuilding the
   full fixture snapshot.
5. Change `/demo/reset` to call both reset methods, reset the demo clock, and
   return a truthful fixture-ready payload. Repeated reset calls must be safe.
6. Add `/ready` distinct from `/health`. `/ready` must confirm that the
   expected fixture catalog/order exists and report mode/fixture status; it must
   not claim a live provider or durable persistence.

**Red verification**: Add tests for active-window product question, expired
window with an explicit later clock, and delivery → reset → delivery replay.
Run `python -B -m pytest -p no:cacheprovider tests/test_api.py tests/test_commerce.py tests/test_reset.py -q` before implementation; the new tests must fail under the current system-clock/incomplete-reset behavior.

**Green verification**: Implement the smallest clock/reset/readiness change and
run the same focused command. Expected result: all selected tests pass, active
fixture actions work, explicit expiry blocks, and the post-reset delivery is
not a duplicate.

**Checkpoint**: Run the full suite. `python -B -m pytest -p no:cacheprovider -q`
must exit 0. Commit checkpoint 1 only after the documented test count is
freshly measured.

### Step 2: Make the static browser fail safely

1. Change the shared `request()` helper in `apps/web/index.html` to check
   `response.ok`, parse the API error shape, and throw a user-safe error without
   exposing internal details.
2. Add one visible error/status region for blocked policy, expired window, or
   unavailable API. `askCatalog`, `selectProduct`, and `confirmPurchase` must
   update successful UI state only after a successful response; downstream
   buttons remain disabled after failure.
3. Keep the explicit payment distinction: a checkout link is not payment
   confirmation, and all provider behavior remains fixture-only.

**Red verification**: Add a focused browser-facing test or DOM contract test
that mocks a non-2xx product-question response. Run it before the handler
change; it must fail because the current UI advances after errors.

**Green verification**: Run the focused test and then the full Python suite;
both must pass. Manually or through the browser suite, a blocked request must
show an error and leave Select/Confirm disabled.

### Step 3: Add desktop/mobile browser smoke coverage

1. Create `e2e/package.json`, `e2e/package-lock.json`, and
   `e2e/playwright.config.ts`. Configure the API web server on port 8105 and
   reuse an existing server when the operator starts it manually.
2. Create `e2e/demo.spec.ts`. Before each test, call `/demo/reset` with the
   demo workspace header. At desktop width, open `/demo`, load the inbound
   fixture, ask the catalog, select quantity two, and create the test checkout
   link. Assert visible “link created” versus payment-not-confirmed copy.
3. Add a desktop policy/recovery trace that exercises opt-out or takeover and
   confirms the UI shows a blocked state rather than false success.
4. At a 390px-wide viewport, assert the workbench remains usable, the primary
   controls are reachable, and no horizontal overflow hides the story.
5. Document browser prerequisites, port 8105, reset, and
   `npm --prefix e2e run test`.

**Red verification**: Run `npm --prefix e2e run test` before the application
and spec are complete; it must fail with the missing/unmet primary-flow
assertion.

**Green verification**: Run `npm --prefix e2e run test`; expected result is all
desktop and mobile specs pass. Then run the Python suite again.

### Step 4: Add strictly lightweight fixture attribution analytics

1. Define a small in-memory event shape in the existing store/service boundary,
   with `event_type`, `conversation_id`, `source`, `workflow`, and timestamp.
   Use explicit `fixture` or `unknown` source values; never infer a live
   campaign or conversion.
2. Record only events already visible in the fixture story: inbound accepted,
   product answer, checkout link created, delivery update, human takeover,
   opt-out, and outbound retry/dead-letter state where applicable. Reset must
   clear these events.
3. Add one read endpoint for the current conversation, such as
   `/inbox/{conversation_id}/analytics`, returning the event list and a small
   summary. Keep it workspace-scoped like the existing endpoints.
4. Add a compact attribution/status panel to `apps/web/index.html` showing
   source, workflow, and outcome with a `fixture-only` label. Do not add a
   dashboard, database schema, worker, or campaign builder.
5. Add focused API tests for event idempotency, reset clearing, and explicit
   `unknown`/fixture source semantics.

**Red verification**: Add the analytics contract tests before the endpoint and
event recording; they must fail because no analytics surface exists.

**Green verification**: Run `python -B -m pytest -p no:cacheprovider tests/test_analytics.py tests/test_reset.py -q`; expected result is all focused tests passing. Rerun browser smoke and confirm the panel reflects only fixture events.

### Step 5: Reconcile setup and showcase documentation

1. Pin the tested Python dependency set or add a committed constraints/lock
   file. Keep the install command copy-pasteable on Windows.
2. Update `README.md`, `deployment.md`, and `tasks.md` so they no longer claim
   an unverified 25-test result. State the fresh command and result only after
   Step 1 passes.
3. Document API port 8105, `/health`, `/ready`, reset, shutdown, browser smoke,
   the fixture clock contract, payment-state distinction, and the exact
   live/fixture/blocked boundary.

**Verify**: From a fresh virtual environment, run the documented install,
`python -B -m pytest -p no:cacheprovider -q`, start on port 8105, check health
and readiness, reset twice, and run `npm --prefix e2e ci` followed by
`npm --prefix e2e run test`. Every command must exit 0.

### Step 6: Final showcase verification

Run in this order:

1. `python -B -m pytest -p no:cacheprovider -q` → all tests pass.
2. `python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8105`.
3. Check `/health` and `/ready` → process and fixture readiness are distinct.
4. Reset with the documented workspace header twice → same clean baseline.
5. `npm --prefix e2e ci` and `npm --prefix e2e run test` → desktop/mobile flow passes.
6. `git status --short` → only intended source/docs/plan files are modified.

## Test plan

- Clock tests: active and expired service-window policy with explicit UTC
  clocks; no test may depend on `datetime.now()`.
- Reset tests: delivery update, reset, replay delivery, order status, and
  repeated reset; assert mutable order/dedupe/workflow state is restored.
- API readiness tests: process health remains distinct from fixture readiness;
  workspace scope remains required for stateful routes.
- Browser tests: load fixture → product question → quantity 2 → checkout link,
  blocked policy state, mobile layout, and fixture attribution panel.
- Existing tests: preserve inbound normalization, dedupe, policy, templates,
  retry/dead-letter, order status, delivery idempotency, and handoff behavior.

## Done criteria

- [ ] Default fixture walkthrough remains inside an injected deterministic
  service window on any host date.
- [ ] `POST http://127.0.0.1:8105/demo/reset` restores inbound, order,
  delivery-event, workflow, outbound, clock, and analytics fixture state and is
  safe to repeat.
- [ ] `/health` reports process health and `/ready` reports fixture readiness.
- [ ] `python -B -m pytest -p no:cacheprovider -q` exits 0 from a fresh setup.
- [ ] No documented test count is stale or based on an unverified run.
- [ ] `npm --prefix e2e run test` covers desktop and 390px mobile primary flow.
- [ ] Non-2xx API responses produce visible blocked/error UI and cannot enable
  later success controls.
- [ ] Lightweight analytics shows only explicit fixture/unknown attribution and
  resets with the rest of demo state.
- [ ] README, deployment, and tasks document port 8105, setup, health,
  readiness, reset, browser smoke, shutdown, and provider boundaries.
- [ ] `git status --short` contains no files outside Scope.
- [ ] No push, PR, or merge occurred without explicit authorization.

## STOP conditions

Stop and report back if:

- Any Current state excerpt or endpoint contract has drifted from the planned
  SHA.
- Making the clock injectable requires changing a provider integration or
  durable persistence boundary.
- Resetting state would delete or mutate anything outside the in-memory demo
  workspace.
- Attribution work begins to require a database schema, queue, worker, live
  campaign integration, or claims beyond fixture/unknown source labels.
- The browser test cannot run on port 8105 without provider credentials or an
  undocumented manual dependency.
- A verification command fails twice after a reasonable correction attempt.
- A proposed change requires reproducing a credential, token, or `.env` value;
  record only file/line and credential type, then stop.

## Maintenance notes

- Future live adapters must not reuse the fixture clock or fixture attribution
  source without an explicit mode boundary.
- If the seeded event timestamp changes, update the fixture clock default,
  reset tests, browser assertions, and docs together.
- Reviewers should scrutinize reset completeness, final policy rechecks,
  payment-link-versus-payment wording, and whether analytics remains small and
  explicitly simulated.
- Durable persistence, signature validation, auth, queue workers, and live
  provider capability verification remain deferred.
