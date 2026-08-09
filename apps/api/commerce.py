"""Fixture-backed product and payment-link workflow for the client demo."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Callable

from .inbound import InMemoryConversationStore
from .policy import OutboundPolicy, PolicyDecision


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

    def find_product(self, query: str) -> Product | None:
        normalized = query.casefold()
        if "blue" in normalized or "product" in normalized:
            return self.products["blue-product-001"]
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

    def outbound_policy(self, conversation_id: str) -> PolicyDecision:
        self._require_conversation(conversation_id)
        conversation = self.inbound_store.conversations[conversation_id]
        return self.policy.evaluate(conversation, now=self.clock())

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
