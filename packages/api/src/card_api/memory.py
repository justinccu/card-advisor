"""Deleting a user's Advisor memory along with their account (ADR 0005, 0009).

AgentCore Memory keeps two kinds of data per user (the actor id is the Cognito `sub`):
- long-term records (preferences, conversation summaries), kept until deleted. These must be gone
  before the account is: if any can't be deleted, `purge` raises, the API answers 503, and the
  site keeps the account so the user can retry. Otherwise the records would outlive every way to
  find them.
- raw conversation events, which expire on their own 7 days after they're written. They're
  deleted too, in parallel, within a time budget that fits the API's 10-second Lambda. Any left
  when it runs out expire by themselves.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger(__name__)

EVENT_BUDGET_SECONDS = 5.0
DELETE_WORKERS = 8
BATCH = 100  # BatchDeleteMemoryRecords' limit


class MemoryPurgeError(Exception):
    pass


def namespaces(actor_id: str) -> list[str]:
    # Prefixes of the namespaces in agentcore.json; the trailing slash keeps user "ab" from
    # matching user "abc".
    return [f"/users/{actor_id}/", f"/summaries/{actor_id}/"]


def _delete_records(client, memory_id: str, actor_id: str) -> int:
    deleted = 0
    for prefix in namespaces(actor_id):
        pages = client.get_paginator("list_memory_records").paginate(
            memoryId=memory_id, namespace=prefix
        )
        ids = [r["memoryRecordId"] for page in pages for r in page["memoryRecordSummaries"]]
        for i in range(0, len(ids), BATCH):
            resp = client.batch_delete_memory_records(
                memoryId=memory_id, records=[{"memoryRecordId": x} for x in ids[i : i + BATCH]]
            )
            if resp.get("failedRecords"):
                raise MemoryPurgeError(f"{len(resp['failedRecords'])} memory records not deleted")
        deleted += len(ids)
    return deleted


def _delete_events(client, memory_id: str, actor_id: str, deadline: float) -> tuple[int, bool]:
    """(events deleted, whether some were left to expire)."""
    events = []
    for page in client.get_paginator("list_sessions").paginate(
        memoryId=memory_id, actorId=actor_id
    ):
        for session in page["sessionSummaries"]:
            for epage in client.get_paginator("list_events").paginate(
                memoryId=memory_id,
                actorId=actor_id,
                sessionId=session["sessionId"],
                includePayloads=False,
            ):
                events += [(session["sessionId"], e["eventId"]) for e in epage["events"]]
            if time.monotonic() > deadline:
                return 0, True

    def delete(item: tuple[str, str]) -> bool:
        if time.monotonic() > deadline:
            return False
        session_id, event_id = item
        client.delete_event(
            memoryId=memory_id, actorId=actor_id, sessionId=session_id, eventId=event_id
        )
        return True

    with ThreadPoolExecutor(DELETE_WORKERS) as pool:
        done = list(pool.map(delete, events))
    return sum(done), not all(done)


def purge(client, memory_id: str, actor_id: str, *, budget: float = EVENT_BUDGET_SECONDS) -> dict:
    records = _delete_records(client, memory_id, actor_id)
    try:
        events, left = _delete_events(client, memory_id, actor_id, time.monotonic() + budget)
    except Exception:  # best effort: they expire within 7 days anyway
        log.exception("deleting memory events failed; they will expire")
        events, left = 0, True
    return {"records": records, "events": events, "events_left_to_expire": left}
