from fastapi.testclient import TestClient

from apps.api.main import create_app


def test_demo_page_contains_shared_workbench_schema_and_fixture_controls():
    response = TestClient(create_app()).get("/demo")

    assert response.status_code == 200
    assert "WhatsApp Commerce and Support" in response.text
    assert "--brand-blue" in response.text
    assert "Load inbound fixture" in response.text
    assert "link created" in response.text
    assert "fixture-only" in response.text


def test_demo_page_declares_non_2xx_error_contract():
    response = TestClient(create_app()).get("/demo")

    assert 'id="errorStatus"' in response.text
    assert 'role="alert"' in response.text
    assert "if (!response.ok)" in response.text
    assert "The fixture API could not complete that action." in response.text
