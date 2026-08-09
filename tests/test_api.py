from fastapi.testclient import TestClient

from apps.api.main import create_app


WORKSPACE_ID = "workspace-demo"
PAYLOAD = {
    "event_id": "provider-event-api-001",
    "message_id": "provider-message-api-001",
    "from": "+15551234567",
    "text": "Is the blue product available?",
    "timestamp": "2026-08-09T10:00:00Z",
}


def test_webhook_accepts_and_deduplicates_fixture_event():
    client = TestClient(create_app())

    first = client.post(
        "/webhooks/meta_cloud",
        headers={"X-Workspace-ID": WORKSPACE_ID},
        json=PAYLOAD,
    )
    second = client.post(
        "/webhooks/meta_cloud",
        headers={"X-Workspace-ID": WORKSPACE_ID},
        json=PAYLOAD,
    )

    assert first.status_code == 202
    assert first.json()["duplicate"] is False
    assert second.status_code == 202
    assert second.json()["duplicate"] is True
    assert second.json()["conversation_id"] == first.json()["conversation_id"]


def test_inbox_exposes_customer_message_and_service_window():
    client = TestClient(create_app())

    accepted = client.post(
        "/webhooks/meta_cloud",
        headers={"X-Workspace-ID": WORKSPACE_ID},
        json=PAYLOAD,
    )
    conversation_id = accepted.json()["conversation_id"]

    response = client.get(
        "/inbox",
        headers={"X-Workspace-ID": WORKSPACE_ID},
    )

    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "conversation_id": conversation_id,
            "customer_identity": "+15551234567",
            "status": "open",
            "window_status": "active",
            "message_count": 1,
            "latest_message": "Is the blue product available?",
        }
    ]


def test_missing_workspace_scope_is_rejected():
    client = TestClient(create_app())

    response = client.post("/webhooks/meta_cloud", json=PAYLOAD)

    assert response.status_code == 400
    assert response.json()["detail"] == "X-Workspace-ID is required"


def test_demo_commerce_path_returns_product_then_payment_link():
    client = TestClient(create_app())
    headers = {"X-Workspace-ID": WORKSPACE_ID}

    accepted = client.post(
        "/webhooks/meta_cloud",
        headers=headers,
        json=PAYLOAD,
    )
    conversation_id = accepted.json()["conversation_id"]

    product = client.post(
        f"/inbox/{conversation_id}/product-question",
        headers=headers,
        json={"text": "Is the blue product available?"},
    )
    selection = client.post(
        f"/inbox/{conversation_id}/select",
        headers=headers,
        json={"product_id": "blue-product-001", "quantity": 2},
    )
    payment = client.post(
        f"/inbox/{conversation_id}/confirm",
        headers=headers,
    )

    assert product.status_code == 200
    assert product.json()["state"] == "awaiting_confirmation"
    assert selection.status_code == 200
    assert selection.json()["quantity"] == 2
    assert payment.status_code == 200
    assert payment.json()["payment_status"] == "link_created"
    assert payment.json()["conversion"] is False
