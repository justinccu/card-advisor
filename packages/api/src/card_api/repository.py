"""Storage behind one interface: in-memory for local demos and tests, DynamoDB on AWS (ADR 0003).

DynamoDB single-table layout (every access is by key, no scans):

    PK              SK                          item
    USER#<uid>      PROFILE                     Applicant Profile
    USER#<uid>      ATTEST                      Wallet Attestation
    USER#<uid>      CARD#<opened_on>#<id>       Held Card (sorted by open date -> 5/24 range query)
    USER#<uid>      QUOTA#<yyyy-mm-dd>          daily chat counter, expires via TTL
    USER#<uid>      QUOTA#TRIAL                 a guest's trial messages, expires via TTL
    INVITE          CODE#<code>                 remaining uses (conditional decrement)
    INVITE          CODE#<code>#USE#<user>      who took a use, and when they confirmed
    GUEST           IP#<hash>                   guests started from one network today (TTL)
    GUEST           DAY#<yyyy-mm-dd>            all guests' messages that day (TTL)
    ADVISOR         SPEND                       running Advisor cost in USD (atomic add)

All invites share one partition so an admin lists them with a query, not a scan; at invite-beta
volume (hundreds of items) one partition is nowhere near its throughput limit.
"""

import threading
import time
import uuid
from decimal import Decimal
from typing import Protocol

from card_api.models import (
    ApplicantProfile,
    ChatTurn,
    HeldCard,
    HeldCardIn,
    Invite,
    InviteUse,
    TurnFeedback,
    WalletAttestation,
)

QUOTA_TTL_SECONDS = 3 * 24 * 3600
# Advisor answers (ADR 0009): 7 days like Memory's raw events; 90 once the user rates one.
TURN_TTL_SECONDS = 7 * 24 * 3600
RATED_TURN_TTL_SECONDS = 90 * 24 * 3600
INVITE_PK = "INVITE"
GUEST_PK = "GUEST"
SPEND_KEY = {"PK": "ADVISOR", "SK": "SPEND"}


class Repository(Protocol):
    def get_profile(self, uid: str) -> ApplicantProfile: ...
    def put_profile(self, uid: str, profile: ApplicantProfile) -> None: ...
    def list_cards(self, uid: str) -> list[HeldCard]: ...
    def add_card(self, uid: str, card: HeldCardIn) -> HeldCard: ...
    def update_card(self, uid: str, card_id: str, card: HeldCardIn) -> HeldCard | None: ...
    def delete_card(self, uid: str, card_id: str) -> bool: ...
    def get_attestation(self, uid: str) -> WalletAttestation: ...
    def put_attestation(self, uid: str, attestation: WalletAttestation) -> None: ...
    def create_invite(self, code: str, uses: int) -> None: ...
    def redeem_invite(self, code: str, user: str) -> bool: ...
    def confirm_invite_use(self, user: str) -> bool: ...
    def list_invites(self) -> list[Invite]: ...
    def take_quota(
        self, uid: str, period: str, limit: int, ttl_seconds: int = QUOTA_TTL_SECONDS
    ) -> int | None: ...
    def quota_used(self, uid: str, period: str) -> int: ...
    def take_guest_start(self, network: str, limit: int, ttl_seconds: int) -> bool: ...
    def take_guest_message(self, day: str, limit: int, ttl_seconds: int) -> bool: ...
    def guest_messages(self, day: str) -> int: ...
    def add_spend(self, usd: float) -> float: ...
    def spend(self) -> float: ...
    def put_turn(self, uid: str, turn: ChatTurn) -> None: ...
    def rate_turn(self, uid: str, turn_id: str, feedback: TurnFeedback, rated_at: str) -> bool: ...
    def rated_turns(self) -> list[tuple[str, ChatTurn]]: ...
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
        self._uses: dict[str, dict[str, InviteUse]] = {}
        self._quota: dict[tuple[str, str], int] = {}
        self._guest_starts: dict[str, int] = {}
        self._guest_messages: dict[str, int] = {}
        self._spend = 0.0
        self._turns: dict[str, dict[str, ChatTurn]] = {}

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

    def update_card(self, uid, card_id, card):
        with self._lock:
            cards = self._cards.get(uid, {})
            if card_id not in cards:
                return None
            cards[card_id] = HeldCard(id=card_id, **card.model_dump())
            return cards[card_id]

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

    def redeem_invite(self, code, user):
        with self._lock:
            if user in self._uses.get(code, {}):
                return True  # the same sign-up retried: it already holds a use
            if self._invites.get(code, 0) <= 0:
                return False
            self._invites[code] -= 1
            self._uses.setdefault(code, {})[user] = InviteUse(user=user, taken_at=int(time.time()))
            return True

    def confirm_invite_use(self, user):
        with self._lock:
            for uses in self._uses.values():
                use = uses.get(user)
                if use and use.confirmed_at is None:
                    use.confirmed_at = int(time.time())
                    return True
            return False

    def list_invites(self):
        with self._lock:
            return [
                Invite(code=code, remaining=left, uses=list(self._uses.get(code, {}).values()))
                for code, left in sorted(self._invites.items())
            ]

    def take_quota(self, uid, period, limit, ttl_seconds=QUOTA_TTL_SECONDS):
        """Atomically take one unit of a period's quota (a day, or a guest's trial); the new
        count, or None at the limit."""
        with self._lock:
            used = self._quota.get((uid, period), 0)
            if used >= limit:
                return None
            self._quota[(uid, period)] = used + 1
            return used + 1

    def quota_used(self, uid, period):
        return self._quota.get((uid, period), 0)

    def take_guest_start(self, network, limit, ttl_seconds):
        with self._lock:
            started = self._guest_starts.get(network, 0)
            if started >= limit:
                return False
            self._guest_starts[network] = started + 1
            return True

    def take_guest_message(self, day, limit, ttl_seconds):
        with self._lock:
            sent = self._guest_messages.get(day, 0)
            if sent >= limit:
                return False
            self._guest_messages[day] = sent + 1
            return True

    def guest_messages(self, day):
        return self._guest_messages.get(day, 0)

    def add_spend(self, usd):
        with self._lock:
            self._spend += usd
            return self._spend

    def spend(self):
        return self._spend

    def put_turn(self, uid, turn):
        with self._lock:
            self._turns.setdefault(uid, {})[turn.turn_id] = turn

    def rate_turn(self, uid, turn_id, feedback, rated_at):
        with self._lock:
            turn = self._turns.get(uid, {}).get(turn_id)
            if turn is None:
                return False
            self._turns[uid][turn_id] = turn.model_copy(
                update={"feedback": feedback, "rated_at": rated_at}
            )
            return True

    def rated_turns(self):
        return [
            (uid, t) for uid, turns in self._turns.items() for t in turns.values() if t.feedback
        ]

    def delete_user(self, uid):
        with self._lock:
            self._turns.pop(uid, None)
            self._profiles.pop(uid, None)
            self._cards.pop(uid, None)
            self._attest.pop(uid, None)
            for key in [k for k in self._quota if k[0] == uid]:
                del self._quota[key]
            for uses in self._uses.values():
                uses.pop(uid, None)


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

    def _card_item(self, uid: str, held: HeldCard) -> dict:
        return {
            "PK": self._user(uid),
            "SK": f"CARD#{held.opened_on.isoformat()}#{held.id}",
            "card_id": held.id,
            "data": held.model_dump(mode="json"),
        }

    def add_card(self, uid, card):
        held = HeldCard(id=new_id(), **card.model_dump())
        self._table.put_item(Item=self._card_item(uid, held))
        return held

    def update_card(self, uid, card_id, card):
        match = [c for c in self.list_cards(uid) if c.id == card_id]
        if not match:
            return None
        held = HeldCard(id=card_id, **card.model_dump())
        item = self._card_item(uid, held)
        old_sk = f"CARD#{match[0].opened_on.isoformat()}#{card_id}"
        if item["SK"] == old_sk:
            self._table.put_item(Item=item)
            return held
        # A new open date moves the item (the sort key embeds it): delete + put, atomically.
        name = self._table.name
        self._table.meta.client.transact_write_items(
            TransactItems=[
                {"Delete": {"TableName": name, "Key": {"PK": item["PK"], "SK": old_sk}}},
                {"Put": {"TableName": name, "Item": item}},
            ]
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
            Item={"PK": INVITE_PK, "SK": f"CODE#{code}", "remaining": uses},
            ConditionExpression="attribute_not_exists(PK)",
        )

    def redeem_invite(self, code, user):
        """Take one use and record who took it, atomically: both writes happen or neither does,
        so remaining + recorded uses always equals the uses the code was created with."""
        from botocore.exceptions import ClientError

        name = self._table.name
        try:
            # The resource's client serializes plain Python values, like the Table API does.
            self._table.meta.client.transact_write_items(
                TransactItems=[
                    {
                        "Update": {
                            "TableName": name,
                            "Key": {"PK": INVITE_PK, "SK": f"CODE#{code}"},
                            "UpdateExpression": "SET remaining = remaining - :one",
                            "ConditionExpression": "attribute_exists(PK) AND remaining > :zero",
                            "ExpressionAttributeValues": {":one": 1, ":zero": 0},
                        }
                    },
                    {
                        "Put": {
                            "TableName": name,
                            "Item": {
                                "PK": INVITE_PK,
                                "SK": f"CODE#{code}#USE#{user}",
                                "user": user,
                                "taken_at": int(time.time()),
                            },
                            "ConditionExpression": "attribute_not_exists(PK)",
                        }
                    },
                ]
            )
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] != "TransactionCanceledException":
                raise
            reasons = [r.get("Code") for r in e.response.get("CancellationReasons", [])]
            # The use record already exists: the same sign-up retried and already holds a use.
            return (
                len(reasons) == 2
                and reasons[1] == "ConditionalCheckFailed"
                and (reasons[0] in (None, "None"))
            )

    def _invite_items(self, **filters):
        from boto3.dynamodb.conditions import Key

        kwargs = {"KeyConditionExpression": Key("PK").eq(INVITE_PK), **filters}
        while True:
            page = self._table.query(**kwargs)
            yield from page["Items"]
            if "LastEvaluatedKey" not in page:
                return
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    def _uses_of(self, user: str, *, unconfirmed: bool = False):
        from boto3.dynamodb.conditions import Attr

        cond = Attr("user").eq(user)
        if unconfirmed:
            cond &= Attr("confirmed_at").not_exists()
        return self._invite_items(FilterExpression=cond)

    def confirm_invite_use(self, user):
        from botocore.exceptions import ClientError

        for item in self._uses_of(user, unconfirmed=True):
            try:
                self._table.update_item(
                    Key={"PK": INVITE_PK, "SK": item["SK"]},
                    UpdateExpression="SET confirmed_at = :now",
                    ConditionExpression="attribute_exists(PK)",
                    ExpressionAttributeValues={":now": int(time.time())},
                )
                return True
            except ClientError as e:
                if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                    raise
        return False

    def list_invites(self):
        invites: dict[str, Invite] = {}
        uses: list[tuple[str, InviteUse]] = []
        for item in self._invite_items():
            code, _, rest = item["SK"].removeprefix("CODE#").partition("#USE#")
            if rest:
                uses.append(
                    (
                        code,
                        InviteUse(
                            user=item["user"],
                            taken_at=int(item["taken_at"]),
                            confirmed_at=int(item["confirmed_at"])
                            if "confirmed_at" in item
                            else None,
                        ),
                    )
                )
            else:
                invites[code] = Invite(code=code, remaining=int(item["remaining"]))
        for code, use in uses:
            if code in invites:
                invites[code].uses.append(use)
        return sorted(invites.values(), key=lambda i: i.code)

    def _take(self, key: dict, limit: int, ttl_seconds: int) -> int | None:
        """One unit of a counter, atomically: the new count, or None at the limit. The first
        unit sets the expiry."""
        from botocore.exceptions import ClientError

        try:
            resp = self._table.update_item(
                Key=key,
                UpdateExpression="ADD used :one SET expires_at = if_not_exists(expires_at, :exp)",
                ConditionExpression="attribute_not_exists(used) OR used < :limit",
                ExpressionAttributeValues={
                    ":one": 1,
                    ":limit": limit,
                    ":exp": int(time.time()) + ttl_seconds,
                },
                ReturnValues="UPDATED_NEW",
            )
            return int(resp["Attributes"]["used"])
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return None
            raise

    def take_quota(self, uid, period, limit, ttl_seconds=QUOTA_TTL_SECONDS):
        return self._take({"PK": self._user(uid), "SK": f"QUOTA#{period}"}, limit, ttl_seconds)

    def quota_used(self, uid, period):
        item = self._table.get_item(Key={"PK": self._user(uid), "SK": f"QUOTA#{period}"}).get(
            "Item"
        )
        return int(item["used"]) if item else 0

    def take_guest_start(self, network, limit, ttl_seconds):
        return self._take({"PK": GUEST_PK, "SK": f"IP#{network}"}, limit, ttl_seconds) is not None

    def take_guest_message(self, day, limit, ttl_seconds):
        return self._take({"PK": GUEST_PK, "SK": f"DAY#{day}"}, limit, ttl_seconds) is not None

    def guest_messages(self, day):
        item = self._table.get_item(Key={"PK": GUEST_PK, "SK": f"DAY#{day}"}).get("Item")
        return int(item["used"]) if item else 0

    def add_spend(self, usd):
        resp = self._table.update_item(
            Key=SPEND_KEY,
            UpdateExpression="ADD total_usd :usd",
            ExpressionAttributeValues={":usd": Decimal(str(round(usd, 6)))},
            ReturnValues="UPDATED_NEW",
        )
        return float(resp["Attributes"]["total_usd"])

    def spend(self):
        item = self._table.get_item(Key=SPEND_KEY).get("Item")
        return float(item["total_usd"]) if item else 0.0

    def put_turn(self, uid, turn):
        self._table.put_item(
            Item={
                "PK": self._user(uid),
                "SK": f"TURN#{turn.turn_id}",
                "data": turn.model_dump(mode="json", exclude={"feedback", "rated_at"}),
                "expires_at": int(time.time()) + TURN_TTL_SECONDS,
            }
        )

    def rate_turn(self, uid, turn_id, feedback, rated_at):
        from botocore.exceptions import ClientError

        try:
            self._table.update_item(
                Key={"PK": self._user(uid), "SK": f"TURN#{turn_id}"},
                UpdateExpression="SET feedback = :f, rated_at = :t, expires_at = :exp",
                ConditionExpression="attribute_exists(PK)",
                ExpressionAttributeValues={
                    ":f": feedback.model_dump(mode="json"),
                    ":t": rated_at,
                    ":exp": int(time.time()) + RATED_TURN_TTL_SECONDS,
                },
            )
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def rated_turns(self):
        """Every rated answer, for the owner's review (scripts/feedback.py). A scan: fine at an
        invite-only beta's size, and it keeps the table free of a second copy to delete."""
        from boto3.dynamodb.conditions import Attr

        kwargs = {"FilterExpression": Attr("SK").begins_with("TURN#") & Attr("feedback").exists()}
        out = []
        while True:
            page = self._table.scan(**kwargs)
            for item in page["Items"]:
                turn = ChatTurn.model_validate(
                    {**item["data"], "feedback": item["feedback"], "rated_at": item["rated_at"]}
                )
                out.append((item["PK"].removeprefix("USER#"), turn))
            if "LastEvaluatedKey" not in page:
                return out
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

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
            # ADR 0005: their invite-use records name them too. The use stays consumed.
            for item in list(self._uses_of(uid)):
                batch.delete_item(Key={"PK": INVITE_PK, "SK": item["SK"]})
