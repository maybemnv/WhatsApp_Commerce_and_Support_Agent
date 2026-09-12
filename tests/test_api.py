from threading import Event, Thread

from fastapi.testclient import TestClient

from apps.api.inbound import InMemoryConversationStore, normalize_inbound
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


def test_template_enqueue_and_final_policy_recheck_are_visible_in_api():
    client = TestClient(create_app())
    headers = {"X-Workspace-ID": WORKSPACE_ID}
    accepted = client.post(
        "/webhooks/meta_cloud",
        headers=headers,
        json=PAYLOAD,
    )
    conversation_id = accepted.json()["conversation_id"]

    templates = client.get(
        f"/inbox/{conversation_id}/templates",
        headers=headers,
    )
    queued = client.post(
        f"/inbox/{conversation_id}/outbound/templates",
        headers=headers,
        json={
            "template_id": "order_status_update",
            "locale": "en-US",
            "variables": {
                "order_id": "ORDER-BLUE-001",
                "status": "in_transit",
                "tracking_id": "TRK-BLUE-001",
            },
            "workflow": "order_status",
            "idempotency_key": "api-template-1",
        },
    )
    client.post(f"/inbox/{conversation_id}/policy/opt-out", headers=headers)
    blocked = client.post(
        f"/inbox/{conversation_id}/outbound/{queued.json()['command_id']}/submit",
        headers=headers,
    )

    assert templates.status_code == 200
    assert templates.json()["items"][0]["id"] == "order_status_update"
    assert queued.status_code == 200
    assert queued.json()["status"] == "queued"
    assert blocked.status_code == 200
    assert blocked.json()["status"] == "blocked"
    assert blocked.json()["policy_code"] == "opted_out"


def test_transient_template_failure_exposes_retry_and_dead_letter_controls():
    client = TestClient(create_app())
    headers = {"X-Workspace-ID": WORKSPACE_ID}
    accepted = client.post("/webhooks/meta_cloud", headers=headers, json=PAYLOAD)
    conversation_id = accepted.json()["conversation_id"]
    template = {
        "template_id": "order_status_update",
        "locale": "en-US",
        "variables": {
            "order_id": "ORDER-BLUE-001",
            "status": "in_transit",
            "tracking_id": "TRK-BLUE-001",
        },
        "workflow": "order_status",
        "idempotency_key": "api-template-retry-1",
    }
    queued = client.post(
        f"/inbox/{conversation_id}/outbound/templates",
        headers=headers,
        json=template,
    ).json()
    command_id = queued["command_id"]

    for error_code in ("timeout", "rate_limit", "provider_unavailable", "provider_unavailable"):
        failure = client.post(
            f"/inbox/{conversation_id}/outbound/{command_id}/fail",
            headers=headers,
            json={"error_code": error_code},
        )

    assert failure.status_code == 200
    assert failure.json()["status"] == "dead_letter"
    assert failure.json()["attempts"] == 4


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


def test_fixture_appointment_and_lead_outcomes_are_audited_without_connectors():
    client = TestClient(create_app())
    headers = {"X-Workspace-ID": WORKSPACE_ID}
    conversation_id = client.post("/webhooks/meta_cloud", headers=headers, json=PAYLOAD).json()["conversation_id"]

    appointment = client.post(
        f"/inbox/{conversation_id}/appointment",
        headers=headers,
        json={"customer_name": "Jordan Lee", "appointment_at": "2026-08-12T15:00:00Z"},
    )
    lead = client.post(
        f"/inbox/{conversation_id}/lead",
        headers=headers,
        json={"name": "Jordan Lee", "email": "jordan@example.test", "interest": "Blue Product"},
    )
    analytics = client.get(f"/inbox/{conversation_id}/analytics", headers=headers)

    assert appointment.json() == {
        "state": "awaiting_external_event",
        "outcome": "appointment_requested",
        "provider_result": "fixture_only",
    }
    assert lead.json() == {
        "state": "completed",
        "outcome": "lead_qualified",
        "provider_result": "fixture_only",
    }
    assert [event["event_type"] for event in analytics.json()["events"]][-2:] == [
        "appointment_requested",
        "lead_qualified",
    ]


def test_operator_lifecycle_is_versioned_and_keeps_automation_paused_until_resumed():
    client = TestClient(create_app())
    headers = {"X-Workspace-ID": WORKSPACE_ID}
    conversation_id = client.post("/webhooks/meta_cloud", headers=headers, json=PAYLOAD).json()["conversation_id"]
    takeover = client.post(f"/inbox/{conversation_id}/policy/takeover", headers=headers).json()

    first_claim = client.post(
        f"/inbox/{conversation_id}/handoff/claim",
        headers=headers,
        json={"operator_id": "operator-1", "expected_version": takeover["version"]},
    )
    stale_claim = client.post(
        f"/inbox/{conversation_id}/handoff/claim",
        headers=headers,
        json={"operator_id": "operator-2", "expected_version": takeover["version"]},
    )
    reply = client.post(
        f"/inbox/{conversation_id}/handoff/reply",
        headers=headers,
        json={"operator_id": "operator-1", "text": "I can help with that."},
    )
    resolved = client.post(
        f"/inbox/{conversation_id}/handoff/resolve",
        headers=headers,
        json={"operator_id": "operator-1"},
    )
    blocked = client.post(
        f"/inbox/{conversation_id}/product-question",
        headers=headers,
        json={"text": "Is the blue product available?"},
    )
    resumed = client.post(f"/inbox/{conversation_id}/policy/resume", headers=headers)

    assert first_claim.json()["state"] == "claimed"
    assert stale_claim.status_code == 409
    assert stale_claim.json()["detail"] == "handoff version conflict"
    assert reply.json()["state"] == "claimed"
    assert resolved.json()["state"] == "resolved"
    assert blocked.status_code == 422
    assert blocked.json()["detail"] == "outbound blocked: human takeover is active"
    assert resumed.json()["human_takeover"] is False


def test_reconsent_is_distinct_from_resume_and_control_data_is_visible():
    client = TestClient(create_app())
    headers = {"X-Workspace-ID": WORKSPACE_ID}
    conversation_id = client.post("/webhooks/meta_cloud", headers=headers, json=PAYLOAD).json()["conversation_id"]

    client.post(f"/inbox/{conversation_id}/policy/opt-out", headers=headers)
    resume = client.post(f"/inbox/{conversation_id}/policy/resume", headers=headers)
    reconsent = client.post(
        f"/inbox/{conversation_id}/policy/reconsent",
        headers=headers,
        json={"operator_id": "operator-1", "evidence": "fixture customer asked to receive messages"},
    )
    controls = client.get(f"/inbox/{conversation_id}/controls", headers=headers)

    assert resume.status_code == 409
    assert reconsent.json() == {"conversation_id": conversation_id, "opted_out": False, "consent": "reconfirmed"}
    assert controls.json()["templates"][0]["id"] == "order_status_update"
    assert controls.json()["outbound"] == []
    assert controls.json()["attribution"]["source"] == "fixture"


def test_resume_waits_for_the_conversation_lock():
    store = InMemoryConversationStore()
    store.accept(normalize_inbound(PAYLOAD, adapter="meta_cloud", workspace_id=WORKSPACE_ID))
    conversation_id = next(iter(store.conversations))
    store.take_over(conversation_id)
    finished = Event()
    store._lock.acquire()
    try:
        worker = Thread(target=lambda: (store.resume(conversation_id), finished.set()))
        worker.start()
        assert not finished.wait(0.05)
    finally:
        store._lock.release()
    worker.join()
    assert finished.is_set()


def test_opt_out_waits_for_the_conversation_lock():
    store = InMemoryConversationStore()
    store.accept(normalize_inbound(PAYLOAD, adapter="meta_cloud", workspace_id=WORKSPACE_ID))
    conversation_id = next(iter(store.conversations))
    started = Event()
    finished = Event()

    def opt_out():
        started.set()
        store.opt_out(conversation_id)
        finished.set()

    store._lock.acquire()
    try:
        worker = Thread(target=opt_out)
        worker.start()
        assert started.wait(1)
        assert not finished.wait(0.05)
    finally:
        store._lock.release()
    worker.join()
    assert finished.is_set()


def test_takeover_after_resolved_handoff_creates_a_fresh_open_task():
    client = TestClient(create_app())
    headers = {"X-Workspace-ID": WORKSPACE_ID}
    conversation_id = client.post("/webhooks/meta_cloud", headers=headers, json=PAYLOAD).json()["conversation_id"]
    first = client.post(f"/inbox/{conversation_id}/policy/takeover", headers=headers).json()
    client.post(f"/inbox/{conversation_id}/handoff/claim", headers=headers, json={"operator_id": "operator-1", "expected_version": first["version"]})
    client.post(f"/inbox/{conversation_id}/handoff/resolve", headers=headers, json={"operator_id": "operator-1"})
    client.post(f"/inbox/{conversation_id}/policy/resume", headers=headers)

    second = client.post(f"/inbox/{conversation_id}/policy/takeover", headers=headers, json={"reason": "new_request"})
    detail = client.get(f"/inbox/{conversation_id}", headers=headers)

    assert second.status_code == 200
    assert detail.json()["handoff"]["state"] == "open"
    assert detail.json()["handoff"]["reason"] == "new_request"


def test_conversation_detail_reports_current_handoff_state():
    client = TestClient(create_app())
    headers = {"X-Workspace-ID": WORKSPACE_ID}
    conversation_id = client.post("/webhooks/meta_cloud", headers=headers, json=PAYLOAD).json()["conversation_id"]
    takeover = client.post(f"/inbox/{conversation_id}/policy/takeover", headers=headers).json()
    client.post(f"/inbox/{conversation_id}/handoff/claim", headers=headers, json={"operator_id": "operator-1", "expected_version": takeover["version"]})

    detail = client.get(f"/inbox/{conversation_id}", headers=headers)

    assert detail.json()["handoff"]["state"] == "claimed"


def test_repeated_opt_out_and_reconsent_cycles_are_recorded():
    client = TestClient(create_app())
    headers = {"X-Workspace-ID": WORKSPACE_ID}
    conversation_id = client.post("/webhooks/meta_cloud", headers=headers, json=PAYLOAD).json()["conversation_id"]
    for cycle in range(2):
        client.post(f"/inbox/{conversation_id}/policy/opt-out", headers=headers)
        client.post(f"/inbox/{conversation_id}/policy/reconsent", headers=headers, json={"operator_id": "operator-1", "evidence": f"cycle-{cycle}"})

    analytics = client.get(f"/inbox/{conversation_id}/analytics", headers=headers).json()

    event_types = [event["event_type"] for event in analytics["events"]]
    assert event_types.count("opt_out") == 2
    assert event_types.count("consent_reconfirmed") == 2
