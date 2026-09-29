from datetime import date, datetime, time, timedelta
from functools import lru_cache
from typing import Annotated
from zoneinfo import ZoneInfo

from card_rules.catalog import VERSION_PATTERN, CatalogSnapshot
from card_rules.dates import add_months
from card_rules.ranking import RankOptions, rank
from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware

from card_api import invites, service
from card_api.auth import Caller, current_caller, require_admin
from card_api.catalog import UnknownCatalogVersion, catalog_index, load_catalog
from card_api.models import (
    ApplicantProfile,
    ChatQuota,
    HeldCard,
    HeldCardIn,
    Invite,
    InviteBatchIn,
    SignupIn,
    Velocity,
    Wallet,
    WalletAttestation,
)
from card_api.repository import DynamoRepository, InMemoryRepository, Repository, new_id
from card_api.settings import settings

MAX_WALLET_CARDS = 100
CHAT_DAILY_LIMIT = 10  # ADR 0009
CHAT_TIMEZONE = ZoneInfo("America/New_York")  # the quota resets at midnight US Eastern
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


app = FastAPI(title="card-advisor API", version="0.1.0")

CATALOG_VERSION_HEADER = "X-Catalog-Version"
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
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
    repo.put_profile(caller.uid, body)
    return body


@app.delete("/me", status_code=204)
def delete_me(caller: CallerDep, repo: RepoDep) -> None:
    # ADR 0005: account deletion purges everything we store about the user.
    repo.delete_user(caller.uid)


# --- Wallet -----------------------------------------------------------------------------


@app.get("/me/wallet")
def get_wallet(caller: CallerDep, repo: RepoDep) -> Wallet:
    return Wallet(cards=repo.list_cards(caller.uid), attestation=repo.get_attestation(caller.uid))


@app.post("/me/wallet/cards", status_code=201)
def add_card(body: HeldCardIn, caller: CallerDep, repo: RepoDep, snapshot: CatalogDep) -> HeldCard:
    if body.card_product_id and body.card_product_id not in catalog_index(snapshot):
        raise HTTPException(422, f"unknown card_product_id {body.card_product_id!r}")
    if len(repo.list_cards(caller.uid)) >= MAX_WALLET_CARDS:
        raise HTTPException(409, f"a Wallet holds at most {MAX_WALLET_CARDS} cards")
    return repo.add_card(caller.uid, body)


@app.delete("/me/wallet/cards/{card_id}", status_code=204)
def delete_card(card_id: str, caller: CallerDep, repo: RepoDep) -> None:
    if not repo.delete_card(caller.uid, card_id):
        raise HTTPException(404, "no such card in your Wallet")


@app.put("/me/wallet/attestation")
def put_attestation(body: WalletAttestation, caller: CallerDep, repo: RepoDep) -> WalletAttestation:
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


def _quota(used: int, resets_at: str) -> ChatQuota:
    return ChatQuota(
        limit=CHAT_DAILY_LIMIT,
        used=used,
        remaining=max(0, CHAT_DAILY_LIMIT - used),
        resets_at=resets_at,
    )


@app.get("/me/chat/quota")
def chat_quota(caller: CallerDep, repo: RepoDep) -> ChatQuota:
    day, resets_at = _chat_day()
    return _quota(repo.quota_used(caller.uid, day), resets_at)


@app.post("/me/chat/turn")
def chat_turn(caller: CallerDep, repo: RepoDep) -> ChatQuota:
    """Takes one Advisor message from today's quota (atomic), before any model is called."""
    day, resets_at = _chat_day()
    used = repo.take_quota(caller.uid, day, CHAT_DAILY_LIMIT)
    if used is None:
        raise HTTPException(
            429,
            {
                "message": f"You've used today's {CHAT_DAILY_LIMIT} Advisor messages.",
                **_quota(CHAT_DAILY_LIMIT, resets_at).model_dump(),
            },
        )
    return _quota(used, resets_at)


# --- Invites ----------------------------------------------------------------------------


@app.post("/admin/invites", status_code=201)
def create_invites(body: InviteBatchIn, caller: CallerDep, repo: RepoDep) -> dict:
    require_admin(caller)
    codes = [invites.new_code() for _ in range(body.count)]
    for code in codes:
        repo.create_invite(code, body.uses)
    return {"codes": [invites.display(c) for c in codes], "uses_each": body.uses}


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
