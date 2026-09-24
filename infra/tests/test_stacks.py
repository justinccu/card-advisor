import aws_cdk as cdk
from aws_cdk.assertions import Match, Template
from stacks.ci_stack import CiStack
from stacks.ops_stack import OpsStack

ENV = cdk.Environment(account="123456789012", region="us-east-1")


def test_budget_alerts_before_limit_is_hit():
    stack = OpsStack(cdk.App(), "ops", env=ENV, alert_email="a@example.com", monthly_budget_usd=50)
    budget = Template.from_stack(stack).find_resources("AWS::Budgets::Budget")
    props = next(iter(budget.values()))["Properties"]

    assert props["Budget"]["BudgetLimit"] == {"Amount": 50, "Unit": "USD"}
    thresholds = {
        (n["Notification"]["NotificationType"], n["Notification"]["Threshold"])
        for n in props["NotificationsWithSubscribers"]
    }
    assert ("ACTUAL", 50) in thresholds
    assert ("FORECASTED", 100) in thresholds


def test_deploy_role_is_restricted_to_main_branch():
    stack = CiStack(cdk.App(), "ci", env=ENV, github_repo="owner/repo")
    Template.from_stack(stack).has_resource_properties(
        "AWS::IAM::Role",
        {
            "AssumeRolePolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Condition": {
                                    "StringEquals": Match.object_like(
                                        {
                                            "token.actions.githubusercontent.com:sub": (
                                                "repo:owner/repo:ref:refs/heads/main"
                                            )
                                        }
                                    )
                                }
                            }
                        )
                    ]
                )
            }
        },
    )
