"""Fixture-backed product and payment-link workflow for the client demo."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Callable, Literal

from .inbound import InMemoryConversationStore
from .policy import OutboundPolicy, PolicyDecision
from .templates import TemplateRegistry, TemplateValidationError


class CommerceError(ValueError):
    """Raised when a commerce action cannot safely continue."""


@dataclass(frozen=True, slots=True)
class Product:
    product_id: str
    name: str
    description: str
    availability: str
    price_cents: int
    currency: str
    source: str


OrderState = Literal["in_transit", "out_for_delivery", "delivered"]
SUPPORTED_ORDER_STATES = {"in_transit", "out_for_delivery", "delivered"}


@dataclass(slots=True)
class Order:
    order_id: str
    product_id: str
    status: OrderState = "in_transit"
    tracking_id: str = "TRK-BLUE-001"
    source: str = "fixture-commerce"
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class OrderStatusResult:
    state: str
    message: str
    status: OrderState | None = None
    order_id: str | None = None
    tracking_id: str | None = None
    source: str | None = None


@dataclass(frozen=True, slots=True)
class DeliveryEventResult:
    event_id: str
    order_id: str
    status: OrderState
    duplicate: bool


@dataclass(frozen=True, slots=True)
class OutboundCommandResult:
    command_id: str
    conversation_id: str
    template_id: str
    locale: str
    variables: dict[str, object]
    workflow: str
    idempotency_key: str
    status: str
    policy_code: str | None = None
    policy_reason: str | None = None
    provider_result: str | None = None
    attempts: int = 0
    next_attempt_at: str | None = None
    last_error_code: str | None = None


@dataclass(slots=True)
class WorkflowRun:
    workflow_id: str
    conversation_id: str
    state: str = "new"
    product_id: str | None = None
    quantity: int | None = None
    payment_link: str | None = None
    payment_status: str = "not_started"
    conversion: bool = False
    version: int = 1


@dataclass(frozen=True, slots=True)
class ProductQuestionResult:
    state: str
    product_id: str
    product_name: str
    availability: str
    price_cents: int
    currency: str
    source: str
    message: str


@dataclass(frozen=True, slots=True)
class AnalyticsEvent:
    event_type: str
    conversation_id: str
    source: str
    workflow: str
    timestamp: datetime


@dataclass(frozen=True, slots=True)
class PaymentLinkResult:
    state: str
    quantity: int
    payment_status: str
    payment_link: str
    conversion: bool


@dataclass(slots=True)
class CommerceDemoStore:
    products: dict[str, Product] = field(default_factory=dict)
    workflows: dict[str, WorkflowRun] = field(default_factory=dict)
    orders: dict[str, Order] = field(default_factory=dict)
    delivery_events: dict[str, str] = field(default_factory=dict)
    outbound_commands: dict[str, OutboundCommandResult] = field(default_factory=dict)
    outbound_idempotency: dict[tuple[str, str], str] = field(default_factory=dict)
    delivery_event_conversations: dict[str, str] = field(default_factory=dict)
    analytics_events: list[AnalyticsEvent] = field(default_factory=list)
    analytics_idempotency: set[tuple[str, str]] = field(default_factory=set)

    def __post_init__(self) -> None:
        if not self.products:
            self.products["blue-product-001"] = Product(
                product_id="blue-product-001",
                name="Blue Product",
                description="The seeded blue product for the commerce walkthrough.",
                availability="available",
                price_cents=4900,
                currency="USD",
                source="fixture-catalog",
            )
        if not self.orders:
            self._seed_order()

    def reset(self) -> None:
        """Restore mutable commerce state without changing the static catalog."""
        self.workflows.clear()
        self.delivery_events.clear()
        self.outbound_commands.clear()
        self.outbound_idempotency.clear()
        self.delivery_event_conversations.clear()
        self.analytics_events.clear()
        self.analytics_idempotency.clear()
        self.orders.clear()
        self._seed_order()

    def reset_workspace(self, conversation_ids: set[str]) -> None:
        """Remove mutable state owned by the supplied conversations only."""
        self.workflows = {
            conversation_id: workflow
            for conversation_id, workflow in self.workflows.items()
            if conversation_id not in conversation_ids
        }
        removed_command_ids = {
            command_id
            for command_id, command in self.outbound_commands.items()
            if command.conversation_id in conversation_ids
        }
        for command_id in removed_command_ids:
            del self.outbound_commands[command_id]
        self.outbound_idempotency = {
            key: command_id
            for key, command_id in self.outbound_idempotency.items()
            if key[0] not in conversation_ids
        }
        removed_delivery_ids = {
            event_id
            for event_id, conversation_id in self.delivery_event_conversations.items()
            if conversation_id in conversation_ids
        }
        for event_id in removed_delivery_ids:
            self.delivery_events.pop(event_id, None)
            self.delivery_event_conversations.pop(event_id, None)
        self.analytics_events = [
            event
            for event in self.analytics_events
            if event.conversation_id not in conversation_ids
        ]
        self.analytics_idempotency = {
            key
            for key in self.analytics_idempotency
            if key[0] not in conversation_ids
        }

    def restore_seed_order(self) -> None:
        """Restore shared fixture order data without clearing other catalog rows."""
        self._seed_order()

    def _seed_order(self) -> None:
        self.orders["ORDER-BLUE-001"] = Order(
            order_id="ORDER-BLUE-001",
            product_id="blue-product-001",
            updated_at=datetime(2026, 8, 9, 10, tzinfo=timezone.utc),
        )

    def find_product(self, query: str) -> Product | None:
        normalized = query.casefold()
        if "blue" in normalized or "product" in normalized:
            return self.products["blue-product-001"]
        return None

    def find_order(self, reference: str) -> Order | None:
        normalized = reference.strip().casefold()
        for order in self.orders.values():
            if normalized in {order.order_id.casefold(), order.tracking_id.casefold()}:
                return order
        return None


class CommerceService:
    def __init__(
        self,
        inbound_store: InMemoryConversationStore,
        catalog: CommerceDemoStore,
        *,
        policy: OutboundPolicy | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.inbound_store = inbound_store
        self.catalog = catalog
        self.policy = policy or OutboundPolicy()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.templates = TemplateRegistry()

    def list_templates(self) -> list[dict[str, object]]:
        return self.templates.list()

    def record_analytics_event(
        self,
        conversation_id: str,
        *,
        event_type: str,
        workflow: str,
        source: str,
        dedupe_key: str,
    ) -> AnalyticsEvent | None:
        self._require_conversation(conversation_id)
        if source not in {"fixture", "unknown"}:
            raise CommerceError("analytics source must be fixture or unknown")
        key = (conversation_id, dedupe_key)
        if key in self.catalog.analytics_idempotency:
            return None
        event = AnalyticsEvent(
            event_type=event_type,
            conversation_id=conversation_id,
            source=source,
            workflow=workflow,
            timestamp=self.clock(),
        )
        self.catalog.analytics_idempotency.add(key)
        self.catalog.analytics_events.append(event)
        return event

    def analytics_for(self, conversation_id: str) -> list[AnalyticsEvent]:
        self._require_conversation(conversation_id)
        return [
            event
            for event in self.catalog.analytics_events
            if event.conversation_id == conversation_id
        ]

    def enqueue_template(
        self,
        conversation_id: str,
        *,
        template_id: str,
        locale: str,
        variables: dict[str, object],
        workflow: str,
        idempotency_key: str,
    ) -> OutboundCommandResult:
        self._require_conversation(conversation_id)
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise CommerceError("idempotency_key is required")
        try:
            self.templates.validate(template_id, locale, variables, workflow)
        except TemplateValidationError as exc:
            raise CommerceError(str(exc)) from exc

        key = (conversation_id, idempotency_key)
        existing_id = self.catalog.outbound_idempotency.get(key)
        if existing_id is not None:
            return self.catalog.outbound_commands[existing_id]
        decision = self.outbound_policy(conversation_id)
        command = OutboundCommandResult(
            command_id=f"outbound-{sha256(f'{conversation_id}:{idempotency_key}'.encode()).hexdigest()[:16]}",
            conversation_id=conversation_id,
            template_id=template_id,
            locale=locale,
            variables=dict(variables),
            workflow=workflow,
            idempotency_key=idempotency_key,
            status="queued" if decision.allowed else "blocked",
            policy_code=None if decision.allowed else decision.code,
            policy_reason=None if decision.allowed else decision.reason,
        )
        self.catalog.outbound_commands[command.command_id] = command
        self.catalog.outbound_idempotency[key] = command.command_id
        return command

    def submit_outbound(
        self, conversation_id: str, command_id: str
    ) -> OutboundCommandResult:
        self._require_conversation(conversation_id)
        command = self.catalog.outbound_commands.get(command_id)
        if command is None or command.conversation_id != conversation_id:
            raise CommerceError("outbound command not found")
        if command.status in {"sent", "blocked"}:
            return command
        decision = self.outbound_policy(conversation_id)
        if not decision.allowed:
            blocked = replace(
                command,
                status="blocked",
                policy_code=decision.code,
                policy_reason=decision.reason,
            )
            self.catalog.outbound_commands[command_id] = blocked
            return blocked
        sent = replace(
            command,
            status="sent",
            policy_code="allowed",
            policy_reason="outbound allowed at provider boundary",
            provider_result="fixture_only",
            attempts=command.attempts + 1,
        )
        self.catalog.outbound_commands[command_id] = sent
        return sent

    def fail_outbound(
        self, conversation_id: str, command_id: str, error_code: str
    ) -> OutboundCommandResult:
        self._require_conversation(conversation_id)
        command = self._outbound_command(conversation_id, command_id)
        if command.status in {"sent", "blocked", "dead_letter"}:
            return command
        if not isinstance(error_code, str) or not error_code.strip():
            raise CommerceError("error_code is required")
        attempts = command.attempts + 1
        transient = error_code in {"timeout", "rate_limit", "provider_unavailable"}
        if transient and attempts <= 3:
            backoff_seconds = (5, 30, 300)[attempts - 1]
            retryable = replace(
                command,
                status="retryable",
                attempts=attempts,
                next_attempt_at=(self.clock() + timedelta(seconds=backoff_seconds)).isoformat(),
                last_error_code=error_code,
                policy_code="provider_retryable",
                policy_reason="Transient provider failure can be retried with bounded backoff.",
            )
        else:
            retryable = replace(
                command,
                status="dead_letter",
                attempts=attempts,
                next_attempt_at=None,
                last_error_code=error_code,
                policy_code="dead_letter",
                policy_reason="Provider failure is not safe to retry unchanged.",
            )
        self.catalog.outbound_commands[command_id] = retryable
        self.record_analytics_event(
            conversation_id,
            event_type=(
                "outbound_retryable"
                if retryable.status == "retryable"
                else "outbound_dead_letter"
            ),
            workflow=command.workflow,
            source="fixture",
            dedupe_key=f"{command_id}:{retryable.attempts}",
        )
        return retryable

    def retry_outbound(self, conversation_id: str, command_id: str) -> OutboundCommandResult:
        self._require_conversation(conversation_id)
        command = self._outbound_command(conversation_id, command_id)
        if command.status != "retryable":
            return command
        decision = self.outbound_policy(conversation_id)
        if not decision.allowed:
            blocked = replace(
                command,
                status="blocked",
                policy_code=decision.code,
                policy_reason=decision.reason,
            )
            self.catalog.outbound_commands[command_id] = blocked
            return blocked
        queued = replace(
            command,
            status="queued",
            policy_code="allowed",
            policy_reason="Policy recheck passed before retry.",
        )
        self.catalog.outbound_commands[command_id] = queued
        return self.submit_outbound(conversation_id, command_id)

    def _outbound_command(self, conversation_id: str, command_id: str) -> OutboundCommandResult:
        command = self.catalog.outbound_commands.get(command_id)
        if command is None or command.conversation_id != conversation_id:
            raise CommerceError("outbound command not found")
        return command

    def outbound_policy(self, conversation_id: str) -> PolicyDecision:
        self._require_conversation(conversation_id)
        conversation = self.inbound_store.conversations[conversation_id]
        return self.policy.evaluate(conversation, now=self.clock())

    def lookup_order(self, conversation_id: str, reference: str) -> OrderStatusResult:
        self._require_conversation(conversation_id)
        if not reference.strip():
            raise CommerceError("order reference is required")
        order = self.catalog.find_order(reference)
        if order is None:
            return OrderStatusResult(
                state="no_match",
                message="No order matched that reference. Please check the reference and try again.",
            )
        return OrderStatusResult(
            state="matched",
            message=f"Order {order.order_id} is {order.status}.",
            status=order.status,
            order_id=order.order_id,
            tracking_id=order.tracking_id,
            source=order.source,
        )

    def record_delivery_event(
        self,
        conversation_id: str,
        *,
        event_id: str,
        order_id: str,
        status: OrderState,
        occurred_at: datetime,
    ) -> DeliveryEventResult:
        self._require_conversation(conversation_id)
        order = self.catalog.orders.get(order_id)
        if order is None:
            raise CommerceError("order not found")
        if status not in SUPPORTED_ORDER_STATES:
            raise CommerceError("unsupported delivery status")
        if event_id in self.catalog.delivery_events:
            return DeliveryEventResult(
                event_id=event_id,
                order_id=order_id,
                status=order.status,
                duplicate=True,
            )
        self.catalog.delivery_events[event_id] = order_id
        self.catalog.delivery_event_conversations[event_id] = conversation_id
        order.status = status
        order.updated_at = occurred_at
        self.record_analytics_event(
            conversation_id,
            event_type="delivery_update",
            workflow="order_status",
            source="fixture",
            dedupe_key=f"delivery:{event_id}",
        )
        return DeliveryEventResult(
            event_id=event_id,
            order_id=order_id,
            status=order.status,
            duplicate=False,
        )

    def answer_product_question(
        self,
        conversation_id: str,
        question: str,
    ) -> ProductQuestionResult:
        self._require_conversation(conversation_id)
        decision = self.outbound_policy(conversation_id)
        if not decision.allowed:
            raise CommerceError(decision.reason)
        product = self.catalog.find_product(question)
        if product is None:
            raise CommerceError("no approved catalog match")

        workflow = self._workflow(conversation_id)
        workflow.product_id = product.product_id
        workflow.state = "awaiting_confirmation"
        workflow.version += 1
        result = ProductQuestionResult(
            state=workflow.state,
            product_id=product.product_id,
            product_name=product.name,
            availability=product.availability,
            price_cents=product.price_cents,
            currency=product.currency,
            source=product.source,
            message=(
                f"{product.name} is {product.availability}. "
                f"Price: {product.currency} {product.price_cents / 100:.2f}. "
                "Reply with a quantity to continue."
            ),
        )
        self.record_analytics_event(
            conversation_id,
            event_type="product_answered",
            workflow="commerce",
            source="fixture",
            dedupe_key="product_answered",
        )
        return result

    def select_product(
        self,
        conversation_id: str,
        *,
        product_id: str,
        quantity: int,
    ) -> WorkflowRun:
        workflow = self._workflow(conversation_id)
        if workflow.state != "awaiting_confirmation":
            raise CommerceError("workflow is not awaiting product confirmation")
        if product_id not in self.catalog.products:
            raise CommerceError("product is not in the approved catalog")
        if quantity < 1 or quantity > 20:
            raise CommerceError("quantity must be between 1 and 20")
        workflow.product_id = product_id
        workflow.quantity = quantity
        workflow.version += 1
        return workflow

    def confirm_purchase(self, conversation_id: str) -> PaymentLinkResult:
        workflow = self._workflow(conversation_id)
        if workflow.product_id is None or workflow.quantity is None:
            raise CommerceError("product and quantity must be confirmed first")
        if workflow.payment_link is None:
            token = sha256(
                f"{conversation_id}:{workflow.product_id}:{workflow.quantity}".encode()
            ).hexdigest()[:16]
            workflow.payment_link = f"https://checkout.example.test/{token}"
            workflow.payment_status = "link_created"
            workflow.state = "awaiting_external_event"
            workflow.version += 1
            self.record_analytics_event(
                conversation_id,
                event_type="checkout_link_created",
                workflow="commerce",
                source="fixture",
                dedupe_key="checkout_link_created",
            )
        return PaymentLinkResult(
            state=workflow.state,
            quantity=workflow.quantity,
            payment_status=workflow.payment_status,
            payment_link=workflow.payment_link,
            conversion=workflow.conversion,
        )

    def _workflow(self, conversation_id: str) -> WorkflowRun:
        self._require_conversation(conversation_id)
        workflow = self.catalog.workflows.get(conversation_id)
        if workflow is None:
            workflow = WorkflowRun(
                workflow_id=f"workflow-{conversation_id}",
                conversation_id=conversation_id,
            )
            self.catalog.workflows[conversation_id] = workflow
        return workflow

    def _require_conversation(self, conversation_id: str) -> None:
        if conversation_id not in self.inbound_store.conversations:
            raise CommerceError("conversation not found")
