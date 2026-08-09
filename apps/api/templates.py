"""Approved outbound template contracts for the fixture demo."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


class TemplateValidationError(ValueError):
    """Raised when a local template contract is not safe to submit."""


@dataclass(frozen=True, slots=True)
class TemplateDefinition:
    id: str
    locale: str
    variables: tuple[str, ...]
    workflow: str
    local_approved: bool = True
    provider_approved: bool = True

    def as_mapping(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "locale": self.locale,
            "variables": list(self.variables),
            "workflow": self.workflow,
            "localApproval": self.local_approved,
            "providerApproval": self.provider_approved,
        }


TEMPLATE_DEFINITIONS: tuple[TemplateDefinition, ...] = (
    TemplateDefinition(
        "order_status_update",
        "en-US",
        ("order_id", "status", "tracking_id"),
        "order_status",
    ),
    TemplateDefinition(
        "appointment_reminder",
        "en-US",
        ("appointment_at", "time_zone"),
        "appointment_reminder",
    ),
    TemplateDefinition(
        "payment_link_follow_up",
        "en-US",
        ("payment_link",),
        "payment_follow_up",
    ),
    TemplateDefinition(
        "human_handoff_ack",
        "en-US",
        ("task_id",),
        "human_handoff",
    ),
    TemplateDefinition(
        "service_window_reopen",
        "en-US",
        ("opt_in_source",),
        "service_window_reopen",
    ),
)


class TemplateRegistry:
    def __init__(self, definitions: tuple[TemplateDefinition, ...] = TEMPLATE_DEFINITIONS):
        self._definitions = {definition.id: definition for definition in definitions}

    def list(self) -> list[dict[str, Any]]:
        return [definition.as_mapping() for definition in self._definitions.values()]

    def validate(
        self,
        template_id: str,
        locale: str,
        variables: Mapping[str, Any],
        workflow: str,
    ) -> TemplateDefinition:
        definition = self._definitions.get(template_id)
        if definition is None:
            raise TemplateValidationError("template is not registered")
        if locale != definition.locale:
            raise TemplateValidationError("template locale is not approved")
        if workflow != definition.workflow:
            raise TemplateValidationError("template workflow is not authorized")
        if not definition.local_approved or not definition.provider_approved:
            raise TemplateValidationError("template is not approved by both local and provider policy")
        if set(variables) != set(definition.variables):
            raise TemplateValidationError(
                "variables must contain exactly: " + ", ".join(definition.variables)
            )
        if any(value is None or (isinstance(value, str) and not value.strip()) for value in variables.values()):
            raise TemplateValidationError("template variables must be non-empty")
        return definition
