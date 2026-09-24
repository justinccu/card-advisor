from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_iam as iam
from constructs import Construct

GITHUB_OIDC_URL = "https://token.actions.githubusercontent.com"


class CiStack(Stack):
    """Lets GitHub Actions deploy via short-lived OIDC credentials — no stored access keys."""

    def __init__(self, scope: Construct, construct_id: str, *, github_repo: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        provider = iam.OpenIdConnectProvider(
            self,
            "GitHubOidc",
            url=GITHUB_OIDC_URL,
            client_ids=["sts.amazonaws.com"],
        )

        # Only workflows running on main may assume the deploy role; PRs get no AWS access
        # until we add a read-only role for eval runs in S8.
        deploy_role = iam.Role(
            self,
            "GitHubDeployRole",
            role_name="card-advisor-github-deploy",
            assumed_by=iam.WebIdentityPrincipal(
                provider.open_id_connect_provider_arn,
                conditions={
                    "StringEquals": {
                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                        "token.actions.githubusercontent.com:sub": (
                            f"repo:{github_repo}:ref:refs/heads/main"
                        ),
                    }
                },
            ),
        )

        # CDK deploys by assuming the bootstrap roles, so that is the only permission needed;
        # what can actually be deployed is bounded by the bootstrap roles themselves.
        deploy_role.add_to_policy(
            iam.PolicyStatement(
                actions=["sts:AssumeRole"],
                resources=[f"arn:aws:iam::{self.account}:role/cdk-hnb659fds-*"],
            )
        )

        CfnOutput(self, "DeployRoleArn", value=deploy_role.role_arn)
