import { CardStyleToggle } from "./CardStyleToggle";

export function Footer({
  generatedAt,
  version,
  preview,
}: {
  generatedAt: string;
  version: string;
  preview: boolean;
}) {
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
        <p>
          Card names and designs are trademarks of their respective issuers and card networks, shown
          only to identify each card. Card Advisor is not affiliated with or endorsed by any issuer.
        </p>
        <CardStyleToggle />
        <p className="text-ink-3">
          Catalog {preview ? "preview" : `v${version}`} · updated {date}
        </p>
      </div>
    </footer>
  );
}
