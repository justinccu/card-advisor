"""Storage behind one interface: in-memory for local demos and tests, DynamoDB on AWS (ADR 0003).

DynamoDB single-table layout (every access is by key, no scans):

    PK              SK                          item
    USER#<uid>      PROFILE                     Applicant Profile
    USER#<uid>      ATTEST                      Wallet Attestation
    USER#<uid>      CARD#<opened_on>#<id>       Held Card (sorted by open date -> 5/24 range query)
    USER#<uid>      QUOTA#<yyyy-mm-dd>          daily chat counter, expires via TTL
    INVITE#<code>   META                        remaining uses (conditional decrement)
"""

import threading
import time
import uuid
from datetime import date
from typing import Protocol

from card_api.models import ApplicantProfile, HeldCard, HeldCardIn, WalletAttestation

QUOTA_TTL_SECONDS = 3 * 24 * 3600


class Repository(Protocol):
    def get_profile(self, uid: str) -> ApplicantProfile: ...
    def put_profile(self, uid: str, profile: ApplicantProfile) -> None: ...
    def list_cards(self, uid: str) -> list[HeldCard]: ...
    def add_card(self, uid: str, card: HeldCardIn) -> HeldCard: ...
    def delete_card(self, uid: str, card_id: str) -> bool: ...
    def get_attestation(self, uid: str) -> WalletAttestation: ...
    def put_attestation(self, uid: str, attestation: WalletAttestation) -> None: ...
    def create_invite(self, code: str, uses: int) -> None: ...
    def redeem_invite(self, code: str) -> bool: ...
    def take_quota(self, uid: str, day: date, limit: int) -> bool: ...
    def delete_user(self, uid: str) -> None: ...


def new_id() -> str:
    return uuid.uuid4().hex[:12]


class InMemoryRepository:
    """Process-local store for demos and tests. Same semantics as DynamoDB, including atomic
    invite redemption and quota checks (guarded by a lock)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._profiles: dict[str, ApplicantProfile] = {}
        self._cards: dict[str, dict[str, HeldCard]] = {}
        self._attest: dict[str, WalletAttestation] = {}
        self._invites: dict[str, int] = {}
        self._quota: dict[tuple[str, date], int] = {}

    def get_profile(self, uid):
        return self._profiles.get(uid, ApplicantProfile())

    def put_profile(self, uid, profile):
        self._profiles[uid] = profile

    def list_cards(self, uid):
        return sorted(self._cards.get(uid, {}).values(), key=lambda c: (c.opened_on, c.id))

    def add_card(self, uid, card):
        held = HeldCard(id=new_id(), **card.model_dump())
        with self._lock:
            self._cards.setdefault(uid, {})[held.id] = held
        return held

    def delete_card(self, uid, card_id):
        with self._lock:
            return self._cards.get(uid, {}).pop(card_id, None) is not None

    def get_attestation(self, uid):
        return self._attest.get(uid, WalletAttestation())

    def put_attestation(self, uid, attestation):
        self._attest[uid] = attestation

    def create_invite(self, code, uses):
        with self._lock:
            self._invites[code] = uses

    def redeem_invite(self, code):
        with self._lock:
            if self._invites.get(code, 0) <= 0:
                return False
            self._invites[code] -= 1
            return True

    def take_quota(self, uid, day, limit):
        with self._lock:
            used = self._quota.get((uid, day), 0)
            if used >= limit:
                return False
            self._quota[(uid, day)] = used + 1
            return True

    def delete_user(self, uid):
        with self._lock:
            self._profiles.pop(uid, None)
            self._cards.pop(uid, None)
            self._attest.pop(uid, None)
            for key in [k for k in self._quota if k[0] == uid]:
                del self._quota[key]


class DynamoRepository:
    def __init__(self, table_name: str, *, resource=None) -> None:
        import boto3

        self._table = (resource or boto3.resource("dynamodb")).Table(table_name)

    @staticmethod
    def _user(uid: str) -> str:
        return f"USER#{uid}"

    def get_profile(self, uid):
        item = self._table.get_item(Key={"PK": self._user(uid), "SK": "PROFILE"}).get("Item")
        return ApplicantProfile.model_validate(item["data"]) if item else ApplicantProfile()

    def put_profile(self, uid, profile):
        self._table.put_item(
            Item={"PK": self._user(uid), "SK": "PROFILE", "data": profile.model_dump(mode="json")}
        )

    def list_cards(self, uid):
        from boto3.dynamodb.conditions import Key

        items, kwargs = (
            [],
            {
                "KeyConditionExpression": Key("PK").eq(self._user(uid))
                & Key("SK").begins_with("CARD#")
            },
        )
        while True:
            page = self._table.query(**kwargs)
            items += page["Items"]
            if "LastEvaluatedKey" not in page:
                break
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        return [HeldCard.model_validate(i["data"]) for i in items]

    def add_card(self, uid, card):
        held = HeldCard(id=new_id(), **card.model_dump())
        self._table.put_item(
            Item={
                "PK": self._user(uid),
                "SK": f"CARD#{held.opened_on.isoformat()}#{held.id}",
                "card_id": held.id,
                "data": held.model_dump(mode="json"),
            }
        )
        return held

    def delete_card(self, uid, card_id):
        # The sort key embeds the open date, so find it within this user's partition first.
        # Scoping the lookup to the caller's partition is what stops cross-user deletes.
        match = [c for c in self.list_cards(uid) if c.id == card_id]
        if not match:
            return False
        sk = f"CARD#{match[0].opened_on.isoformat()}#{card_id}"
        self._table.delete_item(Key={"PK": self._user(uid), "SK": sk})
        return True

    def get_attestation(self, uid):
        item = self._table.get_item(Key={"PK": self._user(uid), "SK": "ATTEST"}).get("Item")
        return WalletAttestation.model_validate(item["data"]) if item else WalletAttestation()

    def put_attestation(self, uid, attestation):
        self._table.put_item(
            Item={
                "PK": self._user(uid),
                "SK": "ATTEST",
                "data": attestation.model_dump(mode="json"),
            }
        )

    def create_invite(self, code, uses):
        self._table.put_item(
            Item={"PK": f"INVITE#{code}", "SK": "META", "remaining": uses},
            ConditionExpression="attribute_not_exists(PK)",
        )

    def redeem_invite(self, code):
        from botocore.exceptions import ClientError

        try:
            self._table.update_item(
                Key={"PK": f"INVITE#{code}", "SK": "META"},
                UpdateExpression="SET remaining = remaining - :one",
                ConditionExpression="attribute_exists(PK) AND remaining > :zero",
                ExpressionAttributeValues={":one": 1, ":zero": 0},
            )
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def take_quota(self, uid, day, limit):
        from botocore.exceptions import ClientError

        try:
            self._table.update_item(
                Key={"PK": self._user(uid), "SK": f"QUOTA#{day.isoformat()}"},
                UpdateExpression="ADD used :one SET expires_at = if_not_exists(expires_at, :exp)",
                ConditionExpression="attribute_not_exists(used) OR used < :limit",
                ExpressionAttributeValues={
                    ":one": 1,
                    ":limit": limit,
                    ":exp": int(time.time()) + QUOTA_TTL_SECONDS,
                },
            )
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def delete_user(self, uid):
        from boto3.dynamodb.conditions import Key

        kwargs = {"KeyConditionExpression": Key("PK").eq(self._user(uid))}
        with self._table.batch_writer() as batch:
            while True:
                page = self._table.query(**kwargs)
                for item in page["Items"]:
                    batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})
                if "LastEvaluatedKey" not in page:
                    break
                kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
