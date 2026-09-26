import json
from datetime import UTC, datetime

import boto3
import pytest
from card_api.catalog import (
    LATEST_TTL_SECONDS,
    FileCatalogStore,
    S3CatalogStore,
    UnknownCatalogVersion,
)
from card_rules.catalog import CatalogSnapshot
from card_rules.models import Market
from moto import mock_aws


def snapshot(version: str) -> str:
    return CatalogSnapshot(
        version=version, market=Market.US, generated_at=datetime.now(UTC), cards=[]
    ).model_dump_json()


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_file_store_serves_newest_version_and_any_pinned_one(tmp_path):
    for v in ("1.2", "1.10", "1.9"):
        (tmp_path / f"v{v}.json").write_text(snapshot(v))
    store = FileCatalogStore(tmp_path)
    assert store.get().version == "1.10"  # numeric, not string, order
    assert store.get("1.2").version == "1.2"
    with pytest.raises(UnknownCatalogVersion):
        store.get("2.0")


def test_file_store_falls_back_to_the_preview_when_nothing_is_published(tmp_path):
    preview = tmp_path / "preview.json"
    preview.write_text(snapshot("0.0"))
    assert FileCatalogStore(tmp_path / "none", preview=preview).get().version == "0.0"


@pytest.fixture
def s3():
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-2")
        client.create_bucket(
            Bucket="cat", CreateBucketConfiguration={"LocationConstraint": "us-east-2"}
        )
        yield client


def put(s3, key, body):
    s3.put_object(Bucket="cat", Key=f"catalog/us/{key}", Body=body)


def test_new_version_reaches_a_warm_store_within_the_ttl(s3):
    put(s3, "v1.4.json", snapshot("1.4"))
    put(s3, "LATEST", "1.4")
    clock = Clock()
    store = S3CatalogStore("cat", "catalog/us/", client=s3, clock=clock)
    assert store.get().version == "1.4"

    put(s3, "v1.5.json", snapshot("1.5"))
    put(s3, "LATEST", "1.5")
    clock.now = LATEST_TTL_SECONDS - 1
    assert store.get().version == "1.4"  # pointer still cached
    assert store.get("1.5").version == "1.5"  # but a pinned request gets exactly what it asked for
    clock.now = LATEST_TTL_SECONDS
    assert store.get().version == "1.5"
    assert store.get("1.4").version == "1.4"  # old version still answerable (immutable)


def test_snapshots_are_fetched_once_per_version(s3):
    put(s3, "v1.4.json", snapshot("1.4"))
    put(s3, "LATEST", "1.4")
    store = S3CatalogStore("cat", "catalog/us/", client=s3, clock=Clock())
    first = store.get("1.4")
    s3.delete_object(Bucket="cat", Key="catalog/us/v1.4.json")
    assert store.get("1.4") is first  # served from cache, no S3 read


def test_unknown_or_mislabelled_versions_are_rejected(s3):
    put(s3, "LATEST", "1.4")
    put(s3, "v1.4.json", snapshot("1.3"))  # file content doesn't match its name
    store = S3CatalogStore("cat", "catalog/us/", client=s3, clock=Clock())
    with pytest.raises(UnknownCatalogVersion):
        store.get("1.4")
    with pytest.raises(UnknownCatalogVersion):
        store.get("7.7")


def test_a_malformed_pointer_fails_loudly(s3):
    put(s3, "LATEST", json.dumps({"v": 1}))
    with pytest.raises(RuntimeError, match="MAJOR.MINOR"):
        S3CatalogStore("cat", "catalog/us/", client=s3, clock=Clock()).get()
