import os
from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_lambda as lambda_
from stacks.api_stack import ApiStack
from stacks.auth_stack import AuthStack
from stacks.ci_stack import CiStack
from stacks.data_stack import DataStack
from stacks.ops_stack import OpsStack
from stacks.web_stack import WebStack

LAMBDA_BUNDLE = Path(__file__).parent / "build" / "api"

app = cdk.App()

project = app.node.get_context("project")
env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=app.node.get_context("region"),
)

# Kept out of the repo: set ALERT_EMAIL in .env (loaded by the Makefile).
alert_email = os.environ.get("ALERT_EMAIL")
if not alert_email:
    raise ValueError("Set ALERT_EMAIL in .env (see README: Development)")

ops = OpsStack(
    app,
    f"{project}-ops",
    env=env,
    alert_email=alert_email,
    monthly_budget_usd=float(app.node.get_context("monthly_budget_usd")),
)
CiStack(
    app,
    f"{project}-ci",
    env=env,
    # `gh api repos/OWNER/REPO/actions/oidc/customization/sub` -> sub_claim_prefix
    github_subject_prefix=app.node.get_context("github_oidc_subject_prefix"),
)

# S4: user data, sign-up, API. The Lambda package is built by scripts/bundle_lambda.sh.
if not LAMBDA_BUNDLE.is_dir():
    raise ValueError(f"Missing {LAMBDA_BUNDLE}: run `make lambda-bundle` first")


def code() -> lambda_.Code:
    # One Code object per stack (CDK rule); same content hash, so the asset uploads once.
    return lambda_.Code.from_asset(str(LAMBDA_BUNDLE))


data = DataStack(app, f"{project}-data", env=env, alerts=ops.alerts)
auth = AuthStack(app, f"{project}-auth", env=env, table=data.table, code=code())
ApiStack(
    app,
    f"{project}-api",
    env=env,
    project=project,
    table=data.table,
    catalog_bucket=data.catalog_bucket,
    auth=auth,
    code=code(),
    cors_origins=app.node.get_context("cors_origins"),
    alerts=ops.alerts,
    # Set after `agentcore deploy` creates the Advisor's Memory (ADR 0009); empty until then.
    advisor_memory_id=app.node.try_get_context("advisor_memory_id") or None,
)

# S5: the public site. CI builds web/out against the live API, then deploys with
# `-c site_dir=../web/out`; without it the site's files are left as they are.
WebStack(
    app,
    f"{project}-web",
    env=env,
    project=project,
    site_dir=app.node.try_get_context("site_dir"),
)

cdk.Tags.of(app).add("project", project)
app.synth()
