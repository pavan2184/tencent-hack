import type { Metadata } from "next";
import { Inter_Tight } from "next/font/google";
import Link from "next/link";
import type { ReactNode } from "react";
import { NavLinks } from "@/components/NavLinks";
import { PersonaBoundary, PersonaProvider } from "@/components/PersonaProvider";
import { PersonaSwitcher } from "@/components/PersonaSwitcher";
import "./globals.css";

const interTight = Inter_Tight({
  subsets: ["latin"],
  variable: "--font-inter-tight",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Internal Brain",
  description:
    "Permission-aware, freshness-proven, grounded answers over the company brain.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={interTight.variable}>
      <body className="flex min-h-dvh flex-col">
        <PersonaProvider>
          <header className="sticky top-0 z-40 bg-white/90 backdrop-blur-md">
            <div className="mx-auto flex max-w-page flex-wrap items-center justify-between gap-x-10 gap-y-3 px-4 py-5 md:px-8 lg:grid lg:grid-cols-[1fr_auto_1fr]">
              <Link
                href="/ask"
                className="text-xl font-semibold tracking-[-0.02em] text-neutral-900 uppercase"
              >
                Internal Brain.
              </Link>
              <NavLinks />
              <div className="lg:justify-self-end">
                <PersonaSwitcher />
              </div>
            </div>
          </header>
          <main className="mx-auto w-full max-w-page flex-1 px-4 pt-10 pb-24 md:px-8 md:pt-16">
            <PersonaBoundary>{children}</PersonaBoundary>
          </main>
          <footer className="border-t border-neutral-200">
            <div className="mx-auto flex max-w-page flex-wrap items-end justify-between gap-4 px-4 py-10 md:px-8">
              <p className="text-2xl tracking-[-0.02em] text-neutral-900 md:text-3xl">
                Permitted. Fresh.{" "}
                <span className="text-neutral-400">Grounded.</span>
              </p>
              <p className="text-xs text-neutral-500">
                Internal Brain · every answer access-filtered, freshness-checked
                and audited
              </p>
            </div>
          </footer>
        </PersonaProvider>
      </body>
    </html>
  );
}
