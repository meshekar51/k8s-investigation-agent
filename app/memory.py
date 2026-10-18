"""Memory management (transcript step 6).

Two kinds of memory, like a human on-call engineer:
  - Short-term / session memory = "what we said in this incident channel".
    LangGraph checkpointer keyed by session_id (thread_id). Follow-up questions work.
  - Long-term memory = "the incident log book".
    Every finished investigation is written to a store; the agent reads it back
    with the recall_past_incidents tool to spot repeat offenders.

Local dev / tests -> both in RAM (gone when the process stops).
kind / Kubernetes -> both in PostgreSQL (StatefulSet sre-agent-db in the agent's namespace).
"""

from __future__ import annotations

import logging
import time
import uuid

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from app.config import Settings

log = logging.getLogger(__name__)
_POOLS: dict[str, object] = {}


def _pool(uri: str, wait_seconds: int = 120):
    """One shared connection pool per database, opened with retries.

    In Kubernetes the agent can start before Postgres is ready; waiting here (instead of
    crash-looping) keeps the rollout clean.
    """
    if uri in _POOLS:
        return _POOLS[uri]
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    pool = ConnectionPool(
        conninfo=uri,
        min_size=1,
        max_size=10,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            pool.open(wait=True, timeout=10)
            break
        except Exception as exc:  # noqa: BLE001 - retry any connection failure
            if time.monotonic() > deadline:
                raise RuntimeError(f"PostgreSQL not reachable after {wait_seconds}s: {exc}") from exc
            log.warning("waiting for PostgreSQL: %s", exc)
            time.sleep(3)
    _POOLS[uri] = pool
    return pool


def build_checkpointer(settings: Settings):
    if settings.postgres_uri:
        from langgraph.checkpoint.postgres import PostgresSaver

        saver = PostgresSaver(_pool(settings.postgres_uri))
        saver.setup()  # creates/migrates its tables, idempotent
        return saver
    return InMemorySaver()


def build_store(settings: Settings):
    if settings.postgres_uri:
        from langgraph.store.postgres import PostgresStore

        store = PostgresStore(_pool(settings.postgres_uri))
        store.setup()
        return store
    return InMemoryStore()


class IncidentMemory:
    """Thin wrapper so the rest of the code never depends on the store's API."""

    def __init__(self, store, max_items: int = 5):
        self.store = store
        self.max_items = max_items

    def remember(self, namespace: str, record: dict) -> None:
        record = {**record, "ts": int(time.time())}
        self.store.put(("incidents", namespace or "cluster"), uuid.uuid4().hex, record)

    def recall(self, namespace: str) -> list[dict]:
        items = self.store.search(("incidents", namespace or "cluster"), limit=50)
        values = sorted((i.value for i in items), key=lambda v: v.get("ts", 0), reverse=True)
        return values[: self.max_items]
