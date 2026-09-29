"""Who is calling (ADR 0009).

The user id is the access token's `sub`, never anything the model or the request body says.
AgentCore Runtime has already verified the token (CUSTOM_JWT authorizer, our Cognito web client
only), so its signature isn't checked again here; the same token is forwarded to the API, where
API Gateway verifies it once more.

Local development (`agentcore dev`) has no Cognito token. With ADVISOR_LOCAL=1, calls go to the
local API as the demo site's signed-in dev user (the DEV_USER_HEADER the site sends), or as
ADVISOR_DEV_USER for CLI prompts. Both variables exist only in the local `.env.local`; the deployed
runtime never has them, and its header allowlist forwards only Authorization.
"""

import os
from dataclasses import dataclass

import jwt

# Headers under this prefix reach agent code; the site sends it only in its local dev mode.
DEV_USER_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Dev-User"


class NotSignedIn(Exception):
    pass


@dataclass(frozen=True)
class Caller:
    user_id: str
    headers: dict[str, str]  # what identifies the caller to the API


def caller_from(request_headers: dict[str, str] | None) -> Caller:
    headers = {k.lower(): v for k, v in (request_headers or {}).items()}
    auth = headers.get("authorization", "")
    if auth.startswith("Bearer "):
        try:
            claims = jwt.decode(auth.split(" ", 1)[1], options={"verify_signature": False})
        except jwt.PyJWTError as e:
            raise NotSignedIn("unreadable token") from e
        if claims.get("token_use") != "access" or not claims.get("sub"):
            raise NotSignedIn("not a Cognito access token")
        return Caller(user_id=claims["sub"], headers={"Authorization": auth})
    dev_user = headers.get(DEV_USER_HEADER.lower()) or os.environ.get("ADVISOR_DEV_USER")
    if os.environ.get("ADVISOR_LOCAL") == "1" and dev_user:
        return Caller(user_id=dev_user, headers={"X-Dev-User": dev_user})
    raise NotSignedIn("sign in to use the Advisor")
