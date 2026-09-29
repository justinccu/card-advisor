from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_apigatewayv2_authorizers as authorizers
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sns as sns
from aws_cdk import aws_ssm as ssm
from constructs import Construct

from stacks.auth_stack import AuthStack

CATALOG_PREFIX = "catalog/us/"
# A generous ceiling for an invite-only beta; it caps what a runaway client (or an attacker
# with a valid token) can cost, since every request reaching Lambda is billed.
THROTTLE_RATE_PER_SECOND = 20
THROTTLE_BURST = 40


class ApiStack(Stack):
    """HTTP API -> one FastAPI Lambda. Identity is checked at the edge: the JWT authorizer
    rejects bad tokens before Lambda runs, and the app reads the verified claims only."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        project: str,
        table: ddb.ITableV2,
        catalog_bucket: s3.IBucket,
        auth: AuthStack,
        code: lambda_.Code,
        cors_origins: list[str],
        alerts: sns.ITopic,
        advisor_memory_id: str | None = None,
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)

        fn = lambda_.Function(
            self,
            "ApiFunction",
            runtime=lambda_.Runtime.PYTHON_3_13,
            architecture=lambda_.Architecture.ARM_64,  # ~20% cheaper per ms than x86
            code=code,
            handler="card_api.lambda_handler.handler",
            memory_size=512,  # more memory = more CPU = shorter cold starts for FastAPI
            timeout=Duration.seconds(10),
            environment={
                "APP_ENV": "aws",  # disables the local X-Dev-User sign-in
                "TABLE_NAME": table.table_name,
                "CATALOG_BUCKET": catalog_bucket.bucket_name,
                "CATALOG_PREFIX": CATALOG_PREFIX,
            },
            log_group=logs.LogGroup(
                self,
                "ApiLogs",
                retention=logs.RetentionDays.TWO_WEEKS,
                removal_policy=RemovalPolicy.DESTROY,
            ),
        )
        # Least privilege: this table's items, and read-only on published snapshots.
        table.grant_read_write_data(fn)
        catalog_bucket.grant_read(fn, f"{CATALOG_PREFIX}*")
        if advisor_memory_id:
            # Account deletion also deletes the user's Advisor memory (card_api.memory): list and
            # delete only, on this one Memory. Reading or writing conversations stays the agent's.
            fn.add_environment("ADVISOR_MEMORY_ID", advisor_memory_id)
            fn.add_to_role_policy(
                iam.PolicyStatement(
                    actions=[
                        "bedrock-agentcore:ListMemoryRecords",
                        "bedrock-agentcore:BatchDeleteMemoryRecords",
                        "bedrock-agentcore:ListSessions",
                        "bedrock-agentcore:ListEvents",
                        "bedrock-agentcore:DeleteEvent",
                    ],
                    resources=[
                        f"arn:aws:bedrock-agentcore:{self.region}:{self.account}"
                        f":memory/{advisor_memory_id}"
                    ],
                )
            )

        self.http_api = apigw.HttpApi(
            self,
            "HttpApi",
            api_name=f"{project}-api",
            create_default_stage=False,
            # API Gateway answers CORS preflights itself (before any authorizer) and replaces
            # the app's CORS headers, so this list is the one that counts.
            cors_preflight=apigw.CorsPreflightOptions(
                allow_origins=cors_origins,
                allow_methods=[
                    apigw.CorsHttpMethod.GET,
                    apigw.CorsHttpMethod.POST,
                    apigw.CorsHttpMethod.PUT,
                    apigw.CorsHttpMethod.PATCH,
                    apigw.CorsHttpMethod.DELETE,
                ],
                allow_headers=["Authorization", "Content-Type"],
                expose_headers=["X-Catalog-Version"],
                max_age=Duration.hours(1),
            ),
        )
        access_logs = logs.LogGroup(
            self,
            "AccessLogs",
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=RemovalPolicy.DESTROY,
        )
        stage = self.http_api.add_stage(
            "DefaultStage",
            stage_name="$default",
            auto_deploy=True,
            throttle=apigw.ThrottleSettings(
                rate_limit=THROTTLE_RATE_PER_SECOND, burst_limit=THROTTLE_BURST
            ),
        )
        stage.node.default_child.access_log_settings = apigw.CfnStage.AccessLogSettingsProperty(
            destination_arn=access_logs.log_group_arn,
            format=(
                '{"requestId":"$context.requestId","ip":"$context.identity.sourceIp",'
                '"route":"$context.routeKey","status":"$context.status",'
                '"latencyMs":"$context.responseLatency",'
                '"authError":"$context.authorizer.error"}'
            ),
        )

        integration = integrations.HttpLambdaIntegration("Api", fn)
        jwt = authorizers.HttpJwtAuthorizer(
            "Cognito",
            jwt_issuer=auth.issuer,
            # Cognito access tokens carry client_id rather than aud; API Gateway checks either.
            jwt_audience=[auth.web_client.user_pool_client_id],
        )
        # Public: health and the catalog (the site is public too).
        for path in ("/health", "/catalog"):
            self.http_api.add_routes(
                path=path, methods=[apigw.HttpMethod.GET], integration=integration
            )
        # Everything else needs a valid token. Explicit methods (no ANY) so preflight OPTIONS
        # never reaches the authorizer.
        self.http_api.add_routes(
            path="/{proxy+}",
            methods=[
                apigw.HttpMethod.GET,
                apigw.HttpMethod.POST,
                apigw.HttpMethod.PUT,
                apigw.HttpMethod.PATCH,
                apigw.HttpMethod.DELETE,
            ],
            integration=integration,
            authorizer=jwt,
        )

        # --- Alarms -> the ops alert topic (email) ----------------------------------------
        def alarm(name: str, description: str, metric: cw.IMetric, threshold: float) -> None:
            a = cw.Alarm(
                self,
                name,
                alarm_description=description,
                metric=metric,
                threshold=threshold,
                evaluation_periods=1,
                comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            )
            a.add_alarm_action(cw_actions.SnsAction(alerts))

        alarm(
            "ApiErrors",
            "API Lambda errors (unhandled exceptions or timeouts)",
            fn.metric_errors(period=Duration.minutes(5), statistic="Sum"),
            5,
        )
        unauthorized = logs.MetricFilter(
            self,
            "Unauthorized",
            log_group=access_logs,
            filter_pattern=logs.FilterPattern.string_value("$.status", "=", "401"),
            metric_namespace=project,
            metric_name="Unauthorized",
            metric_value="1",
            default_value=0,
        )
        alarm(
            "UnauthorizedSpike",
            "Many 401s: someone probing the API with bad or expired tokens",
            unauthorized.metric(period=Duration.minutes(5), statistic="Sum"),
            50,
        )

        # --- Wiring for the other tools (ADR 0006: agentcore CLI reads these) --------------
        values = {
            "api-url": self.http_api.api_endpoint,
            "user-pool-id": auth.user_pool.user_pool_id,
            "web-client-id": auth.web_client.user_pool_client_id,
            "cognito-discovery-url": f"{auth.issuer}/.well-known/openid-configuration",
            "table-name": table.table_name,
            "catalog-bucket": catalog_bucket.bucket_name,
        }
        for key, value in values.items():
            ssm.StringParameter(
                self, f"Param-{key}", parameter_name=f"/{project}/{key}", string_value=value
            )
        CfnOutput(self, "ApiUrl", value=self.http_api.api_endpoint)
        CfnOutput(self, "UserPoolId", value=auth.user_pool.user_pool_id)
        CfnOutput(self, "WebClientId", value=auth.web_client.user_pool_client_id)
        CfnOutput(self, "CatalogBucket", value=catalog_bucket.bucket_name)
