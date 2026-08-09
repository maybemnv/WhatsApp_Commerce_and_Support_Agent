from datetime import datetime, timedelta, timezone

from apps.api.inbound import InMemoryConversationStore, InboundWebhookService, normalize_inbound


WORKSPACE_ID = "workspace-demo"
PAYLOAD = {
    "event_id": "provider-event-001",
    "message_id": "provider-message-001",
    "from": "+15551234567",
    "text": "Is the blue product available?",
    "timestamp": "2026-08-09T10:00:00Z",
}


def test_normalizes_fixture_event_into_typed_inbound_envelope():
    event = normalize_inbound(
        PAYLOAD,
        adapter="meta_cloud",
        workspace_id=WORKSPACE_ID,
    )

    assert event.event_id == "provider-event-001"
    assert event.provider_message_id == "provider-message-001"
    assert event.channel_identity == "+15551234567"
    assert event.body_text == "Is the blue product available?"
    assert event.adapter == "meta_cloud"
    assert event.occurred_at == datetime(2026, 8, 9, 10, tzinfo=timezone.utc)


def test_replayed_event_creates_one_message_and_one_conversation():
    store = InMemoryConversationStore()
    service = InboundWebhookService(store)

    first = service.accept(PAYLOAD, adapter="meta_cloud", workspace_id=WORKSPACE_ID)
    second = service.accept(PAYLOAD, adapter="meta_cloud", workspace_id=WORKSPACE_ID)

    assert first.duplicate is False
    assert second.duplicate is True
    assert second.conversation_id == first.conversation_id
    assert len(store.messages) == 1
    assert len(store.conversations) == 1
    assert len(store.events) == 1


def test_accepted_inbound_message_opens_a_24_hour_service_window():
    store = InMemoryConversationStore()
    service = InboundWebhookService(store)

    result = service.accept(PAYLOAD, adapter="meta_cloud", workspace_id=WORKSPACE_ID)
    conversation = store.conversations[result.conversation_id]

    assert conversation.customer_identity == "+15551234567"
    assert conversation.window_opened_at == datetime(2026, 8, 9, 10, tzinfo=timezone.utc)
    assert conversation.window_expires_at == conversation.window_opened_at + timedelta(hours=24)
    assert conversation.window_status == "active"
