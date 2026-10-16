import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

const tones = {
  neutral: "bg-neutral-100 text-neutral-700 before:bg-neutral-400",
  success: "bg-accent-soft text-accent-strong before:bg-accent",
  warning: "bg-amber-50 text-amber-800 before:bg-amber-500",
  danger: "bg-red-50 text-red-700 before:bg-red-500",
  info: "bg-white text-neutral-900 ring-1 ring-neutral-300 ring-inset before:bg-neutral-900",
} as const;

export type BadgeTone = keyof typeof tones;

export interface BadgeProps extends ComponentProps<"span"> {
  tone?: BadgeTone;
  /** Leading status dot, for badges that report a state rather than label a thing. */
  dot?: boolean;
}

export function Badge({
  tone = "neutral",
  dot = false,
  className,
  ...props
}: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs whitespace-nowrap",
        tones[tone],
        dot
          ? "before:size-1.5 before:shrink-0 before:rounded-full before:content-['']"
          : "before:hidden",
        className,
      )}
      {...props}
    />
  );
}
