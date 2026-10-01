#!/usr/bin/env bash
# Put the public site on our own domain: `make site-domain DOMAIN=example.com`.
# Requests (once) a free ACM certificate in us-east-1, where CloudFront reads them, then prints
# the two DNS records to add at the registrar and, once the certificate is issued, the
# cdk.json lines that attach the name to the distribution (the next CI deploy applies them).
# Run again to check progress. Idempotent; the only thing it creates is the certificate.
set -euo pipefail
domain=${1:?usage: site_domain.sh DOMAIN}
cert_region=us-east-1

arn=$(aws acm list-certificates --region "$cert_region" \
  --certificate-statuses PENDING_VALIDATION ISSUED \
  --query "CertificateSummaryList[?DomainName=='${domain}'].CertificateArn | [0]" --output text)
if [ "$arn" = "None" ] || [ -z "$arn" ]; then
  arn=$(aws acm request-certificate --region "$cert_region" --domain-name "$domain" \
    --validation-method DNS --tags Key=project,Value=card-advisor \
    --query CertificateArn --output text)
  echo "Requested a certificate for $domain"
  sleep 5 # ACM fills in the validation record a few seconds after the request
fi

read -r status name value < <(aws acm describe-certificate --region "$cert_region" \
  --certificate-arn "$arn" --output text --query \
  'Certificate.[Status, DomainValidationOptions[0].ResourceRecord.Name, DomainValidationOptions[0].ResourceRecord.Value]')

# The distribution's own name: CloudFrontUrl once a domain is attached, SiteUrl before that.
output() {
  aws cloudformation describe-stacks --region us-east-2 --stack-name card-advisor-web \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue | [0]" --output text
}
target=$(output CloudFrontUrl)
[ "$target" = "None" ] && target=$(output SiteUrl)
target=${target#https://}

cat <<INFO

Certificate: $status
  $arn

DNS records to add at the registrar (DNS only, no proxy):
  1. CNAME  $name  ->  $value
     Proves we own the name. Keep it: renewals use it.
  2. CNAME  $domain  ->  $target
     The site. For a bare domain (no www.) use the registrar's CNAME flattening / ALIAS record.
INFO

if [ "$status" = "ISSUED" ]; then
  cat <<INFO

Certificate issued. Add to "context" in infra/cdk.json, then commit and push (CI deploys):
    "site_domain": "$domain",
    "site_certificate_arn": "$arn",
INFO
else
  echo
  echo "Waiting for record 1 (usually minutes after it is added). Run this again to check."
fi
