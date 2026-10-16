import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

export function Card({ className, ...props }: ComponentProps<"section">) {
  return (
    <section
      className={cn("rounded-sm border border-neutral-200 bg-white", className)}
      {...props}
    />
  );
}

export function CardHeader({ className, ...props }: ComponentProps<"div">) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-start justify-between gap-3 px-6 pt-6 pb-1",
        className,
      )}
      {...props}
    />
  );
}

export function CardTitle({ className, ...props }: ComponentProps<"h2">) {
  return (
    <h2
      className={cn(
        "text-xl font-medium tracking-[-0.01em] text-neutral-900",
        className,
      )}
      {...props}
    />
  );
}

export function CardDescription({ className, ...props }: ComponentProps<"p">) {
  return (
    <p className={cn("mt-1 text-sm text-neutral-500", className)} {...props} />
  );
}

export function CardContent({ className, ...props }: ComponentProps<"div">) {
  return <div className={cn("px-6 py-5", className)} {...props} />;
}
