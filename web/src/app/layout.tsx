import type { Metadata, Viewport } from "next";

import { AdvisorLauncher } from "@/components/AdvisorLauncher";
import { AdvisorProvider } from "@/components/AdvisorProvider";
import { Footer } from "@/components/Footer";
import { Nav } from "@/components/Nav";
import { PreviewBanner } from "@/components/PreviewBanner";
import { Providers } from "@/components/Providers";
import type { AdvisorCard } from "@/lib/advisor";
import { getCatalog } from "@/lib/catalog";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Card Advisor — Find the card that fits your life", template: "%s · Card Advisor" },
  description:
    "Compare US credit cards by welcome offer, annual fee and rewards, and see which ones you can actually get. No affiliate links. Not financial advice.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fbfbfd" },
    { media: "(prefers-color-scheme: dark)", color: "#000000" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  const catalog = getCatalog();
  // The Advisor links cards as `card:<id>`; the chat resolves them to these official pages only.
  const advisorCards: AdvisorCard[] = catalog.cards.map((c) => ({
    id: c.id,
    issuer_id: c.issuer_id,
    name: c.name,
    url: c.url,
    annual_fee_usd: c.annual_fee_usd,
    first_year_annual_fee_usd: c.first_year_annual_fee_usd,
    offer: c.offer,
  }));
  return (
    <html lang="en">
      <body className="min-h-dvh">
        <Providers catalogVersion={catalog.preview ? null : catalog.version}>
          <AdvisorProvider cards={advisorCards}>
            <Nav />
            {catalog.preview && <PreviewBanner />}
            <main>{children}</main>
            <Footer generatedAt={catalog.generated_at} version={catalog.version} preview={catalog.preview} />
            <AdvisorLauncher />
          </AdvisorProvider>
        </Providers>
      </body>
    </html>
  );
}
