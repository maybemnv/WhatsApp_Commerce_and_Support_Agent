"""Normalized inbound WhatsApp events and a deterministic demo store."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any, Literal, Mapping
from uuid import UUID, uuid5


ChannelAdapter = Literal["meta_cloud", "twilio_whatsapp"]
InboundKind = Literal["text", "template", "interactive", "media"]
SUPPORTED_ADAPTERS = {"meta_cloud", "twilio_whatsapp"}
SUPPORTED_KINDS = {"text", "template", "interactive", "media"}
WHATSAPP_NAMESPACE = UUID("b2d6692c-b72e-4e2b-971a-83bd8b846b5f")


class InboundValidationError(ValueError):
    """Raised when an inbound payload cannot be normalized safely."""


@dataclass(frozen=True, slots=True)
class InboundEvent:
    event_id: str
    workspace_id: str
    adapter: ChannelAdapter
    channel_identity: str
    provider_message_id: str
    kind: InboundKind
    body_text: str | None
    occurred_at: datetime
    raw_payload_reference: str


@dataclass(slots=True)
class Conversation:
    id: str
    workspace_id: str
    customer_identity: str
    status: str = "open"
    version: int = 1
    window_opened_at: datetime | None = None
    window_expires_at: datetime | None = None
    window_status: str = "unknown"
    opted_out: bool = False
    human_takeover: bool = False


@dataclass(frozen=True, slots=True)
class Message:
    id: str
    conversation_id: str
    provider_message_id: str
    body_text: str | None
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class AcceptResult:
    event_id: str
    conversation_id: str
    duplicate: bool


@dataclass(slots=True)
class InMemoryConversationStore:
    """Deterministic state store for the demo and domain tests.

    The interface is intentionally small so it can be replaced by the PRD's
    PostgreSQL repository without changing webhook normalization behavior.
    """

    events: dict[str, InboundEvent] = field(default_factory=dict)
    conversations: dict[str, Conversation] = field(default_factory=dict)
    messages: dict[str, Message] = field(default_factory=dict)

    def accept(self, event: InboundEvent) -> AcceptResult:
        event_key = _event_key(event)
        conversation_id = _conversation_id(event)
        if event_key in self.events:
            return AcceptResult(
                event_id=event.event_id,
                conversation_id=conversation_id,
                duplicate=True,
            )

        self.events[event_key] = event
        conversation = self.conversations.get(conversation_id)
        if conversation is None:
            conversation = Conversation(
                id=conversation_id,
                workspace_id=event.workspace_id,
                customer_identity=event.channel_identity,
            )
            self.conversations[conversation_id] = conversation

        if conversation.window_opened_at is None or event.occurred_at > conversation.window_opened_at:
            conversation.window_opened_at = event.occurred_at
            conversation.window_expires_at = event.occurred_at + timedelta(hours=24)
            conversation.window_status = "active"
            conversation.version += 1

        message_id = _message_id(event)
        self.messages.setdefault(
            message_id,
            Message(
                id=message_id,
                conversation_id=conversation_id,
                provider_message_id=event.provider_message_id,
                body_text=event.body_text,
                occurred_at=event.occurred_at,
            ),
        )
        return AcceptResult(
            event_id=event.event_id,
            conversation_id=conversation_id,
            duplicate=False,
        )

    def opt_out(self, conversation_id: str) -> Conversation:
        conversation = self._conversation(conversation_id)
        conversation.opted_out = True
        conversation.status = "opted_out"
        conversation.version += 1
        return conversation

    def take_over(self, conversation_id: str) -> Conversation:
        conversation = self._conversation(conversation_id)
        conversation.human_takeover = True
        conversation.status = "human_handoff"
        conversation.version += 1
        return conversation

    def resume(self, conversation_id: str) -> Conversation:
        conversation = self._conversation(conversation_id)
        if conversation.opted_out:
            raise ValueError("cannot resume an opted-out conversation")
        conversation.human_takeover = False
        conversation.status = "open"
        conversation.version += 1
        return conversation

    def _conversation(self, conversation_id: str) -> Conversation:
        conversation = self.conversations.get(conversation_id)
        if conversation is None:
            raise KeyError("conversation not found")
        return conversation


class InboundWebhookService:
    def __init__(self, store: InMemoryConversationStore) -> None:
        self.store = store

    def accept(
        self,
        payload: Mapping[str, Any],
        *,
        adapter: ChannelAdapter,
        workspace_id: str,
    ) -> AcceptResult:
        return self.store.accept(
            normalize_inbound(payload, adapter=adapter, workspace_id=workspace_id)
        )


def normalize_inbound(
    payload: Mapping[str, Any],
    *,
    adapter: ChannelAdapter,
    workspace_id: str,
) -> InboundEvent:
    """Normalize the fixture provider envelope into the PRD inbound contract."""

    if adapter not in SUPPORTED_ADAPTERS:
        raise InboundValidationError(f"unsupported adapter: {adapter}")
    if not workspace_id.strip():
        raise InboundValidationError("workspace_id is required")
    if not isinstance(payload, Mapping):
        raise InboundValidationError("payload must be an object")

    event_id = _required_text(payload, "event_id")
    provider_message_id = _required_text(payload, "message_id")
    channel_identity = _required_text(payload, "from")
    body_text = _optional_text(payload, "text")
    kind = payload.get("kind", "text")
    if kind not in SUPPORTED_KINDS:
        raise InboundValidationError(f"unsupported inbound kind: {kind}")
    if kind == "text" and body_text is None:
        raise InboundValidationError("text inbound events require text")

    timestamp = _required_text(payload, "timestamp")
    occurred_at = _parse_timestamp(timestamp)
    raw_reference = _optional_text(payload, "raw_payload_reference") or f"fixture:{event_id}"
    return InboundEvent(
        event_id=event_id,
        workspace_id=workspace_id,
        adapter=adapter,
        channel_identity=channel_identity,
        provider_message_id=provider_message_id,
        kind=kind,
        body_text=body_text,
        occurred_at=occurred_at,
        raw_payload_reference=raw_reference,
    )


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InboundValidationError(f"{key} is required")
    return value.strip()


def _optional_text(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise InboundValidationError(f"{key} must be text")
    value = value.strip()
    return value or None


def _parse_timestamp(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise InboundValidationError("timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise InboundValidationError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _stable_id(prefix: str, value: str) -> str:
    digest = sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def _event_key(event: InboundEvent) -> str:
    return f"{event.workspace_id}:{event.adapter}:{event.event_id}"


def _conversation_id(event: InboundEvent) -> str:
    return "conv_" + str(
        uuid5(
            WHATSAPP_NAMESPACE,
            f"{event.workspace_id}:{event.adapter}:{event.channel_identity}",
        )
    )


def _message_id(event: InboundEvent) -> str:
    return _stable_id(
        "msg",
        f"{event.workspace_id}:{event.adapter}:{event.provider_message_id}",
    )
