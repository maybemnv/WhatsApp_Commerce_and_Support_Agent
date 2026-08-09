"""FastAPI entry point for the fixture-backed WhatsApp demo."""

from __future__ import annotations

from datetime import datetime, timezone
from fastapi import FastAPI, Header, HTTPException, status
from fastapi.responses import FileResponse
from pathlib import Path

from .commerce import CommerceDemoStore, CommerceError, CommerceService
from .inbound import InMemoryConversationStore, InboundValidationError, InboundWebhookService
from .policy import OutboundPolicy


def create_app(store: InMemoryConversationStore | None = None) -> FastAPI:
    state_store = store or InMemoryConversationStore()
    webhook_service = InboundWebhookService(state_store)
    commerce_store = CommerceDemoStore()
    app = FastAPI(title="WhatsApp Commerce and Support Agent", version="0.1.0")
    app.state.store = state_store
    app.state.commerce_store = commerce_store
    app.state.clock = lambda: datetime.now(timezone.utc)
    commerce_service = CommerceService(
        state_store,
        commerce_store,
        policy=OutboundPolicy(),
        clock=lambda: app.state.clock(),
    )
    demo_page = Path(__file__).resolve().parents[1] / "web" / "index.html"

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": "fixture"}

    @app.get("/demo", include_in_schema=False)
    def demo() -> FileResponse:
        return FileResponse(demo_page, media_type="text/html")

    @app.post("/webhooks/{adapter}", status_code=status.HTTP_202_ACCEPTED)
    def receive_webhook(
        adapter: str,
        payload: dict,
        workspace_id: str | None = Header(default=None, alias="X-Workspace-ID"),
    ) -> dict[str, object]:
        if not workspace_id or not workspace_id.strip():
            raise HTTPException(status_code=400, detail="X-Workspace-ID is required")
        try:
            result = webhook_service.accept(
                payload,
                adapter=adapter,  # type: ignore[arg-type]
                workspace_id=workspace_id,
            )
        except InboundValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "accepted": True,
            "duplicate": result.duplicate,
            "event_id": result.event_id,
            "conversation_id": result.conversation_id,
        }

    @app.get("/inbox")
    def inbox(
        workspace_id: str | None = Header(default=None, alias="X-Workspace-ID"),
    ) -> dict[str, list[dict[str, object]]]:
        scoped_workspace = _require_workspace(workspace_id)
        conversations = [
            conversation
            for conversation in state_store.conversations.values()
            if conversation.workspace_id == scoped_workspace
        ]
        conversations.sort(key=lambda item: item.window_opened_at or 0, reverse=True)
        return {
            "items": [
                {
                    "conversation_id": conversation.id,
                    "customer_identity": conversation.customer_identity,
                    "status": conversation.status,
                    "window_status": conversation.window_status,
                    "message_count": sum(
                        message.conversation_id == conversation.id
                        for message in state_store.messages.values()
                    ),
                    "latest_message": _latest_message(state_store, conversation.id),
                }
                for conversation in conversations
            ]
        }

    @app.get("/inbox/{conversation_id}")
    def conversation_detail(
        conversation_id: str,
        workspace_id: str | None = Header(default=None, alias="X-Workspace-ID"),
    ) -> dict[str, object]:
        scoped_workspace = _require_workspace(workspace_id)
        conversation = state_store.conversations.get(conversation_id)
        if conversation is None or conversation.workspace_id != scoped_workspace:
            raise HTTPException(status_code=404, detail="conversation not found")
        messages = [
            {
                "message_id": message.id,
                "provider_message_id": message.provider_message_id,
                "body_text": message.body_text,
                "occurred_at": message.occurred_at.isoformat(),
            }
            for message in state_store.messages.values()
            if message.conversation_id == conversation.id
        ]
        messages.sort(key=lambda item: item["occurred_at"])
        return {
            "conversation_id": conversation.id,
            "customer_identity": conversation.customer_identity,
            "status": conversation.status,
            "version": conversation.version,
            "service_window": {
                "opened_at": _iso(conversation.window_opened_at),
                "expires_at": _iso(conversation.window_expires_at),
                "status": conversation.window_status,
            },
            "policy": {
                "opted_out": conversation.opted_out,
                "human_takeover": conversation.human_takeover,
            },
            "handoff": (
                {
                    "task_id": conversation.handoff_task_id,
                    "state": "open",
                    "reason": conversation.handoff_reason,
                }
                if conversation.handoff_task_id is not None
                else None
            ),
            "messages": messages,
        }

    @app.get("/inbox/{conversation_id}/policy")
    def outbound_policy(
        conversation_id: str,
        workspace_id: str | None = Header(default=None, alias="X-Workspace-ID"),
    ) -> dict[str, object]:
        _require_conversation_scope(state_store, conversation_id, workspace_id)
        decision = commerce_service.outbound_policy(conversation_id)
        return {
            "allowed": decision.allowed,
            "code": decision.code,
            "reason": decision.reason,
        }

    @app.post("/inbox/{conversation_id}/policy/opt-out")
    def opt_out(
        conversation_id: str,
        workspace_id: str | None = Header(default=None, alias="X-Workspace-ID"),
    ) -> dict[str, object]:
        _require_conversation_scope(state_store, conversation_id, workspace_id)
        state_store.opt_out(conversation_id)
        return {"conversation_id": conversation_id, "opted_out": True}

    @app.post("/inbox/{conversation_id}/policy/takeover")
    def take_over(
        conversation_id: str,
        body: dict | None = None,
        workspace_id: str | None = Header(default=None, alias="X-Workspace-ID"),
    ) -> dict[str, object]:
        _require_conversation_scope(state_store, conversation_id, workspace_id)
        reason = (body or {}).get("reason", "operator_requested")
        if not isinstance(reason, str) or not reason.strip():
            raise HTTPException(status_code=422, detail="reason must be text")
        conversation = state_store.take_over(conversation_id, reason=reason.strip())
        return {
            "conversation_id": conversation_id,
            "human_takeover": True,
            "handoff_task_id": conversation.handoff_task_id,
            "handoff_reason": conversation.handoff_reason,
        }

    @app.post("/inbox/{conversation_id}/policy/resume")
    def resume(
        conversation_id: str,
        workspace_id: str | None = Header(default=None, alias="X-Workspace-ID"),
    ) -> dict[str, object]:
        _require_conversation_scope(state_store, conversation_id, workspace_id)
        try:
            state_store.resume(conversation_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"conversation_id": conversation_id, "human_takeover": False}

    @app.post("/inbox/{conversation_id}/product-question")
    def product_question(
        conversation_id: str,
        body: dict,
        workspace_id: str | None = Header(default=None, alias="X-Workspace-ID"),
    ) -> dict[str, object]:
        _require_conversation_scope(state_store, conversation_id, workspace_id)
        question = body.get("text")
        if not isinstance(question, str) or not question.strip():
            raise HTTPException(status_code=422, detail="text is required")
        try:
            result = commerce_service.answer_product_question(conversation_id, question)
        except CommerceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "state": result.state,
            "product_id": result.product_id,
            "product_name": result.product_name,
            "availability": result.availability,
            "price_cents": result.price_cents,
            "currency": result.currency,
            "source": result.source,
            "message": result.message,
        }

    @app.post("/inbox/{conversation_id}/select")
    def select_product(
        conversation_id: str,
        body: dict,
        workspace_id: str | None = Header(default=None, alias="X-Workspace-ID"),
    ) -> dict[str, object]:
        _require_conversation_scope(state_store, conversation_id, workspace_id)
        product_id = body.get("product_id")
        quantity = body.get("quantity")
        if not isinstance(product_id, str) or not product_id.strip():
            raise HTTPException(status_code=422, detail="product_id is required")
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise HTTPException(status_code=422, detail="quantity must be an integer")
        try:
            workflow = commerce_service.select_product(
                conversation_id,
                product_id=product_id,
                quantity=quantity,
            )
        except CommerceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "workflow_id": workflow.workflow_id,
            "state": workflow.state,
            "product_id": workflow.product_id,
            "quantity": workflow.quantity,
            "version": workflow.version,
        }

    @app.post("/inbox/{conversation_id}/confirm")
    def confirm_purchase(
        conversation_id: str,
        workspace_id: str | None = Header(default=None, alias="X-Workspace-ID"),
    ) -> dict[str, object]:
        _require_conversation_scope(state_store, conversation_id, workspace_id)
        try:
            result = commerce_service.confirm_purchase(conversation_id)
        except CommerceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "state": result.state,
            "quantity": result.quantity,
            "payment_status": result.payment_status,
            "payment_link": result.payment_link,
            "conversion": result.conversion,
        }

    @app.post("/inbox/{conversation_id}/order-status")
    def order_status(
        conversation_id: str,
        body: dict,
        workspace_id: str | None = Header(default=None, alias="X-Workspace-ID"),
    ) -> dict[str, object]:
        _require_conversation_scope(state_store, conversation_id, workspace_id)
        reference = body.get("reference")
        if not isinstance(reference, str) or not reference.strip():
            raise HTTPException(status_code=422, detail="reference is required")
        try:
            result = commerce_service.lookup_order(conversation_id, reference)
        except CommerceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        payload: dict[str, object] = {
            "state": result.state,
            "message": result.message,
        }
        if result.state == "matched":
            payload.update(
                {
                    "status": result.status,
                    "order_id": result.order_id,
                    "tracking_id": result.tracking_id,
                    "source": result.source,
                }
            )
        return payload

    @app.post("/inbox/{conversation_id}/delivery-event")
    def delivery_event(
        conversation_id: str,
        body: dict,
        workspace_id: str | None = Header(default=None, alias="X-Workspace-ID"),
    ) -> dict[str, object]:
        _require_conversation_scope(state_store, conversation_id, workspace_id)
        event_id = body.get("event_id")
        order_id = body.get("order_id")
        event_status = body.get("status")
        timestamp = body.get("timestamp")
        if not all(isinstance(value, str) and value.strip() for value in (event_id, order_id, event_status, timestamp)):
            raise HTTPException(status_code=422, detail="event_id, order_id, status, and timestamp are required")
        try:
            occurred_at = _parse_timestamp(timestamp)
            result = commerce_service.record_delivery_event(
                conversation_id,
                event_id=event_id,
                order_id=order_id,
                status=event_status,  # type: ignore[arg-type]
                occurred_at=occurred_at,
            )
        except (CommerceError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "event_id": result.event_id,
            "order_id": result.order_id,
            "status": result.status,
            "duplicate": result.duplicate,
        }

    @app.post("/demo/reset")
    def reset_demo(
        workspace_id: str | None = Header(default=None, alias="X-Workspace-ID"),
    ) -> dict[str, object]:
        scoped_workspace = _require_workspace(workspace_id)
        event_keys = [
            key for key, event in state_store.events.items() if event.workspace_id == scoped_workspace
        ]
        conversation_ids = [
            key
            for key, conversation in state_store.conversations.items()
            if conversation.workspace_id == scoped_workspace
        ]
        for key in event_keys:
            del state_store.events[key]
        for key in conversation_ids:
            del state_store.conversations[key]
        for key, message in list(state_store.messages.items()):
            if message.conversation_id in conversation_ids:
                del state_store.messages[key]
        for key in list(commerce_store.workflows):
            if key in conversation_ids:
                del commerce_store.workflows[key]
        return {"reset": True, "workspace_id": scoped_workspace}

    return app


def _require_workspace(workspace_id: str | None) -> str:
    if not workspace_id or not workspace_id.strip():
        raise HTTPException(status_code=400, detail="X-Workspace-ID is required")
    return workspace_id.strip()


def _require_conversation_scope(
    store: InMemoryConversationStore,
    conversation_id: str,
    workspace_id: str | None,
) -> None:
    scoped_workspace = _require_workspace(workspace_id)
    conversation = store.conversations.get(conversation_id)
    if conversation is None or conversation.workspace_id != scoped_workspace:
        raise HTTPException(status_code=404, detail="conversation not found")


def _latest_message(store: InMemoryConversationStore, conversation_id: str) -> str | None:
    messages = [
        message
        for message in store.messages.values()
        if message.conversation_id == conversation_id
    ]
    if not messages:
        return None
    return max(messages, key=lambda message: message.occurred_at).body_text


def _iso(value):
    return value.isoformat() if value is not None else None


def _parse_timestamp(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


app = create_app()
