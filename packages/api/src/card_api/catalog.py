"""Which Catalog Snapshot a request is served from (ADR 0003).

Snapshots are immutable (`catalog/us/v1.4.json` is never rewritten), so a snapshot cached by its
version never goes stale and needs no invalidation. The only moving part is which version is
latest: a tiny pointer (`catalog/us/LATEST` on S3, or the newest file locally), re-read at most
every LATEST_TTL_SECONDS. Publishing a new version therefore reaches every warm Lambda within
that window, without a redeploy, and a caller that pins `catalog_version` (the static site pins
the version it was built from) is answered from exactly that version, before and after the switch.
Every response says which version it used, so a Recommendation can be reproduced later.
"""

import re
import time
from collections import OrderedDict
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

from card_rules.catalog import VERSION_PATTERN, CatalogCard, CatalogSnapshot, version_key

from card_api.settings import settings

LATEST_TTL_SECONDS = 60
MAX_CACHED_VERSIONS = 3  # latest, the one before it, and a pinned straggler


class UnknownCatalogVersion(LookupError):
    pass


class CatalogStore:
    """Resolves versions and caches immutable snapshots. Subclasses only fetch."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._latest: tuple[str, float] | None = None  # (version, when it was read)
        self._snapshots: OrderedDict[str, CatalogSnapshot] = OrderedDict()

    def _read_latest(self) -> str:
        raise NotImplementedError

    def _read_snapshot(self, version: str) -> CatalogSnapshot:
        raise NotImplementedError

    def latest_version(self) -> str:
        now = self._clock()
        if self._latest is None or now - self._latest[1] >= LATEST_TTL_SECONDS:
            self._latest = (self._read_latest(), now)
        return self._latest[0]

    def get(self, version: str | None = None) -> CatalogSnapshot:
        """The snapshot for `version` (default: latest). Raises UnknownCatalogVersion."""
        version = version or self.latest_version()
        if version in self._snapshots:
            self._snapshots.move_to_end(version)
            return self._snapshots[version]
        snapshot = self._read_snapshot(version)
        if snapshot.version != version:
            raise UnknownCatalogVersion(f"the file for v{version} holds v{snapshot.version}")
        self._snapshots[version] = snapshot
        while len(self._snapshots) > MAX_CACHED_VERSIONS:
            self._snapshots.popitem(last=False)
        return snapshot


class FileCatalogStore(CatalogStore):
    """Local: the published files in catalog/us; or one explicit file (CATALOG_PATH); or, when
    nothing is published, the unreviewed preview."""

    def __init__(
        self, directory: Path, *, single: Path | None = None, preview: Path | None = None, **kw
    ) -> None:
        super().__init__(**kw)
        self._dir, self._single, self._preview = directory, single, preview

    def _published(self) -> list[str]:
        if not self._dir.is_dir():
            return []
        found = [p.stem[1:] for p in self._dir.glob("v*.json")]
        return sorted((v for v in found if re.fullmatch(VERSION_PATTERN, v)), key=version_key)

    def _only(self) -> CatalogSnapshot | None:
        """The one snapshot served when there's no directory of versions to choose from."""
        path = self._single or (None if self._published() else self._preview)
        if path is None:
            return None
        if not path.exists():
            raise RuntimeError(
                f"no catalog at {path}; run `uv run scout preview` "
                "(or `scout publish` and point CATALOG_PATH at catalog/us/vMAJOR.MINOR.json)"
            )
        return CatalogSnapshot.model_validate_json(path.read_text())

    def _read_latest(self) -> str:
        only = self._only()
        return only.version if only else self._published()[-1]

    def _read_snapshot(self, version: str) -> CatalogSnapshot:
        only = self._only()
        if only is not None:
            if only.version != version:
                raise UnknownCatalogVersion(version)
            return only
        path = self._dir / f"v{version}.json"
        if not path.exists():
            raise UnknownCatalogVersion(version)
        return CatalogSnapshot.model_validate_json(path.read_text())


class S3CatalogStore(CatalogStore):
    """AWS: `<prefix>LATEST` holds the latest version string and `<prefix>v<version>.json` the
    snapshots, each uploaded once and never overwritten (`scout release`)."""

    def __init__(self, bucket: str, prefix: str, *, client=None, **kw) -> None:
        super().__init__(**kw)
        if client is None:
            import boto3

            client = boto3.client("s3")
        self._s3, self._bucket, self._prefix = client, bucket, prefix

    def _get(self, key: str) -> bytes:
        return self._s3.get_object(Bucket=self._bucket, Key=self._prefix + key)["Body"].read()

    def _read_latest(self) -> str:
        version = self._get("LATEST").decode().strip()
        if not re.fullmatch(VERSION_PATTERN, version):
            raise RuntimeError(f"the catalog pointer holds {version!r}, not MAJOR.MINOR")
        return version

    def _read_snapshot(self, version: str) -> CatalogSnapshot:
        try:
            body = self._get(f"v{version}.json")
        except self._s3.exceptions.NoSuchKey as e:
            raise UnknownCatalogVersion(version) from e
        return CatalogSnapshot.model_validate_json(body)


@lru_cache(maxsize=1)
def store() -> CatalogStore:
    if settings.catalog_bucket:
        return S3CatalogStore(settings.catalog_bucket, settings.catalog_prefix)
    return FileCatalogStore(
        settings.catalog_dir, single=settings.catalog_file, preview=settings.preview_path
    )


def load_catalog(version: str | None = None) -> CatalogSnapshot:
    return store().get(version)


def catalog_index(snapshot: CatalogSnapshot) -> dict[str, CatalogCard]:
    return {c.id: c for c in snapshot.cards}
