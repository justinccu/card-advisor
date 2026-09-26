import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from card_rules.catalog import VERSION_PATTERN, version_key

REPO_ROOT = Path(__file__).resolve().parents[4]


def default_catalog_path() -> Path:
    """CATALOG_PATH if set; else the newest published catalog/us/vMAJOR.MINOR.json; else the
    local preview."""
    if os.environ.get("CATALOG_PATH"):
        return Path(os.environ["CATALOG_PATH"])
    published = sorted(
        (
            p
            for p in (REPO_ROOT / "catalog" / "us").glob("v*.json")
            if re.fullmatch(VERSION_PATTERN, p.stem[1:])
        ),
        key=lambda p: version_key(p.stem[1:]),
    )
    return (
        published[-1] if published else REPO_ROOT / "catalog" / ".cache" / "preview_snapshot.json"
    )


@dataclass(frozen=True)
class Settings:
    """`local` runs on a laptop with an in-memory store and dev sign-in; `aws` runs on Lambda
    behind an API Gateway JWT authorizer, with DynamoDB and the catalog in S3."""

    env: str = os.environ.get("APP_ENV", "local")
    table_name: str | None = os.environ.get("TABLE_NAME")
    catalog_path: Path = field(default_factory=lambda: default_catalog_path())
    catalog_bucket: str | None = os.environ.get("CATALOG_BUCKET")
    catalog_key: str = os.environ.get("CATALOG_KEY", "catalog/us/latest.json")
    cors_origins: list[str] = field(
        default_factory=lambda: os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
    )

    @property
    def dev_auth(self) -> bool:
        # Dev sign-in exists only locally; on AWS identity comes solely from the verified JWT.
        return self.env == "local"


settings = Settings()
