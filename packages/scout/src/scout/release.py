"""Ship a published Catalog Snapshot to S3, where the API reads it (card_api.catalog).

A version is uploaded once and never overwritten (S3 conditional write), then the `LATEST`
pointer moves to it; warm API containers pick the new pointer up within a minute. Re-releasing
the same bytes is a no-op, different bytes under an existing version is refused, and the pointer
only moves backwards on purpose (a rollback), never by accident.
"""

from dataclasses import dataclass
from pathlib import Path

from card_rules.catalog import CatalogSnapshot, version_key

from scout import publish


class ReleaseError(Exception):
    pass


@dataclass
class Plan:
    version: str
    snapshot_key: str
    pointer_key: str
    upload: bool  # False when that version is already on S3 with identical bytes
    previous: str | None  # what LATEST pointed at before


def _read(s3, bucket: str, key: str) -> bytes | None:
    try:
        return s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    except s3.exceptions.NoSuchKey:
        return None


def plan(
    s3,
    bucket: str,
    prefix: str,
    version: str | None = None,
    *,
    catalog_dir: Path = publish.CATALOG_DIR,
    rollback: bool = False,
) -> tuple[Plan, bytes]:
    version = version or publish.latest(catalog_dir)[0]
    if version is None:
        raise ReleaseError("nothing published yet (run `scout publish`)")
    path = catalog_dir / f"v{version}.json"
    if not path.exists():
        raise ReleaseError(f"no local snapshot {path.name}")
    body = path.read_bytes()
    if CatalogSnapshot.model_validate_json(body).version != version:
        raise ReleaseError(f"{path.name} does not hold version {version}")

    snapshot_key, pointer_key = f"{prefix}v{version}.json", f"{prefix}LATEST"
    existing = _read(s3, bucket, snapshot_key)
    if existing is not None and existing != body:
        raise ReleaseError(f"s3://{bucket}/{snapshot_key} exists with different content")
    pointer = _read(s3, bucket, pointer_key)
    previous = pointer.decode().strip() if pointer else None
    if previous and version_key(version) < version_key(previous) and not rollback:
        raise ReleaseError(f"LATEST is {previous}; moving it back to {version} needs --rollback")
    return Plan(version, snapshot_key, pointer_key, existing is None, previous), body


def apply(s3, bucket: str, p: Plan, body: bytes) -> None:
    if p.upload:
        try:
            # IfNoneMatch: the write fails if the key appeared meanwhile, so no version is ever
            # overwritten, even by two releases racing each other.
            s3.put_object(
                Bucket=bucket,
                Key=p.snapshot_key,
                Body=body,
                ContentType="application/json",
                IfNoneMatch="*",
            )
        except s3.exceptions.ClientError as e:
            if e.response["Error"]["Code"] in ("PreconditionFailed", "ConditionalRequestConflict"):
                raise ReleaseError(f"{p.snapshot_key} was written by someone else") from e
            raise
    s3.put_object(
        Bucket=bucket,
        Key=p.pointer_key,
        Body=p.version.encode(),
        ContentType="text/plain",
        CacheControl="no-cache",
    )
