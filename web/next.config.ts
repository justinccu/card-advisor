import type { NextConfig } from "next";

// Static export (ADR 0003): catalog pages are rendered at build time from a Catalog Snapshot
// and served from S3 + CloudFront; the Wallet talks to the API from the browser.
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
};

export default nextConfig;
