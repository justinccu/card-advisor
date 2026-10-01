"""Cognito user-pool triggers for invite-only sign-up.

Kept apart from the web app: Cognito gives a trigger 5 seconds, so a cold start here imports only
the repository, not FastAPI and the catalog.
"""

from functools import lru_cache

from card_api import invites
from card_api.repository import DynamoRepository, Repository
from card_api.settings import settings


@lru_cache(maxsize=1)
def get_repo() -> Repository:
    if not settings.table_name:
        raise RuntimeError("TABLE_NAME is not set")
    return DynamoRepository(settings.table_name)


def presignup_handler(event, context):
    """Pre sign-up: runs before the account exists, so a bad code leaves nothing behind. The code
    rides along as clientMetadata from the sign-up form; one use is taken atomically and recorded
    against this user (`userName`, which equals the token `sub` in an email-sign-in pool).
    Raising rejects the sign-up.

    Accounts the API makes for guests (AdminCreateUser, card_api.guests) need no code: only an
    IAM principal allowed to administer the pool can make that call, never a visitor."""
    if event.get("triggerSource") == "PreSignUp_AdminCreateUser":
        return event
    request = event.get("request", {})
    code = (request.get("clientMetadata") or {}).get("invite_code", "")
    user = event.get("userName", "")
    if not code or not user or not get_repo().redeem_invite(invites.normalize(code), user):
        raise Exception("A valid invite code is required to sign up.")
    return event


def postconfirm_handler(event, context):
    """Post confirmation: marks the user's invite use as completed (email confirmed). Uses that
    never get here are codes burned by abandoned sign-ups; the record says which, so they can be
    reconciled or refunded later. Never blocks the user."""
    if event.get("triggerSource") == "PostConfirmation_ConfirmSignUp" and event.get("userName"):
        get_repo().confirm_invite_use(event["userName"])
    return event
