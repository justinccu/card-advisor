from aws_cdk import Duration, RemovalPolicy, Stack
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sns as sns
from constructs import Construct


class DataStack(Stack):
    """User data (one DynamoDB table) and the Catalog Snapshot bucket (ADR 0003).

    Both outlive the stack (RETAIN + deletion protection): tearing down or renaming a stack must
    never take user wallets or published catalog versions with it.
    """

    def __init__(self, scope: Construct, construct_id: str, *, alerts: sns.ITopic, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        # Single-table layout: see packages/api/src/card_api/repository.py.
        self.table = ddb.TableV2(
            self,
            "Table",
            partition_key=ddb.Attribute(name="PK", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="SK", type=ddb.AttributeType.STRING),
            billing=ddb.Billing.on_demand(),  # pay per request: ~$0 while idle
            time_to_live_attribute="expires_at",  # daily chat quotas expire on their own
            point_in_time_recovery_specification=ddb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True  # restore to any second in the last 35 days
            ),
            deletion_protection=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Snapshots are immutable by convention (scout release never overwrites a version);
        # versioning also protects against a mistaken delete or overwrite outside that tool.
        self.catalog_bucket = s3.Bucket(
            self,
            "CatalogBucket",
            versioned=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            lifecycle_rules=[
                s3.LifecycleRule(noncurrent_version_expiration=Duration.days(90)),
            ],
            removal_policy=RemovalPolicy.RETAIN,
        )

        throttles = cw.MathExpression(
            expression="r + w",
            using_metrics={
                "r": self.table.metric("ReadThrottleEvents", statistic="Sum"),
                "w": self.table.metric("WriteThrottleEvents", statistic="Sum"),
            },
            period=Duration.minutes(5),
        )
        alarm = cw.Alarm(
            self,
            "TableThrottled",
            alarm_description="DynamoDB throttled requests: traffic spike or a hot key",
            metric=throttles,
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
        )
        alarm.add_alarm_action(cw_actions.SnsAction(alerts))
