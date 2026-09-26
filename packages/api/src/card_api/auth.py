"""Who is calling. Identity never comes from the request body or the LLM, only from:

- AWS: the API Gateway JWT authorizer's verified Cognito claims (Mangum exposes the raw event).
- local: an `X-Dev-User` header, accepted only when APP_ENV=local.
"""

import re
from dataclasses import dataclass

from fastapi import Header, HTTPException, Request

from card_api.settings import settings

_DEV_USER = re.compile(r"^[a-z0-9-]{3,40}$")


@dataclass(frozen=True)
class Caller:
    uid: str
    is_admin: bool


def _from_jwt(request: Request) -> Caller | None:
    event = request.scope.get("aws.event") or {}
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims")
    if not claims or not claims.get("sub"):
        return None
    groups = claims.get("cognito:groups", "")
    # HTTP API passes list claims as "[a b]" strings; normalize both forms.
    group_list = groups if isinstance(groups, list) else re.findall(r"[\w-]+", str(groups))
    return Caller(uid=claims["sub"], is_admin="admin" in group_list)


def current_caller(request: Request, x_dev_user: str | None = Header(None)) -> Caller:
    caller = _from_jwt(request)
    if caller:
        return caller
    if settings.dev_auth and x_dev_user:
        if not _DEV_USER.match(x_dev_user):
            raise HTTPException(400, "invalid dev user id")
        return Caller(uid=x_dev_user, is_admin=x_dev_user.startswith("admin"))
    raise HTTPException(401, "not signed in")


def require_admin(caller: Caller) -> Caller:
    if not caller.is_admin:
        raise HTTPException(403, "admin only")
    return caller
