"""Guest accounts for the Advisor trial (ADR 0009, temporary).

A visitor who isn't signed in gets a throwaway Cognito account, so the Advisor Runtime, which
accepts only our Cognito tokens, needs no second way in, and every limit keyed by user (the
10-message trial, the 7-day turn records, Memory) works unchanged. The account is in the
"guest" group, which the API reads from the token: guests can chat and rate answers, nothing
else. Its password is random and never leaves this function; the site keeps the session going
with the refresh token (30 days), after which the guest is simply gone.
"""

import secrets

GUEST_GROUP = "guest"
EMAIL_DOMAIN = "guest.invalid"  # reserved: never a real mailbox, and no mail is sent


def create(idp, pool_id: str, client_id: str) -> dict:
    email = f"guest-{secrets.token_hex(8)}@{EMAIL_DOMAIN}"
    password = secrets.token_urlsafe(24) + "Aa1"  # meets the pool's policy either way
    idp.admin_create_user(
        UserPoolId=pool_id,
        Username=email,
        MessageAction="SUPPRESS",
        UserAttributes=[
            {"Name": "email", "Value": email},
            {"Name": "email_verified", "Value": "true"},
        ],
    )
    idp.admin_set_user_password(
        UserPoolId=pool_id, Username=email, Password=password, Permanent=True
    )
    idp.admin_add_user_to_group(UserPoolId=pool_id, Username=email, GroupName=GUEST_GROUP)
    tokens = idp.admin_initiate_auth(
        UserPoolId=pool_id,
        ClientId=client_id,
        AuthFlow="ADMIN_USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": email, "PASSWORD": password},
    )["AuthenticationResult"]
    return {
        "access_token": tokens["AccessToken"],
        "refresh_token": tokens["RefreshToken"],
        "expires_in": tokens["ExpiresIn"],
    }
