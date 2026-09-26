"""AWS entry points. Not deployed yet; kept here so local and cloud run the same app code."""

from mangum import Mangum

from card_api.app import app, get_repo

# API Gateway HTTP API -> FastAPI. The JWT authorizer runs before this; auth.py reads its claims.
handler = Mangum(app, lifespan="off")


def presignup_handler(event, context):
    """Cognito pre sign-up trigger: invite-only registration (the invite code rides along as
    clientMetadata from the sign-up form). Raising rejects the sign-up."""
    code = (event.get("request", {}).get("clientMetadata") or {}).get("invite_code", "")
    if not code or not get_repo().redeem_invite(code.strip().upper()):
        raise Exception("A valid invite code is required to sign up.")
    return event
