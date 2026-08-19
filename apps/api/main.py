"""FastAPI entry point for the fixture-backed WhatsApp demo."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from fastapi import FastAPI, Header, HTTPException, status
from fastapi.responses import FileResponse
from pathlib import Path

from .commerce import CommerceDemoStore, CommerceError, CommerceService
from .inbound import InMemoryConversationStore, InboundValidationError, InboundWebhookService
from .policy import OutboundPolicy


DEFAULT_DEMO_NOW = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
DEMO_NOW_ENV = "WHATSAPP_DEMO_NOW"


def create_app(store: InMemoryConversationStore | None = None) -> FastAPI:
    state_store = store or InMemoryConversationStore()
    webhook_service = InboundWebhookService(state_store)
    commerce_store = CommerceDemoStore()
    app = FastAPI(title="WhatsApp Commerce and Support Agent", version="0.1.0")
    app.state.store = state_store
    app.state.commerce_store = commerce_store
    app.state.demo_now = _configured_demo_now()
    app.state.clock = lambda: app.state.demo_now
    commerce_service = CommerceService(
        state_store,
        commerce_store,
        policy=OutboundPolicy(),
        clock=lambda: app.state.clock(),
    )
    app.state.commerce_service = commerce_service
    demo_page = Path(__file__).resolve().parents[1] / "web" / "index.html"

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": "fixture"}

    @app.get("/ready")
    def ready() -> dict[str, str]:
        catalog_ready = "blue-product-001" in commerce_store.products
        order_ready = "ORDER-BLUE-001" in commerce_store.orders
        fixture_ready = catalog_ready and order_ready
        return {
            "status": "ready" if fixture_ready else "not_ready",
            "mode": "fixture",
            "catalog": "ready" if catalog_ready else "missing",
            "seed_order": "ready" if order_ready else "missing",
        }

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
        if not result.duplicate:
            commerce_service.record_analytics_event(
                result.conversation_id,
                event_type="inbound_accepted",
                workflow="commerce",
                source="fixture",
                dedupe_key=f"inbound:{result.event_id}",
            )
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

    @app.get("/inbox/{conversation_id}/analytics")
    def conversation_analytics(
        conversation_id: str,
        workspace_id: str | None = Header(default=None, alias="X-Workspace-ID"),
    ) -> dict[str, object]:
        _require_conversation_scope(state_store, conversation_id, workspace_id)
        events = commerce_service.analytics_for(conversation_id)
        outcomes: dict[str, int] = {}
        for event in events:
            outcomes[event.event_type] = outcomes.get(event.event_type, 0) + 1
        sources = {event.source for event in events}
        return {
            "conversation_id": conversation_id,
            "source": next(iter(sources)) if len(sources) == 1 else "unknown",
            "workflow": events[-1].workflow if events else "commerce",
            "events": [
                {
                    "event_type": event.event_type,
                    "conversation_id": event.conversation_id,
                    "source": event.source,
                    "workflow": event.workflow,
                    "timestamp": event.timestamp.isoformat(),
                }
                for event in events
            ],
            "summary": {"total": len(events), "outcomes": outcomes},
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
        commerce_service.record_analytics_event(
            conversation_id,
            event_type="opt_out",
            workflow="governance",
            source="fixture",
            dedupe_key="opt_out",
        )
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
        commerce_service.record_analytics_event(
            conversation_id,
            event_type="human_takeover",
            workflow="support",
            source="fixture",
            dedupe_key="human_takeover",
        )
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

    @app.get("/inbox/{conversation_id}/templates")
    def templates(
        conversation_id: str,
        workspace_id: str | None = Header(default=None, alias="X-Workspace-ID"),
    ) -> dict[str, object]:
        _require_conversation_scope(state_store, conversation_id, workspace_id)
        return {"items": commerce_service.list_templates()}

    @app.post("/inbox/{conversation_id}/outbound/templates")
    def enqueue_template(
        conversation_id: str,
        body: dict,
        workspace_id: str | None = Header(default=None, alias="X-Workspace-ID"),
    ) -> dict[str, object]:
        _require_conversation_scope(state_store, conversation_id, workspace_id)
        template_id = body.get("template_id")
        locale = body.get("locale")
        variables = body.get("variables")
        workflow = body.get("workflow")
        idempotency_key = body.get("idempotency_key")
        if not all(isinstance(value, str) and value.strip() for value in (template_id, locale, workflow, idempotency_key)):
            raise HTTPException(status_code=422, detail="template_id, locale, workflow, and idempotency_key are required")
        if not isinstance(variables, dict):
            raise HTTPException(status_code=422, detail="variables must be an object")
        try:
            command = commerce_service.enqueue_template(
                conversation_id,
                template_id=template_id,
                locale=locale,
                variables=variables,
                workflow=workflow,
                idempotency_key=idempotency_key,
            )
        except CommerceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _outbound_payload(command)

    @app.post("/inbox/{conversation_id}/outbound/{command_id}/submit")
    def submit_outbound(
        conversation_id: str,
        command_id: str,
        workspace_id: str | None = Header(default=None, alias="X-Workspace-ID"),
    ) -> dict[str, object]:
        _require_conversation_scope(state_store, conversation_id, workspace_id)
        try:
            command = commerce_service.submit_outbound(conversation_id, command_id)
        except CommerceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _outbound_payload(command)

    @app.post("/inbox/{conversation_id}/outbound/{command_id}/fail")
    def fail_outbound(
        conversation_id: str,
        command_id: str,
        body: dict,
        workspace_id: str | None = Header(default=None, alias="X-Workspace-ID"),
    ) -> dict[str, object]:
        _require_conversation_scope(state_store, conversation_id, workspace_id)
        error_code = body.get("error_code")
        if not isinstance(error_code, str) or not error_code.strip():
            raise HTTPException(status_code=422, detail="error_code is required")
        try:
            command = commerce_service.fail_outbound(conversation_id, command_id, error_code)
        except CommerceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _outbound_payload(command)

    @app.post("/inbox/{conversation_id}/outbound/{command_id}/retry")
    def retry_outbound(
        conversation_id: str,
        command_id: str,
        workspace_id: str | None = Header(default=None, alias="X-Workspace-ID"),
    ) -> dict[str, object]:
        _require_conversation_scope(state_store, conversation_id, workspace_id)
        try:
            command = commerce_service.retry_outbound(conversation_id, command_id)
        except CommerceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _outbound_payload(command)

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
        state_store.reset()
        commerce_store.reset()
        app.state.demo_now = _configured_demo_now()
        return {
            "reset": True,
            "workspace_id": scoped_workspace,
            "mode": "fixture",
            "fixture_clock": app.state.demo_now.isoformat(),
            "catalog": "ready",
            "seed_order": "ready",
        }

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


def _outbound_payload(command: object) -> dict[str, object]:
    return {
        "command_id": command.command_id,
        "conversation_id": command.conversation_id,
        "template_id": command.template_id,
        "locale": command.locale,
        "variables": command.variables,
        "workflow": command.workflow,
        "idempotency_key": command.idempotency_key,
        "status": command.status,
        "policy_code": command.policy_code,
        "policy_reason": command.policy_reason,
        "provider_result": command.provider_result,
        "attempts": command.attempts,
        "next_attempt_at": command.next_attempt_at,
        "last_error_code": command.last_error_code,
    }


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


def _configured_demo_now() -> datetime:
    value = os.getenv(DEMO_NOW_ENV)
    if value is None or not value.strip():
        return DEFAULT_DEMO_NOW
    return _parse_timestamp(value.strip())


app = create_app()
