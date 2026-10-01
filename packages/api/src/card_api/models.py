"""API request/response shapes. Names follow CONTEXT.md."""

from datetime import date
from typing import Literal

from card_rules.models import TaxId
from card_rules.ranking import SpendingProfile
from pydantic import BaseModel, Field, model_validator

# Ranges, never exact numbers (ADR 0005): we don't want to hold precise scores or incomes.
ScoreBand = Literal["none", "under_580", "580_669", "670_739", "740_799", "800_plus"]
IncomeBand = Literal["under_25k", "25k_50k", "50k_100k", "100k_200k", "200k_plus"]
HistoryBand = Literal["none", "under_1y", "1_2y", "2_5y", "5y_plus"]


class ApplicantProfile(BaseModel):
    tax_id: TaxId | None = None
    score_band: ScoreBand | None = None
    income_band: IncomeBand | None = None
    credit_history: HistoryBand | None = None
    # What ranking uses (ADR 0009); None until the user fills it in.
    spending: SpendingProfile | None = None


class HeldCardIn(BaseModel):
    """A card the user holds. Either a catalog card (`card_product_id`) or an off-catalog one
    (issuer + name), because 5/24 counts every card, including store cards we don't list."""

    card_product_id: str | None = Field(None, max_length=80)
    issuer_id: str | None = Field(None, max_length=40)
    name: str | None = Field(None, max_length=120)
    opened_on: date
    closed_on: date | None = None
    is_authorized_user: bool = False
    is_business: bool = False
    bonus_received_on: date | None = None

    @model_validator(mode="after")
    def _identified(self):
        if not self.card_product_id and not (self.issuer_id and self.name):
            raise ValueError("give card_product_id, or issuer_id and name for off-catalog cards")
        if self.closed_on and self.closed_on < self.opened_on:
            raise ValueError("closed_on is before opened_on")
        if self.opened_on > date.today():
            raise ValueError("opened_on is in the future")
        return self


class HeldCard(HeldCardIn):
    id: str


class HeldCardPatch(BaseModel):
    """Corrections to a held card. Only the fields sent change; `closed_on: null` reopens it."""

    opened_on: date | None = None
    closed_on: date | None = None
    is_authorized_user: bool | None = None


class WalletAttestation(BaseModel):
    complete_since: date | None = None
    includes_all_open_cards: bool = False
    full_history_issuers: list[str] = Field(default_factory=list, max_length=20)


class Wallet(BaseModel):
    cards: list[HeldCard]
    attestation: WalletAttestation


class Velocity(BaseModel):
    """Personal cards opened in the last 24 months, from any issuer (the 5/24 count)."""

    count_24m: int
    next_drop_off: date | None
    complete: bool  # whether the Wallet Attestation covers the whole window


class SignupIn(BaseModel):
    invite_code: str = Field(min_length=4, max_length=40)


class InviteBatchIn(BaseModel):
    count: int = Field(1, ge=1, le=50)
    uses: int = Field(1, ge=1, le=100)


class InviteUse(BaseModel):
    """Who took one use of a code, and whether they finished sign-up (confirmed their email).
    A use that never confirms is a code burned by an abandoned sign-up."""

    user: str
    taken_at: int  # epoch seconds
    confirmed_at: int | None = None


class Invite(BaseModel):
    code: str
    remaining: int
    uses: list[InviteUse] = []


class ChatQuota(BaseModel):
    """Advisor messages left (ADR 0009): 30 per user per day, reset at midnight US Eastern; a
    guest's trial is 10 in all and never resets."""

    limit: int
    used: int
    remaining: int
    resets_at: str | None  # ISO timestamp of the next US Eastern midnight; None for a guest
    guest: bool = False


class ChatUsage(BaseModel):
    """What one Advisor message cost (model tokens at list price, plus Runtime and Memory),
    reported by the agent; it adds up to the spend that closes the guest trial."""

    cost_usd: float = Field(ge=0, le=1)


class GuestStart(BaseModel):
    """A guest's identity for the Advisor trial: Cognito tokens on AWS (refreshed by the site
    with the refresh token), or a dev user id locally."""

    access_token: str | None = None
    refresh_token: str | None = None
    expires_in: int | None = None
    dev_user: str | None = None


# --- Advisor answer feedback (ADR 0009) ---------------------------------------------------


class ToolCall(BaseModel):
    """A tool the Advisor called for an answer, with what it returned (truncated by the agent).
    This is what tells a data mistake from a model mistake when an answer is rated down."""

    name: str = Field(max_length=60)
    input: str = Field("", max_length=2000)
    result: str = Field("", max_length=6000)


class ChatTurnIn(BaseModel):
    """One Advisor answer, written by the agent with the user's own token. Kept 7 days, like
    Memory, or 90 once the user rates it; deleted with the account."""

    turn_id: str = Field(pattern=r"^[0-9a-z-]{8,64}$")
    question: str = Field(max_length=2000)
    answer: str = Field(max_length=12000)
    tools: list[ToolCall] = Field(default_factory=list, max_length=20)
    model_id: str = Field(max_length=100)
    prompt_version: str = Field(max_length=40)
    catalog_version: str | None = Field(None, max_length=20)
    rules_version: str | None = Field(None, max_length=20)


FeedbackReason = Literal["wrong_info", "not_what_i_asked", "missing_info", "other"]


class TurnFeedback(BaseModel):
    rating: Literal["up", "down"]
    reason: FeedbackReason | None = None
    comment: str | None = Field(None, max_length=500)


class ChatTurn(ChatTurnIn):
    created_at: str  # ISO timestamp
    feedback: TurnFeedback | None = None
    rated_at: str | None = None
