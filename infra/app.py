import os

import aws_cdk as cdk
from stacks.ci_stack import CiStack
from stacks.ops_stack import OpsStack

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

OpsStack(
    app,
    f"{project}-ops",
    env=env,
    alert_email=alert_email,
    monthly_budget_usd=float(app.node.get_context("monthly_budget_usd")),
)
CiStack(app, f"{project}-ci", env=env, github_repo=app.node.get_context("github_repo"))

cdk.Tags.of(app).add("project", project)
app.synth()
