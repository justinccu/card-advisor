"""The card-advisor HTTP API, called with the user's own identity (ADR 0009).

The agent holds no data permissions of its own: every read goes through the API as the user, so
it can see exactly what the user can see and nothing more.
"""

import os
import time
from typing import Any

import httpx

API_URL = os.environ.get("ADVISOR_API_URL", "http://localhost:8000").rstrip("/")
CATALOG_TTL_SECONDS = 300


class ApiError(Exception):
    def __init__(self, status: int, detail: Any):
        super().__init__(f"API {status}: {detail}")
        self.status, self.detail = status, detail


class QuotaExceeded(ApiError):
    pass


# The catalog is public and the same for everyone; cache it per process.
_catalog: dict[str, Any] = {"at": 0.0, "version": None, "cards": {}}


class AdvisorApi:
    def __init__(self, headers: dict[str, str], *, base_url: str = API_URL, client=None):
        self._client = client or httpx.Client(base_url=base_url, timeout=10.0)
        self._headers = headers

    def _call(self, method: str, path: str, **kw) -> Any:
        res = self._client.request(method, path, headers=self._headers, **kw)
        if res.status_code == 429 and path == "/me/chat/turn":
            raise QuotaExceeded(429, res.json().get("detail"))
        if res.status_code >= 400:
            try:
                detail = res.json().get("detail")
            except ValueError:
                detail = res.text[:200]
            raise ApiError(res.status_code, detail)
        return res.json() if res.content else None

    def take_turn(self) -> dict:
        """One message from today's quota; raises QuotaExceeded when it's used up."""
        return self._call("POST", "/me/chat/turn")

    def profile(self) -> dict:
        return self._call("GET", "/me/profile")

    def wallet(self) -> dict:
        return self._call("GET", "/me/wallet")

    def velocity(self) -> dict:
        return self._call("GET", "/me/velocity")

    def eligibility(self, card_ids: list[str]) -> dict:
        return self._call("GET", "/me/eligibility", params=[("card_id", c) for c in card_ids])

    def recommendations(self, options: dict) -> dict:
        return self._call("POST", "/me/recommendations", json=options)

    def card(self, card_id: str) -> dict | None:
        if time.monotonic() - _catalog["at"] > CATALOG_TTL_SECONDS or not _catalog["cards"]:
            snapshot = self._call("GET", "/catalog")
            _catalog.update(
                at=time.monotonic(),
                version=snapshot["version"],
                cards={c["id"]: c for c in snapshot["cards"]},
            )
        return _catalog["cards"].get(card_id)
