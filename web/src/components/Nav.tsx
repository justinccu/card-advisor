"use client";

import { CreditCard } from "lucide-react";
import { motion } from "motion/react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { spring } from "@/lib/motion";

import { useSession } from "./Providers";

const LINKS = [
  { href: "/cards/", label: "Cards" },
  { href: "/compare/", label: "Compare" },
  { href: "/wallet/", label: "Wallet" },
];

export function Nav() {
  const path = usePathname();
  const { uid, ready } = useSession();
  return (
    <header className="glass sticky top-0 z-40 border-b border-hairline">
      <nav className="mx-auto flex h-12 max-w-[1024px] items-center justify-between px-4 text-[13px]">
        <Link href="/" className="flex items-center gap-1.5 whitespace-nowrap font-semibold tracking-tight" aria-label="Card Advisor home">
          <CreditCard size={18} strokeWidth={2.2} aria-hidden />
          <span className="hidden sm:inline">Card Advisor</span>
        </Link>
        <ul className="flex items-center gap-1">
          {LINKS.map((l) => {
            const active = path.startsWith(l.href.replace(/\/$/, ""));
            return (
              <li key={l.href} className="relative">
                <Link
                  href={l.href}
                  className={`relative z-10 block rounded-full px-3 py-1.5 transition-colors ${active ? "text-ink" : "text-ink-2 hover:text-ink"}`}
                >
                  {l.label}
                </Link>
                {active && (
                  <motion.span
                    layoutId="nav-pill"
                    transition={spring.nav}
                    className="absolute inset-0 rounded-full bg-black/[0.05] dark:bg-white/10"
                  />
                )}
              </li>
            );
          })}
        </ul>
        <Link
          href={uid ? "/profile/" : "/signin/"}
          className="min-w-14 whitespace-nowrap text-right text-link"
          aria-live="polite"
        >
          {!ready ? "" : uid ? "Profile" : "Sign in"}
        </Link>
      </nav>
    </header>
  );
}
