from aws_cdk import Duration, RemovalPolicy, Stack
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from constructs import Construct

ADMIN_GROUP = "admin"


class AuthStack(Stack):
    """Invite-only sign-up with Cognito (ADR 0005).

    Sign-up is a public Cognito endpoint; the pre sign-up trigger takes one invite use (atomic,
    recorded per user) before the account exists, and the post confirmation trigger stamps the
    use once the email is verified. Identity reaches the API only as a verified JWT.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        table: ddb.ITableV2,
        code: lambda_.Code,
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)

        triggers = {
            name: lambda_.Function(
                self,
                f"{name}Trigger",
                runtime=lambda_.Runtime.PYTHON_3_13,
                architecture=lambda_.Architecture.ARM_64,
                code=code,
                handler=f"card_api.triggers.{handler}",
                # Cognito waits at most 5 s for a trigger; triggers.py imports no web framework.
                timeout=Duration.seconds(5),
                memory_size=256,
                environment={"APP_ENV": "aws", "TABLE_NAME": table.table_name},
                log_group=logs.LogGroup(
                    self,
                    f"{name}Logs",
                    retention=logs.RetentionDays.TWO_WEEKS,
                    removal_policy=RemovalPolicy.DESTROY,
                ),
            )
            for name, handler in [
                ("PreSignUp", "presignup_handler"),
                ("PostConfirmation", "postconfirm_handler"),
            ]
        }
        for fn in triggers.values():
            table.grant_read_write_data(fn)

        self.user_pool = cognito.UserPool(
            self,
            "UserPool",
            feature_plan=cognito.FeaturePlan.LITE,  # first 10,000 monthly active users free
            self_sign_up_enabled=True,  # gated by the pre sign-up trigger's invite check
            sign_in_aliases=cognito.SignInAliases(email=True),  # username = sub (a UUID)
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=True)
            ),
            password_policy=cognito.PasswordPolicy(
                min_length=12,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=False,
            ),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            lambda_triggers=cognito.UserPoolTriggers(
                pre_sign_up=triggers["PreSignUp"],
                post_confirmation=triggers["PostConfirmation"],
            ),
            deletion_protection=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # The site signs in from the browser: a public client (no secret) using SRP, so the
        # password never leaves the page. Short access tokens bound how long a disabled user's
        # token stays valid (the API's JWT authorizer checks signature and expiry, not
        # revocation); disabling a user also revokes their refresh tokens (global sign-out).
        self.web_client = self.user_pool.add_client(
            "WebClient",
            generate_secret=False,
            auth_flows=cognito.AuthFlow(user_srp=True),
            access_token_validity=Duration.minutes(30),
            id_token_validity=Duration.minutes(30),
            refresh_token_validity=Duration.days(30),
            enable_token_revocation=True,
            prevent_user_existence_errors=True,
        )

        cognito.CfnUserPoolGroup(
            self,
            "AdminGroup",
            user_pool_id=self.user_pool.user_pool_id,
            group_name=ADMIN_GROUP,
            description="Can create and list invite codes (the API checks cognito:groups)",
        )

    @property
    def issuer(self) -> str:
        return f"https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool.user_pool_id}"
