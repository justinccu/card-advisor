from datetime import date, timedelta
from functools import lru_cache
from typing import Annotated

from card_rules.dates import add_months
from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware

from card_api import service
from card_api.auth import Caller, current_caller, require_admin
from card_api.catalog import catalog_index, load_catalog
from card_api.models import (
    ApplicantProfile,
    HeldCard,
    HeldCardIn,
    InviteBatchIn,
    SignupIn,
    Velocity,
    Wallet,
    WalletAttestation,
)
from card_api.repository import DynamoRepository, InMemoryRepository, Repository, new_id
from card_api.settings import settings

MAX_WALLET_CARDS = 100
DEMO_INVITE = "DEMO-2026"
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
    repo.create_invite(DEMO_INVITE, 100)
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Dev-User"],
)

CallerDep = Annotated[Caller, Depends(current_caller)]
RepoDep = Annotated[Repository, Depends(get_repo)]


@app.get("/health")
def health() -> dict:
    snapshot = load_catalog()
    return {"ok": True, "catalog_version": snapshot.version, "preview": snapshot.preview}


@app.get("/catalog")
def catalog(response: Response):
    response.headers["Cache-Control"] = "public, max-age=300"
    return load_catalog()


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
def add_card(body: HeldCardIn, caller: CallerDep, repo: RepoDep) -> HeldCard:
    if body.card_product_id and body.card_product_id not in catalog_index():
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
    caller: CallerDep, repo: RepoDep, as_of: Annotated[date | None, Query()] = None
) -> Velocity:
    wallet = service.to_rules_wallet(
        repo.list_cards(caller.uid), repo.get_attestation(caller.uid), catalog_index()
    )
    return service.velocity(wallet, _as_of(as_of))


@app.get("/me/eligibility")
def get_eligibility(
    caller: CallerDep,
    repo: RepoDep,
    card_id: Annotated[list[str] | None, Query(max_length=60)] = None,
    as_of: Annotated[date | None, Query()] = None,
) -> list[dict]:
    """Eligibility Verdicts for the given cards (default: every card open to applicants)."""
    index = catalog_index()
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
    return service.evaluate_cards(products, repo.get_profile(caller.uid), wallet, _as_of(as_of))


# --- Invites ----------------------------------------------------------------------------


@app.post("/admin/invites", status_code=201)
def create_invites(body: InviteBatchIn, caller: CallerDep, repo: RepoDep) -> dict:
    require_admin(caller)
    codes = [f"CA-{new_id()[:8].upper()}" for _ in range(body.count)]
    for code in codes:
        repo.create_invite(code, body.uses)
    return {"codes": codes, "uses_each": body.uses}


@app.post("/dev/signup", status_code=201)
def dev_signup(body: SignupIn, repo: RepoDep) -> dict:
    """Local stand-in for Cognito sign-up + the pre-sign-up trigger (see presignup.py)."""
    if not settings.dev_auth:
        raise HTTPException(404)
    if not repo.redeem_invite(body.invite_code.strip().upper()):
        raise HTTPException(403, "invite code is invalid or used up")
    return {"user_id": f"u-{new_id()}"}
