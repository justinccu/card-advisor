from aws_cdk import Stack
from aws_cdk import aws_budgets as budgets
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subs
from constructs import Construct


class OpsStack(Stack):
    """Cost guardrails and the shared alert topic every other stack publishes to."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        alert_email: str,
        monthly_budget_usd: float,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.alerts = sns.Topic(self, "Alerts", display_name="card-advisor alerts")
        self.alerts.add_subscription(subs.EmailSubscription(alert_email))

        # Account-wide on purpose: a forgotten NAT Gateway or runaway log group
        # won't carry the project tag, and those are the costs we most need to catch.
        thresholds = [
            ("ACTUAL", 50),
            ("ACTUAL", 80),
            ("FORECASTED", 100),
        ]
        budgets.CfnBudget(
            self,
            "MonthlyBudget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name="card-advisor-monthly",
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(amount=monthly_budget_usd, unit="USD"),
                # Track gross usage: with credits netted out, alerts stay silent while credits
                # quietly burn down, and the first warning would arrive after they're gone.
                cost_types=budgets.CfnBudget.CostTypesProperty(
                    include_credit=False, include_refund=False
                ),
            ),
            notifications_with_subscribers=[
                budgets.CfnBudget.NotificationWithSubscribersProperty(
                    notification=budgets.CfnBudget.NotificationProperty(
                        notification_type=kind,
                        comparison_operator="GREATER_THAN",
                        threshold=pct,
                        threshold_type="PERCENTAGE",
                    ),
                    subscribers=[
                        budgets.CfnBudget.SubscriberProperty(
                            subscription_type="EMAIL", address=alert_email
                        )
                    ],
                )
                for kind, pct in thresholds
            ],
        )
