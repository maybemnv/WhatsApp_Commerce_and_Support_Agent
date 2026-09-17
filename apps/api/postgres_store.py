"""PostgreSQL-backed persistence for the existing WhatsApp domain stores."""

from __future__ import annotations

import pickle
from collections.abc import Callable

from .commerce import CommerceDemoStore
from .inbound import InMemoryConversationStore


class _SnapshotStore:
    _store_name = ""

    def _connect(self):
        import psycopg

        return psycopg.connect(self.database_url)

    def _load_snapshot(self) -> bool:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT payload FROM whatsapp_runtime_snapshots WHERE store_name = %s",
                (self._store_name,),
            )
            row = cursor.fetchone()
        if row is None:
            return False
        state = pickle.loads(bytes(row[0]))  # noqa: S301 - trusted database boundary
        for name, value in state.items():
            setattr(self, name, value)
        return True

    def _persist_snapshot(self) -> None:
        names = (
            ("products", "workflows", "orders", "delivery_events", "outbound_commands",
             "outbound_idempotency", "delivery_event_conversations", "analytics_events",
             "analytics_idempotency")
            if self._store_name == "commerce"
            else ("events", "conversations", "messages", "handoffs", "audit_events")
        )
        state = {name: getattr(self, name) for name in names}
        payload = pickle.dumps(state, protocol=pickle.HIGHEST_PROTOCOL)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"whatsapp:{self._store_name}",),
            )
            cursor.execute(
                "INSERT INTO whatsapp_runtime_snapshots (store_name, payload, updated_at) "
                "VALUES (%s, %s, now()) ON CONFLICT (store_name) DO UPDATE SET "
                "payload = EXCLUDED.payload, updated_at = EXCLUDED.updated_at",
                (self._store_name, payload),
            )


class PostgresConversationStore(_SnapshotStore, InMemoryConversationStore):
    """Persist inbound events, conversations, handoffs and audit state."""

    _store_name = "conversation"
    _MUTATIONS = frozenset({
        "reset", "reset_workspace", "accept", "opt_out", "take_over",
        "claim_handoff", "reply_to_handoff", "resolve_handoff", "reconsent", "resume",
    })

    def __init__(self, database_url: str) -> None:
        InMemoryConversationStore.__init__(self)
        self.database_url = database_url
        self._load_snapshot()

    def __getattribute__(self, name: str):
        value = super().__getattribute__(name)
        if name in PostgresConversationStore._MUTATIONS and callable(value):
            return lambda *args, **kwargs: self._mutate(value, *args, **kwargs)
        return value

    def _mutate(self, method: Callable, *args, **kwargs):
        with self._lock:
            result = method(*args, **kwargs)
            self._persist_snapshot()
            return result


class PostgresCommerceStore(_SnapshotStore, CommerceDemoStore):
    """Persist commerce workflow, outbound and analytics state."""

    _store_name = "commerce"

    def __init__(self, database_url: str) -> None:
        CommerceDemoStore.__init__(self)
        self.database_url = database_url
        self.persist_callback = self._persist_snapshot
        self.products.clear()
        self.orders.clear()
        self._load_snapshot()

    def persist(self) -> None:
        self._persist_snapshot()
