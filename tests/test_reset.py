from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.inbound import InMemoryConversationStore, InboundWebhookService


WORKSPACE_ID = "workspace-demo"
PAYLOAD = {
    "event_id": "provider-event-reset-001",
    "message_id": "provider-message-reset-001",
    "from": "+15551234567",
    "text": "Is the blue product available?",
    "timestamp": "2026-08-09T10:00:00Z",
}


def test_default_fixture_clock_keeps_seeded_window_active():
    client = TestClient(create_app())
    headers = {"X-Workspace-ID": WORKSPACE_ID}

    accepted = client.post("/webhooks/meta_cloud", headers=headers, json=PAYLOAD)
    conversation_id = accepted.json()["conversation_id"]
    response = client.post(
        f"/inbox/{conversation_id}/product-question",
        headers=headers,
        json={"text": "Is the blue product available?"},
    )

    assert response.status_code == 200
    assert response.json()["state"] == "awaiting_confirmation"


def test_explicit_fixture_clock_can_block_expired_window(monkeypatch):
    monkeypatch.setenv("WHATSAPP_DEMO_NOW", "2026-08-10T10:00:01Z")
    client = TestClient(create_app())
    headers = {"X-Workspace-ID": WORKSPACE_ID}

    accepted = client.post("/webhooks/meta_cloud", headers=headers, json=PAYLOAD)
    conversation_id = accepted.json()["conversation_id"]
    response = client.post(
        f"/inbox/{conversation_id}/product-question",
        headers=headers,
        json={"text": "Is the blue product available?"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "outbound blocked: service window is closed"


def test_reset_restores_delivery_and_is_safe_to_repeat():
    client = TestClient(create_app())
    headers = {"X-Workspace-ID": WORKSPACE_ID}
    accepted = client.post("/webhooks/meta_cloud", headers=headers, json=PAYLOAD)
    conversation_id = accepted.json()["conversation_id"]
    event = {
        "event_id": "delivery-event-reset-001",
        "order_id": "ORDER-BLUE-001",
        "status": "delivered",
        "timestamp": "2026-08-09T12:00:00Z",
    }

    delivered = client.post(
        f"/inbox/{conversation_id}/delivery-event",
        headers=headers,
        json=event,
    )
    first_reset = client.post("/demo/reset", headers=headers)
    second_reset = client.post("/demo/reset", headers=headers)

    replay = client.post(
        "/webhooks/meta_cloud",
        headers=headers,
        json=PAYLOAD,
    )
    replay_conversation_id = replay.json()["conversation_id"]
    replay_delivery = client.post(
        f"/inbox/{replay_conversation_id}/delivery-event",
        headers=headers,
        json=event,
    )
    order_status = client.post(
        f"/inbox/{replay_conversation_id}/order-status",
        headers=headers,
        json={"reference": "ORDER-BLUE-001"},
    )

    assert delivered.json()["duplicate"] is False
    assert first_reset.status_code == 200
    assert first_reset.json()["mode"] == "fixture"
    assert second_reset.status_code == 200
    assert replay.json()["duplicate"] is False
    assert replay_delivery.json()["duplicate"] is False
    assert order_status.json()["status"] == "delivered"


def test_ready_is_distinct_from_process_health():
    client = TestClient(create_app())

    health = client.get("/health")
    ready = client.get("/ready")

    assert health.json() == {"status": "ok", "mode": "fixture"}
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ready.json()["mode"] == "fixture"
    assert ready.json()["catalog"] == "ready"
    assert ready.json()["seed_order"] == "ready"


def test_inbound_store_reset_clears_all_mutable_state():
    store = InMemoryConversationStore()
    InboundWebhookService(store).accept(
        PAYLOAD,
        adapter="meta_cloud",
        workspace_id=WORKSPACE_ID,
    )

    store.reset()

    assert store.events == {}
    assert store.conversations == {}
    assert store.messages == {}
