import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

// Housend-style hover: a green fill rises from the bottom of the pill (`before:` layer).
const wipe =
  "before:absolute before:inset-0 before:-z-10 before:translate-y-full before:rounded-[inherit] before:bg-accent-strong before:transition-transform before:duration-500 before:ease-out-soft hover:text-white hover:before:translate-y-0";

const variants = {
  primary: cn("bg-neutral-900 text-white", wipe),
  accent: "bg-accent-strong text-white hover:bg-neutral-900",
  secondary: "bg-neutral-100 text-neutral-900 hover:bg-neutral-200",
  outline: cn(
    "border border-neutral-300 bg-white text-neutral-900 hover:border-accent-strong",
    wipe,
  ),
  ghost: "text-neutral-700 hover:bg-neutral-100 hover:text-neutral-900",
  danger: "bg-red-700 text-white hover:bg-red-800",
} as const;

const sizes = {
  sm: "h-8 px-4 text-xs",
  md: "h-10 px-5 text-sm",
  icon: "size-10 text-sm",
} as const;

export interface ButtonProps extends ComponentProps<"button"> {
  variant?: keyof typeof variants;
  size?: keyof typeof sizes;
}

export function Button({
  variant = "primary",
  size = "md",
  type = "button",
  className,
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        "relative isolate inline-flex items-center justify-center gap-1.5 overflow-hidden rounded-full font-medium whitespace-nowrap transition-colors duration-300",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-neutral-900",
        "disabled:pointer-events-none disabled:opacity-40",
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    />
  );
}
