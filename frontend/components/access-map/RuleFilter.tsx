"use client";

import { cn } from "@/lib/utils";
import { FAMILIES, FAMILY_ORDER, type Family } from "./rules";

/** One chip per rule family present on the map; a pressed chip shows its lines. */
export function RuleFilter({
  counts,
  hidden,
  onToggle,
}: {
  counts: Map<Family, number>;
  hidden: Set<Family>;
  onToggle: (family: Family) => void;
}) {
  return (
    <div
      className="flex flex-wrap gap-2"
      role="group"
      aria-label="Filter by rule"
    >
      {FAMILY_ORDER.filter((f) => counts.has(f)).map((family) => {
        const off = hidden.has(family);
        return (
          <button
            key={family}
            type="button"
            aria-pressed={!off}
            title={FAMILIES[family].description}
            onClick={() => onToggle(family)}
            className={cn(
              "inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs transition-colors",
              off
                ? "border-neutral-200 text-neutral-400"
                : "border-neutral-300 text-neutral-900 hover:border-neutral-900",
            )}
          >
            <svg width="22" height="6" aria-hidden className="overflow-visible">
              <line
                x1="0"
                y1="3"
                x2="22"
                y2="3"
                strokeWidth="2"
                strokeDasharray={FAMILIES[family].dash}
                className={FAMILIES[family].stroke}
              />
            </svg>
            {FAMILIES[family].label}
            <span className="text-neutral-400">{counts.get(family)}</span>
          </button>
        );
      })}
    </div>
  );
}
