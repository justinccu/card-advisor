import json

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
    assert props["Budget"]["CostTypes"]["IncludeCredit"] is False  # alert on gross usage
    thresholds = {
        (n["Notification"]["NotificationType"], n["Notification"]["Threshold"])
        for n in props["NotificationsWithSubscribers"]
    }
    assert ("ACTUAL", 50) in thresholds
    assert ("FORECASTED", 100) in thresholds


def test_deploy_role_is_restricted_to_main_branch():
    stack = CiStack(cdk.App(), "ci", env=ENV, github_subject_prefix="repo:owner@1/repo@2")
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
                                                "repo:owner@1/repo@2:ref:refs/heads/main"
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


# --- S4: data, auth, api ------------------------------------------------------------------


def _s4(advisor_memory_id=None):
    """All S4 stacks wired like app.py, with an inline stand-in for the Lambda bundle."""
    from aws_cdk import aws_lambda as lambda_
    from stacks.api_stack import ApiStack
    from stacks.auth_stack import AuthStack
    from stacks.data_stack import DataStack

    app = cdk.App(context={"@aws-cdk/core:defaultCrossStackReferences": "strong"})
    ops = OpsStack(app, "ops", env=ENV, alert_email="a@example.com", monthly_budget_usd=50)
    data = DataStack(app, "data", env=ENV, alerts=ops.alerts)

    def code():
        return lambda_.Code.from_inline("def handler(event, context): return event")

    auth = AuthStack(app, "auth", env=ENV, table=data.table, code=code())
    api = ApiStack(
        app,
        "api",
        env=ENV,
        project="card-advisor",
        table=data.table,
        catalog_bucket=data.catalog_bucket,
        auth=auth,
        code=code(),
        cors_origins=["http://localhost:3000"],
        alerts=ops.alerts,
        advisor_memory_id=advisor_memory_id,
    )
    return (Template.from_stack(s) for s in (data, auth, api))


def _one(template, kind):
    [resource] = template.find_resources(kind).values()
    return resource


def test_user_data_survives_mistakes():
    data, _, _ = _s4()
    table = _one(data, "AWS::DynamoDB::GlobalTable")
    assert table["DeletionPolicy"] == "Retain"
    props = table["Properties"]
    assert props["BillingMode"] == "PAY_PER_REQUEST"
    assert props["TimeToLiveSpecification"] == {"AttributeName": "expires_at", "Enabled": True}
    [replica] = props["Replicas"]
    assert replica["DeletionProtectionEnabled"] is True
    assert replica["PointInTimeRecoverySpecification"]["PointInTimeRecoveryEnabled"] is True


def test_catalog_bucket_is_private_versioned_and_kept():
    data, _, _ = _s4()
    bucket = _one(data, "AWS::S3::Bucket")
    assert bucket["DeletionPolicy"] == "Retain"
    assert bucket["Properties"]["VersioningConfiguration"] == {"Status": "Enabled"}
    assert all(bucket["Properties"]["PublicAccessBlockConfiguration"].values())
    policy = json.dumps(_one(data, "AWS::S3::BucketPolicy"))
    assert '"aws:SecureTransport": "false"' in policy  # HTTPS only


def test_sign_up_is_invite_gated_and_tokens_are_short_lived():
    _, auth, _ = _s4()
    pool = _one(auth, "AWS::Cognito::UserPool")
    assert pool["DeletionPolicy"] == "Retain"
    props = pool["Properties"]
    assert props["UsernameAttributes"] == ["email"]
    assert props["Policies"]["PasswordPolicy"]["MinimumLength"] >= 12
    assert set(props["LambdaConfig"]) == {"PreSignUp", "PostConfirmation"}

    client = _one(auth, "AWS::Cognito::UserPoolClient")["Properties"]
    assert client["GenerateSecret"] is False
    assert client["AccessTokenValidity"] == 30 and client["TokenValidityUnits"]["AccessToken"] == (
        "minutes"
    )
    assert client["EnableTokenRevocation"] is True
    assert _one(auth, "AWS::Cognito::UserPoolGroup")["Properties"]["GroupName"] == "admin"

    handlers = {
        f["Properties"]["Handler"]: f["Properties"]["Timeout"]
        for f in auth.find_resources("AWS::Lambda::Function").values()
    }
    assert handlers == {
        "card_api.triggers.presignup_handler": 5,  # Cognito's own trigger limit
        "card_api.triggers.postconfirm_handler": 5,
    }


def test_every_route_but_health_and_catalog_needs_a_jwt():
    _, _, api = _s4()
    routes = {
        r["Properties"]["RouteKey"]: r["Properties"].get("AuthorizationType", "NONE")
        for r in api.find_resources("AWS::ApiGatewayV2::Route").values()
    }
    assert routes["GET /health"] == "NONE" and routes["GET /catalog"] == "NONE"
    private = {k: v for k, v in routes.items() if k.endswith("/{proxy+}")}
    assert set(private) == {f"{m} /{{proxy+}}" for m in ("GET", "POST", "PUT", "PATCH", "DELETE")}
    assert set(private.values()) == {"JWT"}
    assert not any(k.startswith("ANY ") or k.startswith("OPTIONS ") for k in routes)


def test_cors_and_throttling_are_set_at_the_edge():
    _, _, api = _s4()
    cors = _one(api, "AWS::ApiGatewayV2::Api")["Properties"]["CorsConfiguration"]
    assert cors["AllowOrigins"] == ["http://localhost:3000"]
    assert cors["ExposeHeaders"] == ["X-Catalog-Version"]
    stage = _one(api, "AWS::ApiGatewayV2::Stage")["Properties"]
    assert stage["DefaultRouteSettings"]["ThrottlingRateLimit"] == 20
    assert "$context.status" in stage["AccessLogSettings"]["Format"]


def test_api_lambda_has_least_privilege():
    _, _, api = _s4()
    statements = _one(api, "AWS::IAM::Policy")["Properties"]["PolicyDocument"]["Statement"]
    actions = {a for s in statements for a in _list(s["Action"])}
    assert not any(a.endswith(":*") or a == "*" for a in actions)
    assert "dynamodb:DeleteTable" not in actions and "s3:PutObject" not in actions
    s3_resources = json.dumps([s["Resource"] for s in statements if "s3:GetObject*" in s["Action"]])
    assert "catalog/us/*" in s3_resources  # read-only, published snapshots only
    fn = _one(api, "AWS::Lambda::Function")["Properties"]
    assert fn["Architectures"] == ["arm64"] and fn["Runtime"] == "python3.13"
    assert fn["Environment"]["Variables"]["APP_ENV"] == "aws"  # no dev sign-in on AWS


def test_account_deletion_can_only_list_and_delete_one_advisor_memory():
    _, _, api = _s4()
    policy = json.dumps(_one(api, "AWS::IAM::Policy"))
    assert "bedrock-agentcore" not in policy  # no Memory deployed yet: no permission at all

    _, _, api = _s4(advisor_memory_id="AdvisorMemory-abc123")
    statements = _one(api, "AWS::IAM::Policy")["Properties"]["PolicyDocument"]["Statement"]
    [memory] = [s for s in statements if "bedrock-agentcore" in json.dumps(s["Action"])]
    assert all(
        a.split(":")[1].startswith(("List", "BatchDelete", "Delete")) for a in memory["Action"]
    )
    assert "memory/AdvisorMemory-abc123" in json.dumps(memory["Resource"])
    fn = _one(api, "AWS::Lambda::Function")["Properties"]
    assert fn["Environment"]["Variables"]["ADVISOR_MEMORY_ID"] == "AdvisorMemory-abc123"


def test_alarms_page_the_ops_topic_and_values_are_shared_via_ssm():
    data, _, api = _s4()
    alarms = [*data.find_resources("AWS::CloudWatch::Alarm").values()]
    alarms += [*api.find_resources("AWS::CloudWatch::Alarm").values()]
    assert len(alarms) == 3 and all(a["Properties"]["AlarmActions"] for a in alarms)
    names = {p["Properties"]["Name"] for p in api.find_resources("AWS::SSM::Parameter").values()}
    assert "/card-advisor/cognito-discovery-url" in names and "/card-advisor/api-url" in names


def _list(x):
    return x if isinstance(x, list) else [x]


def _web(site_dir=None):
    from stacks.web_stack import WebStack

    app = cdk.App()
    return Template.from_stack(
        WebStack(app, "web", env=ENV, project="card-advisor", site_dir=site_dir)
    )


def test_site_bucket_is_private_and_only_cloudfront_reads_it():
    web = _web()
    bucket = _one(web, "AWS::S3::Bucket")["Properties"]
    assert all(bucket["PublicAccessBlockConfiguration"].values())
    policy = json.dumps(web.find_resources("AWS::S3::BucketPolicy"))
    assert "cloudfront.amazonaws.com" in policy and "AWS:SourceArn" in policy  # OAC
    web.resource_count_is("AWS::CloudFront::OriginAccessControl", 1)


def test_site_is_https_only_with_security_headers_and_a_404_page():
    web = _web()
    dist = _one(web, "AWS::CloudFront::Distribution")["Properties"]["DistributionConfig"]
    assert dist["DefaultCacheBehavior"]["ViewerProtocolPolicy"] == "redirect-to-https"
    assert {
        (e["ErrorCode"], e["ResponseCode"], e["ResponsePagePath"])
        for e in dist["CustomErrorResponses"]
    } == {
        (403, 404, "/404.html"),
        (404, 404, "/404.html"),
    }
    headers = _one(web, "AWS::CloudFront::ResponseHeadersPolicy")["Properties"]
    security = headers["ResponseHeadersPolicyConfig"]["SecurityHeadersConfig"]
    csp = security["ContentSecurityPolicy"]["ContentSecurityPolicy"]
    assert "frame-ancestors 'none'" in csp and "bedrock-agentcore.us-east-2" in csp
    assert security["FrameOptions"]["FrameOption"] == "DENY"
    assert security["StrictTransportSecurity"]["AccessControlMaxAgeSec"] == 31536000


def test_site_files_are_published_only_from_a_ci_build():
    no_content = _web()
    assert not no_content.find_resources("Custom::CDKBucketDeployment")
    import tempfile
    from pathlib import Path

    out = Path(tempfile.mkdtemp())
    (out / "index.html").write_text("<html></html>")
    deployments = _web(site_dir=str(out)).find_resources("Custom::CDKBucketDeployment")
    assert len(deployments) == 2  # hashed assets, then pages + cache invalidation
    pages = [d for d in deployments.values() if "DistributionId" in d["Properties"]]
    assert len(pages) == 1 and pages[0]["Properties"]["DistributionPaths"] == ["/*"]
