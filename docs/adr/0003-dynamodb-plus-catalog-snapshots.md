# DynamoDB for user data, versioned S3 snapshots for the catalog — no relational database

The catalog is small (tens to hundreds of Card Products) and changes a few times a week, so it is published as an immutable Catalog Snapshot to S3, read at build time by the static site and loaded in memory by the rules engine; filtering and comparison never need SQL. User data (Wallets, Proposed Changes, invites) is key-access and lives in DynamoDB. Postgres on RDS was rejected because Lambda-in-VPC requires a NAT Gateway (~$32+/month) and an always-on instance; Aurora Serverless v2 has a ~$44/month floor.

## Considered Options

- **Aurora DSQL** — the closest alternative (serverless, no VPC, SQL). Rejected for now: no TTL (needed for quota counters), no change streams (needed to trigger republish on approval), no foreign keys anyway. Revisit if relational/analytical query needs emerge.
- **RDS Postgres / Aurora Serverless v2** — VPC + NAT or a ~$44/month floor; connection exhaustion under Lambda concurrency.
- **Neon / Supabase** — outside AWS; IAM and observability would need separate handling.

Ad-hoc analytics are served by DynamoDB export to S3 + Athena, on demand.
