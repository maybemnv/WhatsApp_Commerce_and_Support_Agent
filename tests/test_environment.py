import pytest

from apps.api.environment import RuntimeConfigurationError, app_environment, validate_runtime


def test_missing_app_env_defaults_to_fail_closed_production(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    for name in ("DATABASE_URL", "QUEUE_PROVIDER", "AUTH_BEARER_TOKEN", "WHATSAPP_WEBHOOK_SECRET"):
        monkeypatch.delenv(name, raising=False)

    assert app_environment() == "production"
    with pytest.raises(RuntimeConfigurationError, match="production runtime requires"):
        validate_runtime()
