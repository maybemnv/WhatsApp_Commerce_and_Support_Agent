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


def test_opt_out_blocks_product_reply_and_is_visible_in_policy():
    client = TestClient(create_app())
    headers = {"X-Workspace-ID": WORKSPACE_ID}
    accepted = client.post(
        "/webhooks/meta_cloud",
        headers=headers,
        json=PAYLOAD,
    )
    conversation_id = accepted.json()["conversation_id"]

    opted_out = client.post(
        f"/inbox/{conversation_id}/policy/opt-out",
        headers=headers,
    )
    blocked = client.post(
        f"/inbox/{conversation_id}/product-question",
        headers=headers,
        json={"text": "Is the blue product available?"},
    )
    policy = client.get(
        f"/inbox/{conversation_id}/policy",
        headers=headers,
    )

    assert opted_out.status_code == 200
    assert blocked.status_code == 422
    assert blocked.json()["detail"] == "outbound blocked: opt-out is active"
    assert policy.json() == {
        "allowed": False,
        "code": "opted_out",
        "reason": "outbound blocked: opt-out is active",
    }


def test_human_takeover_blocks_until_explicit_resume():
    client = TestClient(create_app())
    headers = {"X-Workspace-ID": WORKSPACE_ID}
    accepted = client.post(
        "/webhooks/meta_cloud",
        headers=headers,
        json=PAYLOAD,
    )
    conversation_id = accepted.json()["conversation_id"]

    takeover = client.post(
        f"/inbox/{conversation_id}/policy/takeover",
        headers=headers,
    )
    blocked = client.post(
        f"/inbox/{conversation_id}/product-question",
        headers=headers,
        json={"text": "Is the blue product available?"},
    )
    resumed = client.post(
        f"/inbox/{conversation_id}/policy/resume",
        headers=headers,
    )
    allowed = client.post(
        f"/inbox/{conversation_id}/product-question",
        headers=headers,
        json={"text": "Is the blue product available?"},
    )

    assert takeover.status_code == 200
    assert blocked.status_code == 422
    assert blocked.json()["detail"] == "outbound blocked: human takeover is active"
    assert resumed.status_code == 200
    assert allowed.status_code == 200


def test_takeover_exposes_a_handoff_brief_for_the_operator():
    client = TestClient(create_app())
    headers = {"X-Workspace-ID": WORKSPACE_ID}
    accepted = client.post(
        "/webhooks/meta_cloud",
        headers=headers,
        json=PAYLOAD,
    )
    conversation_id = accepted.json()["conversation_id"]

    takeover = client.post(
        f"/inbox/{conversation_id}/policy/takeover",
        headers=headers,
        json={"reason": "customer_requested"},
    )
    detail = client.get(
        f"/inbox/{conversation_id}",
        headers=headers,
    )

    assert takeover.status_code == 200
    assert takeover.json()["handoff_reason"] == "customer_requested"
    assert detail.json()["handoff"] == {
        "task_id": f"handoff-{conversation_id}",
        "state": "open",
        "reason": "customer_requested",
    }


def test_order_status_returns_safe_match_or_no_match():
    client = TestClient(create_app())
    headers = {"X-Workspace-ID": WORKSPACE_ID}
    accepted = client.post(
        "/webhooks/meta_cloud",
        headers=headers,
        json=PAYLOAD,
    )
    conversation_id = accepted.json()["conversation_id"]

    matched = client.post(
        f"/inbox/{conversation_id}/order-status",
        headers=headers,
        json={"reference": "ORDER-BLUE-001"},
    )
    no_match = client.post(
        f"/inbox/{conversation_id}/order-status",
        headers=headers,
        json={"reference": "ORDER-UNKNOWN"},
    )

    assert matched.status_code == 200
    assert matched.json()["state"] == "matched"
    assert matched.json()["status"] == "in_transit"
    assert matched.json()["source"] == "fixture-commerce"
    assert no_match.status_code == 200
    assert no_match.json() == {
        "state": "no_match",
        "message": "No order matched that reference. Please check the reference and try again.",
    }


def test_delivery_event_is_idempotent_and_updates_order_status():
    client = TestClient(create_app())
    headers = {"X-Workspace-ID": WORKSPACE_ID}
    accepted = client.post(
        "/webhooks/meta_cloud",
        headers=headers,
        json=PAYLOAD,
    )
    conversation_id = accepted.json()["conversation_id"]
    event = {
        "event_id": "delivery-event-001",
        "order_id": "ORDER-BLUE-001",
        "status": "delivered",
        "timestamp": "2026-08-09T12:00:00Z",
    }

    first = client.post(
        f"/inbox/{conversation_id}/delivery-event",
        headers=headers,
        json=event,
    )
    replay = client.post(
        f"/inbox/{conversation_id}/delivery-event",
        headers=headers,
        json=event,
    )
    status_response = client.post(
        f"/inbox/{conversation_id}/order-status",
        headers=headers,
        json={"reference": "ORDER-BLUE-001"},
    )

    assert first.status_code == 200
    assert first.json()["duplicate"] is False
    assert replay.status_code == 200
    assert replay.json()["duplicate"] is True
    assert status_response.json()["status"] == "delivered"
