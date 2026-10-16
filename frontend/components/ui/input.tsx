import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

const field =
  "w-full rounded-full border border-transparent bg-neutral-100 px-5 text-sm text-neutral-900 transition-colors placeholder:text-neutral-400 hover:bg-neutral-200/70 focus:border-neutral-900 focus:bg-white focus:outline-none disabled:opacity-50";

export function Input({ className, ...props }: ComponentProps<"input">) {
  return <input className={cn(field, "h-10", className)} {...props} />;
}

export function Textarea({ className, ...props }: ComponentProps<"textarea">) {
  return (
    <textarea
      className={cn(field, "min-h-24 rounded-2xl py-3", className)}
      {...props}
    />
  );
}

export function NativeSelect({
  className,
  ...props
}: ComponentProps<"select">) {
  return (
    <select
      className={cn(field, "select-chevron h-10 pr-10", className)}
      {...props}
    />
  );
}

export function Label({ className, ...props }: ComponentProps<"label">) {
  return (
    <label
      className={cn("block pl-1 text-xs text-neutral-500", className)}
      {...props}
    />
  );
}
