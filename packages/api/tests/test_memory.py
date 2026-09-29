"""Deleting a user's Advisor memory with their account (card_api.memory)."""

import pytest
from card_api import memory


class FakeMemory:
    """AgentCore Memory with two users' records and events, paginated like the real API."""

    def __init__(self, fail_records=False, slow=0.0):
        self.records = {
            "r1": "/users/u1/preferences",
            "r2": "/summaries/u1/s1",
            "r3": "/users/u10/preferences",  # another user whose id starts with "u1"
        }
        self.events = {("u1", "s1"): ["e1", "e2"], ("u1", "s2"): ["e3"], ("u2", "s9"): ["e9"]}
        self.fail_records = fail_records
        self.slow = slow
        self.deleted_events = []

    def get_paginator(self, name):
        fake = self

        class Pages:
            def paginate(self, **kw):
                if name == "list_memory_records":
                    ids = [i for i, ns in fake.records.items() if ns.startswith(kw["namespace"])]
                    # two pages, like a nextToken
                    yield {"memoryRecordSummaries": [{"memoryRecordId": i} for i in ids[:1]]}
                    yield {"memoryRecordSummaries": [{"memoryRecordId": i} for i in ids[1:]]}
                elif name == "list_sessions":
                    sessions = {s for (a, s) in fake.events if a == kw["actorId"]}
                    yield {"sessionSummaries": [{"sessionId": s} for s in sorted(sessions)]}
                elif name == "list_events":
                    ids = fake.events.get((kw["actorId"], kw["sessionId"]), [])
                    yield {"events": [{"eventId": e} for e in ids]}

        return Pages()

    def batch_delete_memory_records(self, memoryId, records):
        if self.fail_records:
            return {"successfulRecords": [], "failedRecords": [{"memoryRecordId": "r1"}]}
        for r in records:
            self.records.pop(r["memoryRecordId"])
        return {"successfulRecords": records, "failedRecords": []}

    def delete_event(self, memoryId, actorId, sessionId, eventId):
        import time

        time.sleep(self.slow)
        self.deleted_events.append((actorId, eventId))


def test_only_this_users_records_and_events_are_deleted():
    fake = FakeMemory()
    result = memory.purge(fake, "mem", "u1")
    assert result == {"records": 2, "events": 3, "events_left_to_expire": False}
    assert fake.records == {"r3": "/users/u10/preferences"}  # "u10" is not "u1"
    assert sorted(fake.deleted_events) == [("u1", "e1"), ("u1", "e2"), ("u1", "e3")]


def test_a_record_that_wont_delete_stops_the_account_deletion():
    with pytest.raises(memory.MemoryPurgeError):
        memory.purge(FakeMemory(fail_records=True), "mem", "u1")


def test_events_past_the_time_budget_are_left_to_expire():
    fake = FakeMemory(slow=0.05)
    result = memory.purge(fake, "mem", "u1", budget=0.0)
    assert result["records"] == 2 and result["events_left_to_expire"] is True
