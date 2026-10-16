import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

export function Table({ className, ...props }: ComponentProps<"table">) {
  return (
    <div className="w-full overflow-x-auto">
      <table
        className={cn("w-full border-collapse text-left text-sm", className)}
        {...props}
      />
    </div>
  );
}

export function THead({ className, ...props }: ComponentProps<"thead">) {
  return (
    <thead
      className={cn(
        "border-b border-neutral-300 text-xs text-neutral-500",
        className,
      )}
      {...props}
    />
  );
}

export function TBody({ className, ...props }: ComponentProps<"tbody">) {
  return (
    <tbody
      className={cn("divide-y divide-neutral-200", className)}
      {...props}
    />
  );
}

export function TR({ className, ...props }: ComponentProps<"tr">) {
  return (
    <tr className={cn("align-top transition-colors", className)} {...props} />
  );
}

export function TH({ className, ...props }: ComponentProps<"th">) {
  return <th className={cn("px-3 py-3 font-normal", className)} {...props} />;
}

export function TD({ className, ...props }: ComponentProps<"td">) {
  return (
    <td className={cn("px-3 py-3.5 text-neutral-700", className)} {...props} />
  );
}
