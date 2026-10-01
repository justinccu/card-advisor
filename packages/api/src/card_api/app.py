import hashlib
import logging
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from typing import Annotated
from zoneinfo import ZoneInfo

from card_rules import load_rules
from card_rules.catalog import VERSION_PATTERN, CatalogSnapshot
from card_rules.dates import add_months
from card_rules.explain import explain
from card_rules.ranking import RankOptions, rank
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from card_api import guests, invites, memory, service
from card_api.auth import Caller, current_caller, require_admin, require_member
from card_api.catalog import UnknownCatalogVersion, catalog_index, load_catalog
from card_api.models import (
    ApplicantProfile,
    ChatQuota,
    ChatTurn,
    ChatTurnIn,
    ChatUsage,
    GuestStart,
    HeldCard,
    HeldCardIn,
    HeldCardPatch,
    Invite,
    InviteBatchIn,
    SignupIn,
    TurnFeedback,
    Velocity,
    Wallet,
    WalletAttestation,
)
from card_api.repository import DynamoRepository, InMemoryRepository, Repository, new_id
from card_api.settings import settings

MAX_WALLET_CARDS = 100
CHAT_DAILY_LIMIT = 30  # ADR 0009
CHAT_TIMEZONE = ZoneInfo("America/New_York")  # the quota resets at midnight US Eastern
# Temporary guest trial (ADR 0009): visitors who aren't signed in get 10 messages in all, a few
# guest starts per network a day, and none once the Advisor has cost settings.guest_budget_usd.
GUEST_MESSAGE_LIMIT = 10
GUEST_TRIAL = "TRIAL"
GUEST_TTL_SECONDS = 30 * 24 * 3600  # the guest's refresh token lasts 30 days
GUEST_STARTS_PER_NETWORK = 3
GUESTS_CLOSED = "The free trial is paused. Sign in to keep using the Advisor."
GUESTS_FULL = "Today's free trial messages are all taken. Sign in, or try again tomorrow."
DEMO_INVITE = "DEMO-2026"  # local demo only: seeded into the in-memory store, never into DynamoDB
DEMO_USER = "demo-user"


@lru_cache(maxsize=1)
def get_repo() -> Repository:
    if settings.table_name:
        return DynamoRepository(settings.table_name)
    repo = InMemoryRepository()
    if settings.env == "local":
        seed_demo(repo)
    return repo


def seed_demo(repo: Repository) -> None:
    """A demo invite plus a user with a realistic Wallet, so eligibility has something to show."""
    repo.create_invite(invites.normalize(DEMO_INVITE), 100)
    today = date.today()
    for product, months_ago in [
        ("chase_freedom_unlimited", 30),
        ("amex_blue_cash_everyday", 20),
        ("c1_venture_x", 11),
        ("citi_double_cash", 7),
        ("discover_it_cash_back", 3),
    ]:
        repo.add_card(
            DEMO_USER, HeldCardIn(card_product_id=product, opened_on=add_months(today, -months_ago))
        )
    repo.put_profile(DEMO_USER, ApplicantProfile(tax_id="SSN", score_band="740_799"))
    repo.put_attestation(
        DEMO_USER,
        WalletAttestation(complete_since=add_months(today, -24), includes_all_open_cards=True),
    )


log = logging.getLogger(__name__)

app = FastAPI(title="card-advisor API", version="0.1.0")

CATALOG_VERSION_HEADER = "X-Catalog-Version"
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Dev-User"],
    expose_headers=[CATALOG_VERSION_HEADER],
)


def resolve_catalog(
    response: Response,
    catalog_version: Annotated[str | None, Query(pattern=VERSION_PATTERN)] = None,
) -> CatalogSnapshot:
    """The snapshot this request uses: the pinned `catalog_version` (the site pins the one it was
    built from) or the latest. Every response names it, so results can be reproduced."""
    try:
        snapshot = load_catalog(catalog_version)
    except UnknownCatalogVersion:
        raise HTTPException(404, f"no catalog version {catalog_version}") from None
    response.headers[CATALOG_VERSION_HEADER] = snapshot.version
    return snapshot


CallerDep = Annotated[Caller, Depends(current_caller)]
RepoDep = Annotated[Repository, Depends(get_repo)]
CatalogDep = Annotated[CatalogSnapshot, Depends(resolve_catalog)]


@app.get("/health")
def health() -> dict:
    snapshot = load_catalog()
    return {"ok": True, "catalog_version": snapshot.version, "preview": snapshot.preview}


@app.get("/catalog")
def catalog(response: Response, snapshot: CatalogDep, catalog_version: str | None = None):
    # A pinned version never changes; "latest" may move once the pointer does.
    response.headers["Cache-Control"] = (
        "public, max-age=31536000, immutable" if catalog_version else "public, max-age=60"
    )
    return snapshot


# --- Profile ----------------------------------------------------------------------------


@app.get("/me/profile")
def get_profile(caller: CallerDep, repo: RepoDep) -> ApplicantProfile:
    return repo.get_profile(caller.uid)


@app.put("/me/profile")
def put_profile(body: ApplicantProfile, caller: CallerDep, repo: RepoDep) -> ApplicantProfile:
    require_member(caller)
    repo.put_profile(caller.uid, body)
    return body


@lru_cache
def memory_client():
    import boto3

    return boto3.client("bedrock-agentcore")


@app.delete("/me", status_code=204)
def delete_me(caller: CallerDep, repo: RepoDep) -> None:
    # ADR 0005: account deletion purges everything we store about the user, the Advisor's
    # memory first: if that fails, nothing is deleted yet and the user can simply retry.
    if settings.advisor_memory_id:
        try:
            purged = memory.purge(memory_client(), settings.advisor_memory_id, caller.uid)
        except Exception as e:
            log.exception("advisor memory purge failed")
            raise HTTPException(
                503, "Couldn't delete your Advisor history. Nothing was deleted; try again."
            ) from e
        log.info("advisor memory purged: %s", purged)
    repo.delete_user(caller.uid)


# --- Wallet -----------------------------------------------------------------------------


@app.get("/me/wallet")
def get_wallet(caller: CallerDep, repo: RepoDep) -> Wallet:
    return Wallet(cards=repo.list_cards(caller.uid), attestation=repo.get_attestation(caller.uid))


@app.post("/me/wallet/cards", status_code=201)
def add_card(body: HeldCardIn, caller: CallerDep, repo: RepoDep, snapshot: CatalogDep) -> HeldCard:
    require_member(caller)
    if body.card_product_id and body.card_product_id not in catalog_index(snapshot):
        raise HTTPException(422, f"unknown card_product_id {body.card_product_id!r}")
    if len(repo.list_cards(caller.uid)) >= MAX_WALLET_CARDS:
        raise HTTPException(409, f"a Wallet holds at most {MAX_WALLET_CARDS} cards")
    return repo.add_card(caller.uid, body)


@app.patch("/me/wallet/cards/{card_id}")
def update_card(card_id: str, body: HeldCardPatch, caller: CallerDep, repo: RepoDep) -> HeldCard:
    require_member(caller)
    current = next((c for c in repo.list_cards(caller.uid) if c.id == card_id), None)
    if current is None:
        raise HTTPException(404, "no such card in your Wallet")
    try:  # the same checks as adding a card (not in the future, closed after opened)
        card = HeldCardIn.model_validate(
            {**current.model_dump(exclude={"id"}), **body.model_dump(exclude_unset=True)}
        )
    except ValidationError as e:
        raise RequestValidationError(e.errors(include_url=False, include_context=False)) from e
    updated = repo.update_card(caller.uid, card_id, card)
    if updated is None:
        raise HTTPException(404, "no such card in your Wallet")
    return updated


@app.delete("/me/wallet/cards/{card_id}", status_code=204)
def delete_card(card_id: str, caller: CallerDep, repo: RepoDep) -> None:
    require_member(caller)
    if not repo.delete_card(caller.uid, card_id):
        raise HTTPException(404, "no such card in your Wallet")


@app.put("/me/wallet/attestation")
def put_attestation(body: WalletAttestation, caller: CallerDep, repo: RepoDep) -> WalletAttestation:
    require_member(caller)
    repo.put_attestation(caller.uid, body)
    return body


# --- Eligibility ------------------------------------------------------------------------


def _as_of(as_of: date | None) -> date:
    today = date.today()
    if as_of and not (today - timedelta(days=3650) <= as_of <= today + timedelta(days=3650)):
        raise HTTPException(422, "as_of out of range")
    return as_of or today


@app.get("/me/velocity")
def get_velocity(
    caller: CallerDep,
    repo: RepoDep,
    snapshot: CatalogDep,
    as_of: Annotated[date | None, Query()] = None,
) -> Velocity:
    wallet = service.to_rules_wallet(
        repo.list_cards(caller.uid), repo.get_attestation(caller.uid), catalog_index(snapshot)
    )
    return service.velocity(wallet, _as_of(as_of))


@app.get("/me/eligibility")
def get_eligibility(
    caller: CallerDep,
    repo: RepoDep,
    snapshot: CatalogDep,
    card_id: Annotated[list[str] | None, Query(max_length=60)] = None,
    as_of: Annotated[date | None, Query()] = None,
) -> dict:
    """Eligibility Verdicts for the given cards (default: every card open to applicants), with
    the catalog version they were computed from."""
    index = catalog_index(snapshot)
    if card_id:
        unknown = [c for c in card_id if c not in index]
        if unknown:
            raise HTTPException(422, f"unknown card ids: {unknown}")
        products = [index[c] for c in card_id]
    else:
        products = [c for c in index.values() if c.availability == "open"]
    wallet = service.to_rules_wallet(
        repo.list_cards(caller.uid), repo.get_attestation(caller.uid), index
    )
    evaluations = service.evaluate_cards(
        products, repo.get_profile(caller.uid), wallet, _as_of(as_of)
    )
    return {"catalog_version": snapshot.version, "evaluations": evaluations}


# --- Recommendations (ADR 0009) --------------------------------------------------------


@app.post("/me/recommendations")
def recommendations(
    caller: CallerDep,
    repo: RepoDep,
    snapshot: CatalogDep,
    options: RankOptions | None = None,
    as_of: Annotated[date | None, Query()] = None,
) -> dict:
    """Open cards ranked by First-year or Ongoing Value for the caller's Spending Profile.
    `options` carries what the user confirmed in conversation (conditional rates, credits)."""
    if not snapshot.valuations:
        raise HTTPException(
            409, f"catalog v{snapshot.version} has no ranking data; publish a newer snapshot"
        )
    profile = repo.get_profile(caller.uid)
    scenario = options.scenario if options else None
    # The saved profile is the long-term record; a conversation what-if applies on top, for this
    # ranking only (never stored).
    spending = scenario.apply(profile.spending) if scenario else profile.spending
    base = {
        "catalog_version": snapshot.version,
        "scenario": scenario is not None,
        "spending_used": spending.model_dump(mode="json") if spending else None,
    }
    if spending is None or not any(spending.monthly_usd.values()):
        return base | {"needs": ["spending"], "sort_by": None, "cards": [], "excluded": []}
    index = catalog_index(snapshot)
    wallet = service.to_rules_wallet(
        repo.list_cards(caller.uid), repo.get_attestation(caller.uid), index
    )
    products = [c for c in snapshot.cards if c.availability == "open"]
    verdicts = service.evaluations(products, profile, wallet, _as_of(as_of))
    ranking = rank(products, snapshot.valuations, spending, verdicts, options)
    return base | {"needs": []} | ranking.model_dump(mode="json")


# --- Advisor chat quota (ADR 0009) -----------------------------------------------------


def _now() -> datetime:
    return datetime.now(CHAT_TIMEZONE)


def _chat_day() -> tuple[date, str]:
    now = _now().astimezone(CHAT_TIMEZONE)
    resets = datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=CHAT_TIMEZONE)
    return now.date(), resets.isoformat()


def _quota(used: int, resets_at: str | None, *, guest: bool = False) -> ChatQuota:
    limit = GUEST_MESSAGE_LIMIT if guest else CHAT_DAILY_LIMIT
    return ChatQuota(
        limit=limit, used=used, remaining=max(0, limit - used), resets_at=resets_at, guest=guest
    )


def _guests_open(repo: Repository) -> bool:
    return repo.spend() < settings.guest_budget_usd


@app.get("/me/chat/quota")
def chat_quota(caller: CallerDep, repo: RepoDep) -> ChatQuota:
    if caller.is_guest:
        return _quota(repo.quota_used(caller.uid, GUEST_TRIAL), None, guest=True)
    day, resets_at = _chat_day()
    return _quota(repo.quota_used(caller.uid, day.isoformat()), resets_at)


@app.post("/me/chat/turn")
def chat_turn(caller: CallerDep, repo: RepoDep) -> ChatQuota:
    """Takes one Advisor message from the quota (atomic), before any model is called: today's
    for members, the trial's for guests while the trial is open."""
    if caller.is_guest:
        if not _guests_open(repo):
            raise HTTPException(503, {"message": GUESTS_CLOSED, "code": "guests_closed"})
        used_up = {
            "message": f"You've used the {GUEST_MESSAGE_LIMIT} free messages. "
            "Sign in to keep using the Advisor.",
            **_quota(GUEST_MESSAGE_LIMIT, None, guest=True).model_dump(),
        }
        # A guest with messages left takes one of today's shared guest messages, then their own.
        if repo.quota_used(caller.uid, GUEST_TRIAL) >= GUEST_MESSAGE_LIMIT:
            raise HTTPException(429, used_up)
        day, _ = _chat_day()
        if not repo.take_guest_message(day.isoformat(), settings.guest_daily_limit, 3 * 86400):
            raise HTTPException(429, {"message": GUESTS_FULL, "code": "guests_full", "guest": True})
        used = repo.take_quota(caller.uid, GUEST_TRIAL, GUEST_MESSAGE_LIMIT, GUEST_TTL_SECONDS)
        if used is None:
            raise HTTPException(429, used_up)
        return _quota(used, None, guest=True)
    day, resets_at = _chat_day()
    used = repo.take_quota(caller.uid, day.isoformat(), CHAT_DAILY_LIMIT)
    if used is None:
        raise HTTPException(
            429,
            {
                "message": f"You've used today's {CHAT_DAILY_LIMIT} Advisor messages.",
                **_quota(CHAT_DAILY_LIMIT, resets_at).model_dump(),
            },
        )
    return _quota(used, resets_at)


@app.post("/me/chat/usage", status_code=204)
def chat_usage(body: ChatUsage, caller: CallerDep, repo: RepoDep) -> None:
    """The agent reports what each message cost (any caller's); the total closes the guest
    trial at settings.guest_budget_usd. Amounts are capped per message and never negative, so
    a caller can't lower the total."""
    total = repo.add_spend(body.cost_usd)
    if total >= settings.guest_budget_usd > total - body.cost_usd:
        log.warning("advisor spend reached $%.2f: guest trial closed", total)


def _client_network(request: Request) -> str:
    """The caller's IP (API Gateway's view; the client's own on a laptop), hashed with today's
    date: enough to count guest starts per network per day, kept a day, never stored raw."""
    event = request.scope.get("aws.event") or {}
    ip = event.get("requestContext", {}).get("http", {}).get("sourceIp") or (
        request.client.host if request.client else "unknown"
    )
    day = _now().date().isoformat()
    return hashlib.sha256(f"{day}|{ip}".encode()).hexdigest()[:32]


@lru_cache
def cognito_client():
    import boto3

    return boto3.client("cognito-idp")


@app.post("/guest", status_code=201)
def start_guest(request: Request, repo: RepoDep) -> GuestStart:
    """A guest identity for the Advisor trial (public: no sign-in). Temporary (ADR 0009)."""
    if not _guests_open(repo):
        raise HTTPException(503, {"message": GUESTS_CLOSED, "code": "guests_closed"})
    if repo.guest_messages(_chat_day()[0].isoformat()) >= settings.guest_daily_limit:
        raise HTTPException(429, {"message": GUESTS_FULL, "code": "guests_full"})
    if not repo.take_guest_start(_client_network(request), GUEST_STARTS_PER_NETWORK, 2 * 86400):
        raise HTTPException(
            429,
            {
                "message": "Too many free trials from your network today. "
                "Sign in to keep using the Advisor.",
                "code": "guest_limit",
            },
        )
    if settings.dev_auth:
        return GuestStart(dev_user=f"guest-{new_id()}")
    if not (settings.user_pool_id and settings.web_client_id):
        raise HTTPException(503, {"message": GUESTS_CLOSED, "code": "guests_closed"})
    return GuestStart(
        **guests.create(cognito_client(), settings.user_pool_id, settings.web_client_id)
    )


@app.get("/rules")
def issuer_rules(
    snapshot: CatalogDep, issuer_id: Annotated[str | None, Query(max_length=40)] = None
) -> dict:
    """The Eligibility Rules in plain English (ADR 0009): what each counts, what it decides,
    and its source. The Advisor explains rules only from this."""
    names = {c.id: c.name for c in snapshot.cards}
    return {
        "rules": [
            explain(r, names) for r in load_rules() if issuer_id is None or r.issuer_id == issuer_id
        ]
    }


@app.post("/me/chat/turns", status_code=201)
def save_chat_turn(body: ChatTurnIn, caller: CallerDep, repo: RepoDep) -> dict:
    """The agent records each answer (with the user's token) so the user can rate it."""
    created = datetime.now(ZoneInfo("UTC")).isoformat(timespec="seconds")
    repo.put_turn(caller.uid, ChatTurn(**body.model_dump(), created_at=created))
    return {"turn_id": body.turn_id}


@app.put("/me/chat/turns/{turn_id}/feedback", status_code=204)
def rate_chat_turn(turn_id: str, body: TurnFeedback, caller: CallerDep, repo: RepoDep) -> None:
    """👍 / 👎 on one answer; the site says rating keeps that exchange 90 days (ADR 0009)."""
    rated = datetime.now(ZoneInfo("UTC")).isoformat(timespec="seconds")
    if not repo.rate_turn(caller.uid, turn_id, body, rated):
        raise HTTPException(404, "That answer has expired or isn't yours.")


# --- Invites ----------------------------------------------------------------------------


@app.post("/admin/invites", status_code=201)
def create_invites(body: InviteBatchIn, caller: CallerDep, repo: RepoDep) -> dict:
    require_admin(caller)
    codes = [invites.new_code() for _ in range(body.count)]
    for code in codes:
        repo.create_invite(code, body.uses)
    return {"codes": [invites.display(c) for c in codes], "uses_each": body.uses}


@app.get("/admin/advisor/spend")
def advisor_spend(caller: CallerDep, repo: RepoDep) -> dict:
    """The Advisor's running cost and whether the guest trial is still open."""
    require_admin(caller)
    total = repo.spend()
    return {
        "total_usd": round(total, 4),
        "guest_budget_usd": settings.guest_budget_usd,
        "guests_open": total < settings.guest_budget_usd,
        "guest_messages_today": repo.guest_messages(_chat_day()[0].isoformat()),
        "guest_daily_limit": settings.guest_daily_limit,
    }


@app.get("/admin/invites")
def list_invites(caller: CallerDep, repo: RepoDep) -> list[Invite]:
    """Every code with its remaining uses and who took each use (unconfirmed = abandoned)."""
    require_admin(caller)
    return [i.model_copy(update={"code": invites.display(i.code)}) for i in repo.list_invites()]


@app.post("/dev/signup", status_code=201)
def dev_signup(body: SignupIn, repo: RepoDep) -> dict:
    """Local stand-in for Cognito sign-up and its triggers (card_api.triggers)."""
    if not settings.dev_auth:
        raise HTTPException(404)
    user = f"u-{new_id()}"
    if not repo.redeem_invite(invites.normalize(body.invite_code), user):
        raise HTTPException(403, "invite code is invalid or used up")
    repo.confirm_invite_use(user)  # no email step locally
    return {"user_id": user}
