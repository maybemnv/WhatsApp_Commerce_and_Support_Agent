# Production-ready repository baseline

The fixture deployment remains provider-free. Outside `APP_ENV=local-fixture`,
startup requires `DATABASE_URL`, `QUEUE_PROVIDER=redis` or
`postgres-outbox`, `AUTH_BEARER_TOKEN`, and `WHATSAPP_WEBHOOK_SECRET`.

```powershell
psql "$env:DATABASE_URL" -f db/migrations/001_whatsapp_demo.sql
uvicorn apps.api.main:app --host 0.0.0.0 --port ${env:PORT ?? 8105}
```

All non-health routes require the server-side bearer boundary. Webhooks require
an HMAC SHA-256 signature, and final outbound policy is re-evaluated by the
existing commerce service immediately before provider submission. The current
runtime intentionally fails closed outside fixture mode until the durable
PostgreSQL repository/worker is selected; Meta credentials remain pending and
no provider is called by CI.
