"""Fixture-backed product and payment-link workflow for the client demo."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
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
        order.status = status
        order.updated_at = occurred_at
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
        return ProductQuestionResult(
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
