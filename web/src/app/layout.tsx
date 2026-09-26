import type { Metadata, Viewport } from "next";

import { Footer } from "@/components/Footer";
import { Nav } from "@/components/Nav";
import { PreviewBanner } from "@/components/PreviewBanner";
import { Providers } from "@/components/Providers";
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
  return (
    <html lang="en">
      <body className="min-h-dvh">
        <Providers>
          <Nav />
          {catalog.preview && <PreviewBanner />}
          <main>{children}</main>
          <Footer generatedAt={catalog.generated_at} version={catalog.version} />
        </Providers>
      </body>
    </html>
  );
}
