import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]


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
    cors_origins: list[str] = field(
        default_factory=lambda: os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
    )

    @property
    def dev_auth(self) -> bool:
        # Dev sign-in exists only locally; on AWS identity comes solely from the verified JWT.
        return self.env == "local"


settings = Settings()
