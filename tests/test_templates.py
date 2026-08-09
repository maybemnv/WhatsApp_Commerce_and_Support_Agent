import pytest

from apps.api.commerce import CommerceDemoStore, CommerceError, CommerceService
from apps.api.inbound import InMemoryConversationStore, InboundWebhookService


WORKSPACE_ID = "workspace-demo"
PAYLOAD = {
    "event_id": "provider-event-template-001",
    "message_id": "provider-message-template-001",
    "from": "+15551234567",
    "text": "Where is my order?",
    "timestamp": "2026-08-09T10:00:00Z",
}


def _service() -> tuple[InMemoryConversationStore, CommerceService, str]:
    inbound_store = InMemoryConversationStore()
    accepted = InboundWebhookService(inbound_store).accept(
        PAYLOAD,
        adapter="meta_cloud",
        workspace_id=WORKSPACE_ID,
    )
    return inbound_store, CommerceService(inbound_store, CommerceDemoStore()), accepted.conversation_id


def test_template_registry_requires_exact_approved_variables():
    _, service, conversation_id = _service()

    with pytest.raises(CommerceError, match="variables must contain exactly"):
        service.enqueue_template(
            conversation_id,
            template_id="order_status_update",
            locale="en-US",
            variables={"order_id": "ORDER-BLUE-001"},
            workflow="order_status",
            idempotency_key="template-1",
        )

    templates = service.list_templates()
    assert [template["id"] for template in templates] == [
        "order_status_update",
        "appointment_reminder",
        "payment_link_follow_up",
        "human_handoff_ack",
        "service_window_reopen",
    ]


def test_template_enqueue_and_submission_are_idempotent():
    _, service, conversation_id = _service()
    payload = {
        "template_id": "order_status_update",
        "locale": "en-US",
        "variables": {
            "order_id": "ORDER-BLUE-001",
            "status": "in_transit",
            "tracking_id": "TRK-BLUE-001",
        },
        "workflow": "order_status",
        "idempotency_key": "template-2",
    }

    queued = service.enqueue_template(conversation_id, **payload)
    replay = service.enqueue_template(conversation_id, **payload)
    sent = service.submit_outbound(conversation_id, queued.command_id)
    sent_replay = service.submit_outbound(conversation_id, queued.command_id)

    assert replay == queued
    assert sent.status == "sent"
    assert sent.provider_result == "fixture_only"
    assert sent_replay == sent


def test_final_submission_rechecks_opt_out_and_takeover_state():
    inbound_store, service, conversation_id = _service()
    queued = service.enqueue_template(
        conversation_id,
        template_id="order_status_update",
        locale="en-US",
        variables={
            "order_id": "ORDER-BLUE-001",
            "status": "in_transit",
            "tracking_id": "TRK-BLUE-001",
        },
        workflow="order_status",
        idempotency_key="template-3",
    )

    inbound_store.opt_out(conversation_id)
    blocked = service.submit_outbound(conversation_id, queued.command_id)

    assert blocked.status == "blocked"
    assert blocked.policy_code == "opted_out"
    assert blocked.provider_result is None

    inbound_store2, service2, conversation_id2 = _service()
    queued2 = service2.enqueue_template(
        conversation_id2,
        template_id="order_status_update",
        locale="en-US",
        variables={
            "order_id": "ORDER-BLUE-001",
            "status": "in_transit",
            "tracking_id": "TRK-BLUE-001",
        },
        workflow="order_status",
        idempotency_key="template-4",
    )
    inbound_store2.take_over(conversation_id2, reason="customer_requested")
    takeover_blocked = service2.submit_outbound(conversation_id2, queued2.command_id)

    assert takeover_blocked.status == "blocked"
    assert takeover_blocked.policy_code == "human_takeover"


def test_transient_outbound_failures_use_bounded_retry_then_dead_letter():
    _, service, conversation_id = _service()
    queued = service.enqueue_template(
        conversation_id,
        template_id="order_status_update",
        locale="en-US",
        variables={
            "order_id": "ORDER-BLUE-001",
            "status": "in_transit",
            "tracking_id": "TRK-BLUE-001",
        },
        workflow="order_status",
        idempotency_key="template-retry-1",
    )

    first = service.fail_outbound(conversation_id, queued.command_id, "timeout")
    second = service.fail_outbound(conversation_id, queued.command_id, "rate_limit")
    third = service.fail_outbound(conversation_id, queued.command_id, "provider_unavailable")
    dead_letter = service.fail_outbound(conversation_id, queued.command_id, "provider_unavailable")

    assert first.status == "retryable"
    assert first.attempts == 1
    assert first.next_attempt_at is not None
    assert second.status == "retryable"
    assert third.status == "retryable"
    assert dead_letter.status == "dead_letter"
    assert dead_letter.attempts == 4
    assert dead_letter.last_error_code == "provider_unavailable"


def test_retry_rechecks_policy_before_releasing_a_failed_command():
    inbound_store, service, conversation_id = _service()
    queued = service.enqueue_template(
        conversation_id,
        template_id="order_status_update",
        locale="en-US",
        variables={
            "order_id": "ORDER-BLUE-001",
            "status": "in_transit",
            "tracking_id": "TRK-BLUE-001",
        },
        workflow="order_status",
        idempotency_key="template-retry-2",
    )
    service.fail_outbound(conversation_id, queued.command_id, "timeout")
    inbound_store.opt_out(conversation_id)

    blocked = service.retry_outbound(conversation_id, queued.command_id)

    assert blocked.status == "blocked"
    assert blocked.policy_code == "opted_out"
