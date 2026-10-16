"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/ask", label: "Ask" },
  { href: "/documents", label: "Documents" },
  { href: "/sources", label: "Sources" },
  { href: "/access", label: "Access" },
  { href: "/audit", label: "Audit" },
] as const;

export function NavLinks() {
  const pathname = usePathname();
  return (
    <nav className="order-last flex w-full items-center gap-7 overflow-x-auto [scrollbar-width:none] lg:order-none lg:w-auto lg:gap-9">
      {LINKS.map(({ href, label }) => {
        const active = pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "py-1 text-[15px] whitespace-nowrap decoration-1 underline-offset-[6px] transition-colors",
              active
                ? "text-neutral-900 underline"
                : "text-neutral-500 hover:text-neutral-900",
            )}
          >
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
