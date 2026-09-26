from functools import lru_cache

from card_rules.catalog import CatalogCard, CatalogSnapshot

from card_api.settings import settings


@lru_cache(maxsize=1)
def load_catalog() -> CatalogSnapshot:
    """The Catalog Snapshot this process serves: a local file in dev, S3 on AWS.

    Loaded once per process (a Lambda container keeps it warm); a new snapshot ships with a
    new deploy or container, which keeps every Recommendation tied to one catalog version.
    """
    if settings.catalog_bucket:
        import boto3

        body = (
            boto3.client("s3")
            .get_object(Bucket=settings.catalog_bucket, Key=settings.catalog_key)["Body"]
            .read()
        )
        return CatalogSnapshot.model_validate_json(body)
    if not settings.catalog_path.exists():
        raise RuntimeError(
            f"no catalog at {settings.catalog_path}; run `uv run scout preview` "
            "(or `scout publish` and point CATALOG_PATH at catalog/us/vMAJOR.MINOR.json)"
        )
    return CatalogSnapshot.model_validate_json(settings.catalog_path.read_text())


def catalog_index() -> dict[str, CatalogCard]:
    return {c.id: c for c in load_catalog().cards}
