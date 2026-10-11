import { BrainCircuit } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import { NavLinks } from "@/components/NavLinks";
import { PersonaBoundary, PersonaProvider } from "@/components/PersonaProvider";
import { PersonaSwitcher } from "@/components/PersonaSwitcher";
import "./globals.css";

export const metadata: Metadata = {
  title: "Internal Brain",
  description:
    "Permission-aware, freshness-proven, grounded answers over the company brain.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <PersonaProvider>
          <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/90 backdrop-blur">
            <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-2.5">
              <div className="flex flex-wrap items-center gap-4">
                <Link
                  href="/ask"
                  className="flex items-center gap-2 font-semibold text-slate-900"
                >
                  <BrainCircuit className="size-5" aria-hidden />
                  Internal Brain
                </Link>
                <NavLinks />
              </div>
              <PersonaSwitcher />
            </div>
          </header>
          <main className="mx-auto max-w-7xl px-4 py-6">
            <PersonaBoundary>{children}</PersonaBoundary>
          </main>
        </PersonaProvider>
      </body>
    </html>
  );
}
