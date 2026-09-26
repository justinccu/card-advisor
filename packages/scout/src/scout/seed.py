from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[4]
SEED_PATH = REPO_ROOT / "catalog" / "seed" / "us_cards.yaml"
CACHE_DIR = REPO_ROOT / "catalog" / ".cache"


class SeedCard(BaseModel):
    id: str
    issuer_id: str
    name: str
    url: str
    priority: Literal["P0", "P1"]
    tags: list[str] = []
    family: str | None = None
    is_business: bool = False
    is_charge_card: bool = False
    availability: str = "open"
    closed_on: str | None = None
    tax_id_hint: str | None = None
    # Public campaign/landing pages for the same card (e.g. an ad-channel URL with a different
    # offer). Fetched with the same honest profile; each becomes an offer variant.
    variant_urls: list[str] = []


def load_seed(path: Path = SEED_PATH) -> list[SeedCard]:
    return [SeedCard.model_validate(c) for c in yaml.safe_load(path.read_text())]


def select(
    cards: list[SeedCard], *, priority: str | None, only: list[str] | None
) -> list[SeedCard]:
    if only:
        unknown = set(only) - {c.id for c in cards}
        if unknown:
            raise SystemExit(f"unknown card ids: {', '.join(sorted(unknown))}")
        return [c for c in cards if c.id in only]
    return [
        c
        for c in cards
        if (priority is None or c.priority == priority) and c.availability == "open"
    ]
