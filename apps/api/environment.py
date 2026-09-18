"""Runtime boundary for the fixture-only checkout."""

from __future__ import annotations

import os


class RuntimeConfigurationError(ValueError):
    """Raised when fixture code is selected for a deploy environment."""


def app_environment() -> str:
    value = os.getenv("APP_ENV", "production").strip().lower()
    if value not in {"local-fixture", "staging", "production"}:
        raise RuntimeConfigurationError(
            "APP_ENV must be local-fixture, staging, or production"
        )
    return value


def validate_runtime() -> None:
    if app_environment() == "local-fixture":
        return
    required = {
        "DATABASE_URL": os.getenv("DATABASE_URL"),
        "QUEUE_PROVIDER": os.getenv("QUEUE_PROVIDER"),
        "AUTH_BEARER_TOKEN": os.getenv("AUTH_BEARER_TOKEN"),
        "WHATSAPP_WEBHOOK_SECRET": os.getenv("WHATSAPP_WEBHOOK_SECRET"),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeConfigurationError(
            "production runtime requires: "
            + ", ".join(missing)
            + "; use APP_ENV=local-fixture for the fixture runtime"
        )
    if required["QUEUE_PROVIDER"] not in {"redis", "postgres-outbox"}:
        raise RuntimeConfigurationError(
            "QUEUE_PROVIDER must be redis or postgres-outbox outside fixture mode"
        )


def is_local_fixture() -> bool:
    return app_environment() == "local-fixture"
