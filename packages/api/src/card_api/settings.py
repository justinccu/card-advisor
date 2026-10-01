import os
from dataclasses import dataclass, field
from pathlib import Path


def repo_root(module_file: Path) -> Path:
    """The checkout root when running from the repo (packages/api/src/card_api/settings.py);
    otherwise the working directory. On Lambda the module sits at /var/task/card_api/, which has
    no repo above it, and only the S3 catalog is used there anyway."""
    parents = module_file.resolve().parents
    return parents[3] if len(parents) > 4 and (parents[3] / "catalog").is_dir() else Path.cwd()


REPO_ROOT = repo_root(Path(__file__))


@dataclass(frozen=True)
class Settings:
    """`local` runs on a laptop with an in-memory store and dev sign-in; `aws` runs on Lambda
    behind an API Gateway JWT authorizer, with DynamoDB and the catalog in S3."""

    env: str = os.environ.get("APP_ENV", "local")
    table_name: str | None = os.environ.get("TABLE_NAME")
    # Where Catalog Snapshots come from (card_api.catalog): S3 on AWS; locally the published
    # files in catalog/us, one explicit file (CATALOG_PATH), or the preview if none is published.
    catalog_bucket: str | None = os.environ.get("CATALOG_BUCKET")
    catalog_prefix: str = os.environ.get("CATALOG_PREFIX", "catalog/us/")
    catalog_dir: Path = REPO_ROOT / "catalog" / "us"
    catalog_file: Path | None = (
        Path(os.environ["CATALOG_PATH"]) if os.environ.get("CATALOG_PATH") else None
    )
    preview_path: Path = REPO_ROOT / "catalog" / ".cache" / "preview_snapshot.json"
    # The Advisor's AgentCore Memory (card_api.memory); unset until the agent is deployed.
    advisor_memory_id: str | None = os.environ.get("ADVISOR_MEMORY_ID") or None
    # Guests on the Advisor trial get Cognito accounts made by the API (card_api.guests).
    user_pool_id: str | None = os.environ.get("USER_POOL_ID") or None
    web_client_id: str | None = os.environ.get("WEB_CLIENT_ID") or None
    # The guest trial closes once the Advisor's running cost reaches this (ADR 0009).
    guest_budget_usd: float = float(os.environ.get("ADVISOR_GUEST_BUDGET_USD", "50"))
    # ...and takes at most this many guest messages a day, all guests together (~$4.50 at
    # ~$0.015 a message), so getting around the per-guest limits can't spend the budget in a day.
    guest_daily_limit: int = int(os.environ.get("ADVISOR_GUEST_DAILY_LIMIT", "300"))
    cors_origins: list[str] = field(
        default_factory=lambda: os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
    )

    @property
    def dev_auth(self) -> bool:
        # Dev sign-in exists only locally; on AWS identity comes solely from the verified JWT.
        return self.env == "local"


settings = Settings()
