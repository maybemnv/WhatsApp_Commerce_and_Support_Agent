from datetime import datetime, timedelta, timezone

from apps.api.inbound import Conversation
from apps.api.policy import OutboundPolicy


def _conversation(**overrides):
    values = {
        "id": "conv-policy",
        "workspace_id": "workspace-demo",
        "customer_identity": "+15551234567",
        "window_opened_at": datetime(2026, 8, 9, 10, tzinfo=timezone.utc),
        "window_expires_at": datetime(2026, 8, 10, 10, tzinfo=timezone.utc),
        "window_status": "active",
    }
    values.update(overrides)
    return Conversation(**values)


def test_active_window_allows_outbound_freeform_reply():
    decision = OutboundPolicy().evaluate(
        _conversation(),
        now=datetime(2026, 8, 9, 12, tzinfo=timezone.utc),
    )

    assert decision.allowed is True
    assert decision.code == "allowed"


def test_expired_window_blocks_outbound_freeform_reply():
    decision = OutboundPolicy().evaluate(
        _conversation(),
        now=datetime(2026, 8, 10, 10, tzinfo=timezone.utc) + timedelta(seconds=1),
    )

    assert decision.allowed is False
    assert decision.code == "service_window_closed"


def test_opt_out_and_human_takeover_override_an_active_window():
    policy = OutboundPolicy()
    now = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)

    opted_out = policy.evaluate(_conversation(opted_out=True), now=now)
    takeover = policy.evaluate(_conversation(human_takeover=True), now=now)

    assert opted_out.code == "opted_out"
    assert takeover.code == "human_takeover"
