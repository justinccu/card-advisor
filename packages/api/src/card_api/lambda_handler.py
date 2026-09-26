"""AWS entry points (API Lambda and the Cognito triggers); local and cloud run the same app code."""

from mangum import Mangum

from card_api import invites
from card_api.app import app, get_repo

# API Gateway HTTP API -> FastAPI. The JWT authorizer runs before this; auth.py reads its claims.
handler = Mangum(app, lifespan="off")


def presignup_handler(event, context):
    """Cognito pre sign-up trigger: invite-only registration. Runs before the account exists, so a
    bad code leaves nothing behind. The code rides along as clientMetadata from the sign-up form;
    one use is taken atomically and recorded against this user (`userName`, which equals the
    token `sub` in an email-sign-in pool). Raising rejects the sign-up."""
    request = event.get("request", {})
    code = (request.get("clientMetadata") or {}).get("invite_code", "")
    user = event.get("userName", "")
    if not code or not user or not get_repo().redeem_invite(invites.normalize(code), user):
        raise Exception("A valid invite code is required to sign up.")
    return event


def postconfirm_handler(event, context):
    """Cognito post confirmation trigger: marks the user's invite use as completed (email
    confirmed). Uses that never get here are codes burned by abandoned sign-ups; the record says
    which, so they can be reconciled or refunded later. Never blocks the user."""
    if event.get("triggerSource") == "PostConfirmation_ConfirmSignUp" and event.get("userName"):
        get_repo().confirm_invite_use(event["userName"])
    return event
