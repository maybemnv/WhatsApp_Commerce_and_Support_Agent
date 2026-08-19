from datetime import datetime, timezone

from apps.api.commerce import CommerceDemoStore, CommerceService
from apps.api.inbound import InMemoryConversationStore, InboundWebhookService


WORKSPACE_ID = "workspace-demo"
PAYLOAD = {
    "event_id": "provider-event-commerce-001",
    "message_id": "provider-message-commerce-001",
    "from": "+15551234567",
    "text": "Is the blue product available?",
    "timestamp": "2026-08-09T10:00:00Z",
}


def _conversation_id():
    inbound_store = InMemoryConversationStore()
    accepted = InboundWebhookService(inbound_store).accept(
        PAYLOAD,
        adapter="meta_cloud",
        workspace_id=WORKSPACE_ID,
    )
    return inbound_store, accepted.conversation_id


def test_product_question_returns_approved_facts_and_source_trace():
    inbound_store, conversation_id = _conversation_id()
    service = CommerceService(
        inbound_store,
        CommerceDemoStore(),
        clock=lambda: datetime(2026, 8, 9, 12, tzinfo=timezone.utc),
    )

    result = service.answer_product_question(
        conversation_id,
        "Is the blue product available?",
    )

    assert result.state == "awaiting_confirmation"
    assert result.product_id == "blue-product-001"
    assert result.product_name == "Blue Product"
    assert result.availability == "available"
    assert result.source == "fixture-catalog"
    assert "Blue Product" in result.message


def test_confirmed_selection_creates_payment_link_without_claiming_payment_success():
    inbound_store, conversation_id = _conversation_id()
    service = CommerceService(
        inbound_store,
        CommerceDemoStore(),
        clock=lambda: datetime(2026, 8, 9, 12, tzinfo=timezone.utc),
    )

    service.answer_product_question(conversation_id, "Is the blue product available?")
    service.select_product(conversation_id, product_id="blue-product-001", quantity=2)
    result = service.confirm_purchase(conversation_id)
    replay = service.confirm_purchase(conversation_id)

    assert result.state == "awaiting_external_event"
    assert result.quantity == 2
    assert result.payment_status == "link_created"
    assert result.payment_link.startswith("https://checkout.example.test/")
    assert result.conversion is False
    assert replay.payment_link == result.payment_link
