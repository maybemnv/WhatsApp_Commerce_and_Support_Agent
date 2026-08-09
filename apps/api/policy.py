"""Deterministic outbound policy gates for the WhatsApp demo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .inbound import Conversation


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    code: str
    reason: str


class OutboundPolicy:
    """Evaluate final-send policy without claiming a live provider boundary."""

    def evaluate(self, conversation: Conversation, *, now: datetime) -> PolicyDecision:
        if conversation.opted_out:
            return PolicyDecision(
                allowed=False,
                code="opted_out",
                reason="outbound blocked: opt-out is active",
            )
        if conversation.human_takeover:
            return PolicyDecision(
                allowed=False,
                code="human_takeover",
                reason="outbound blocked: human takeover is active",
            )
        if (
            conversation.window_expires_at is None
            or now >= conversation.window_expires_at
            or conversation.window_status != "active"
        ):
            return PolicyDecision(
                allowed=False,
                code="service_window_closed",
                reason="outbound blocked: service window is closed",
            )
        return PolicyDecision(allowed=True, code="allowed", reason="outbound allowed")
