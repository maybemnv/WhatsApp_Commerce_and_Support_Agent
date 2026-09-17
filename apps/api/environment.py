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
    if app_environment() != "local-fixture":
        raise RuntimeConfigurationError(
            "fixture-only service requires APP_ENV=local-fixture"
        )


def is_local_fixture() -> bool:
    return app_environment() == "local-fixture"
