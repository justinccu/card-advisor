export function Footer({ generatedAt, version }: { generatedAt: string; version: number }) {
  const date = new Date(generatedAt).toLocaleDateString("en-US", { dateStyle: "medium" });
  return (
    <footer className="mt-24 border-t border-hairline bg-tile/60">
      <div className="mx-auto max-w-[1024px] space-y-3 px-4 py-8 text-[12px] leading-relaxed text-ink-2">
        <p>
          <strong className="font-semibold text-ink">Not financial advice.</strong> Card Advisor takes no
          payments from issuers and uses no affiliate links; rankings depend only on your situation.
          Always confirm terms on the issuer&apos;s site before applying.
        </p>
        <p>
          Offers change often. Every figure links to its source and is human-reviewed before
          publishing. Eligibility rules marked &ldquo;community&rdquo; are inferred from applicant data
          points, not issuer policy.
        </p>
        <p className="text-ink-3">
          Catalog {version === 0 ? "preview" : `v${version}`} · updated {date}
        </p>
      </div>
    </footer>
  );
}
