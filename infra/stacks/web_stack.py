from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from aws_cdk import aws_ssm as ssm
from constructs import Construct

REGION = "us-east-2"

# The static site talks only to our API, Cognito (SRP sign-in) and the Advisor runtime. Next's
# static export inlines its bootstrap scripts, hence 'unsafe-inline' for scripts; Motion sets
# inline styles. scripts/check_site_headers.py loads every page under this policy.
CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        "font-src 'self' data:",
        "connect-src 'self'"
        f" https://*.execute-api.{REGION}.amazonaws.com"
        f" https://cognito-idp.{REGION}.amazonaws.com"
        f" https://bedrock-agentcore.{REGION}.amazonaws.com",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "object-src 'none'",
    ]
)

# The export is one folder per route (trailingSlash): /cards/ -> /cards/index.html. A path
# without an extension gets the trailing slash, so each page has one URL.
URL_REWRITE = """
function handler(event) {
  var request = event.request;
  var uri = request.uri;
  if (uri.endsWith('/')) {
    request.uri = uri + 'index.html';
    return request;
  }
  if (uri.lastIndexOf('.') < uri.lastIndexOf('/')) {
    return {
      statusCode: 301,
      statusDescription: 'Moved Permanently',
      headers: { location: { value: uri + '/' } },
    };
  }
  return request;
}
"""

# Next puts content-hashed files under _next/static: a new build gets new names, so they can be
# cached for a year. Everything else (the HTML) is revalidated on each visit.
HASHED = "_next/static/*"


class WebStack(Stack):
    """S5: the static site (web/out) in a private bucket behind CloudFront.

    `site_dir` is the built site; CI passes it (`-c site_dir=../web/out`) after building against
    the live API. Without it the stack keeps the bucket and distribution and leaves the files
    as they are, so a deploy from a laptop never publishes an unbuilt or local-mode site.

    `domain` (with `certificate_arn`, an issued ACM certificate in us-east-1, where CloudFront
    looks for them) serves the site on our own name; the DNS stays with the registrar, which
    points the name at the distribution (`make site-domain`)."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        project: str,
        site_dir: str | None,
        domain: str | None = None,
        certificate_arn: str | None = None,
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)
        if bool(domain) != bool(certificate_arn):
            raise ValueError("Set both site_domain and site_certificate_arn, or neither")

        bucket = s3.Bucket(
            self,
            "SiteBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            # Rebuilt from the repo on every deploy: nothing here needs keeping.
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        headers = cloudfront.ResponseHeadersPolicy(
            self,
            "SecurityHeaders",
            security_headers_behavior=cloudfront.ResponseSecurityHeadersBehavior(
                content_security_policy=cloudfront.ResponseHeadersContentSecurityPolicy(
                    content_security_policy=CSP, override=True
                ),
                strict_transport_security=cloudfront.ResponseHeadersStrictTransportSecurity(
                    access_control_max_age=Duration.days(365),
                    include_subdomains=True,
                    override=True,
                ),
                content_type_options=cloudfront.ResponseHeadersContentTypeOptions(override=True),
                frame_options=cloudfront.ResponseHeadersFrameOptions(
                    frame_option=cloudfront.HeadersFrameOption.DENY, override=True
                ),
                referrer_policy=cloudfront.ResponseHeadersReferrerPolicy(
                    referrer_policy=cloudfront.HeadersReferrerPolicy.STRICT_ORIGIN_WHEN_CROSS_ORIGIN,
                    override=True,
                ),
            ),
        )

        self.distribution = cloudfront.Distribution(
            self,
            "Site",
            comment=f"{project} site",
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                # Origin access control: only this distribution can read the bucket.
                origin=origins.S3BucketOrigin.with_origin_access_control(bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                response_headers_policy=headers,
                compress=True,
                function_associations=[
                    cloudfront.FunctionAssociation(
                        function=cloudfront.Function(
                            self,
                            "UrlRewrite",
                            code=cloudfront.FunctionCode.from_inline(URL_REWRITE),
                            runtime=cloudfront.FunctionRuntime.JS_2_0,
                        ),
                        event_type=cloudfront.FunctionEventType.VIEWER_REQUEST,
                    )
                ],
            ),
            # Without list permission S3 answers 403 for a missing file: both are "not found".
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=status,
                    response_http_status=404,
                    response_page_path="/404.html",
                    ttl=Duration.minutes(5),
                )
                for status in (403, 404)
            ],
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,  # North America + Europe edges
            http_version=cloudfront.HttpVersion.HTTP2_AND_3,
            domain_names=[domain] if domain else None,
            certificate=(
                acm.Certificate.from_certificate_arn(self, "SiteCertificate", certificate_arn)
                if certificate_arn
                else None
            ),
        )

        if site_dir:
            # Hashed assets first (kept across deploys, so a page loaded just before a deploy
            # still finds its files), then the HTML, which prunes old pages and invalidates the
            # cache so visitors get the new build.
            assets = s3deploy.BucketDeployment(
                self,
                "DeployAssets",
                sources=[s3deploy.Source.asset(site_dir)],
                destination_bucket=bucket,
                exclude=["*"],
                include=[HASHED],
                cache_control=[
                    s3deploy.CacheControl.from_string("public, max-age=31536000, immutable")
                ],
                prune=False,
                memory_limit=512,
            )
            pages = s3deploy.BucketDeployment(
                self,
                "DeployPages",
                sources=[s3deploy.Source.asset(site_dir)],
                destination_bucket=bucket,
                exclude=[HASHED],
                cache_control=[
                    s3deploy.CacheControl.from_string("public, max-age=0, must-revalidate")
                ],
                distribution=self.distribution,
                distribution_paths=["/*"],
                memory_limit=512,
            )
            pages.node.add_dependency(assets)

        cloudfront_url = f"https://{self.distribution.distribution_domain_name}"
        self.site_url = f"https://{domain}" if domain else cloudfront_url
        ssm.StringParameter(
            self, "SiteUrlParam", parameter_name=f"/{project}/site-url", string_value=self.site_url
        )
        CfnOutput(self, "SiteUrl", value=self.site_url)
        # Where the registrar's DNS record for the domain points.
        CfnOutput(self, "CloudFrontUrl", value=cloudfront_url)
        CfnOutput(self, "DistributionId", value=self.distribution.distribution_id)
