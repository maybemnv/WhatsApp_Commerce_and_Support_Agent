from fastapi.testclient import TestClient

from apps.api.main import create_app


WORKSPACE_ID = "workspace-demo"
PAYLOAD = {
    "event_id": "provider-event-analytics-001",
    "message_id": "provider-message-analytics-001",
    "from": "+15551234567",
    "text": "Is the blue product available?",
    "timestamp": "2026-08-09T10:00:00Z",
}


def _conversation(client: TestClient) -> str:
    response = client.post(
        "/webhooks/meta_cloud",
        headers={"X-Workspace-ID": WORKSPACE_ID},
        json=PAYLOAD,
    )
    assert response.status_code == 202
    return response.json()["conversation_id"]


def test_fixture_analytics_records_idempotent_story_events():
    client = TestClient(create_app())
    headers = {"X-Workspace-ID": WORKSPACE_ID}
    conversation_id = _conversation(client)

    product = client.post(
        f"/inbox/{conversation_id}/product-question",
        headers=headers,
        json={"text": "Is the blue product available?"},
    )
    product_replay = client.post(
        f"/inbox/{conversation_id}/product-question",
        headers=headers,
        json={"text": "Is the blue product available?"},
    )
    client.post(
        f"/inbox/{conversation_id}/select",
        headers=headers,
        json={"product_id": "blue-product-001", "quantity": 2},
    )
    client.post(f"/inbox/{conversation_id}/confirm", headers=headers)

    analytics = client.get(
        f"/inbox/{conversation_id}/analytics",
        headers=headers,
    )
    event_types = [event["event_type"] for event in analytics.json()["events"]]

    assert product.status_code == 200
    assert product_replay.status_code == 200
    assert analytics.status_code == 200
    assert analytics.json()["source"] == "fixture"
    assert analytics.json()["workflow"] == "commerce"
    assert event_types == [
        "inbound_accepted",
        "product_answered",
        "checkout_link_created",
    ]
    assert analytics.json()["summary"] == {
        "total": 3,
        "outcomes": {
            "inbound_accepted": 1,
            "product_answered": 1,
            "checkout_link_created": 1,
        },
    }


def test_fixture_analytics_reset_clears_previous_events():
    app = create_app()
    client = TestClient(app)
    headers = {"X-Workspace-ID": WORKSPACE_ID}
    conversation_id = _conversation(client)

    before = client.get(
        f"/inbox/{conversation_id}/analytics",
        headers=headers,
    )
    reset = client.post("/demo/reset", headers=headers)
    new_conversation_id = _conversation(client)
    after = client.get(
        f"/inbox/{new_conversation_id}/analytics",
        headers=headers,
    )

    assert before.json()["summary"]["total"] == 1
    assert reset.status_code == 200
    assert after.json()["summary"]["total"] == 1
    assert [event["event_type"] for event in after.json()["events"]] == ["inbound_accepted"]
    assert app.state.commerce_store.analytics_events


def test_unknown_attribution_source_is_explicitly_preserved():
    client = TestClient(create_app())
    conversation_id = _conversation(client)
    app = client.app
    app.state.commerce_service.record_analytics_event(
        conversation_id,
        event_type="handoff_requested",
        workflow="support",
        source="unknown",
        dedupe_key="handoff-unknown-1",
    )

    analytics = client.get(
        f"/inbox/{conversation_id}/analytics",
        headers={"X-Workspace-ID": WORKSPACE_ID},
    )

    assert analytics.json()["events"][-1]["source"] == "unknown"
