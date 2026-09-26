from datetime import UTC, datetime

import boto3
import pytest
from card_rules.catalog import CatalogSnapshot
from card_rules.models import Market
from moto import mock_aws
from scout import release

PREFIX = "catalog/us/"


def write(dir_, version):
    snap = CatalogSnapshot(
        version=version, market=Market.US, generated_at=datetime.now(UTC), cards=[]
    )
    (dir_ / f"v{version}.json").write_text(snap.model_dump_json())


@pytest.fixture
def s3():
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-2")
        client.create_bucket(
            Bucket="cat", CreateBucketConfiguration={"LocationConstraint": "us-east-2"}
        )
        yield client


def ship(s3, tmp_path, version=None, **kw):
    p, body = release.plan(s3, "cat", PREFIX, version, catalog_dir=tmp_path, **kw)
    release.apply(s3, "cat", p, body)
    return p


def pointer(s3):
    return s3.get_object(Bucket="cat", Key=PREFIX + "LATEST")["Body"].read().decode()


def test_release_uploads_newest_snapshot_then_moves_the_pointer(s3, tmp_path):
    write(tmp_path, "1.4")
    write(tmp_path, "1.10")
    p = ship(s3, tmp_path)
    assert p.version == "1.10" and p.upload and p.previous is None
    assert pointer(s3) == "1.10"
    assert s3.head_object(Bucket="cat", Key=PREFIX + "v1.10.json")


def test_rereleasing_identical_bytes_is_a_no_op(s3, tmp_path):
    write(tmp_path, "1.4")
    ship(s3, tmp_path)
    again, _ = release.plan(s3, "cat", PREFIX, catalog_dir=tmp_path)
    assert again.upload is False


def test_never_overwrites_a_released_version(s3, tmp_path):
    write(tmp_path, "1.4")
    ship(s3, tmp_path)
    write(tmp_path, "1.4")  # same version number, new generated_at -> different bytes
    with pytest.raises(release.ReleaseError, match="different content"):
        release.plan(s3, "cat", PREFIX, catalog_dir=tmp_path)


def test_conditional_write_catches_a_racing_release(s3, tmp_path):
    write(tmp_path, "1.4")
    p, body = release.plan(s3, "cat", PREFIX, catalog_dir=tmp_path)
    s3.put_object(Bucket="cat", Key=PREFIX + "v1.4.json", Body=b"{}")  # someone else, meanwhile
    with pytest.raises(release.ReleaseError, match="someone else"):
        release.apply(s3, "cat", p, body)


def test_pointer_moves_back_only_on_purpose(s3, tmp_path):
    write(tmp_path, "1.3")
    write(tmp_path, "1.4")
    ship(s3, tmp_path, "1.4")
    with pytest.raises(release.ReleaseError, match="--rollback"):
        release.plan(s3, "cat", PREFIX, "1.3", catalog_dir=tmp_path)
    ship(s3, tmp_path, "1.3", rollback=True)
    assert pointer(s3) == "1.3"


def test_missing_local_snapshot_is_refused(s3, tmp_path):
    with pytest.raises(release.ReleaseError, match="nothing published"):
        release.plan(s3, "cat", PREFIX, catalog_dir=tmp_path)
    with pytest.raises(release.ReleaseError, match="no local snapshot"):
        release.plan(s3, "cat", PREFIX, "9.9", catalog_dir=tmp_path)
