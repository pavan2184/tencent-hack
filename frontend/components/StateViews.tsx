import { CircleAlert, Inbox, LoaderCircle } from "lucide-react";
import type { ReactNode } from "react";
import type { ApiError } from "@/lib/apiClient";
import { cn } from "@/lib/utils";

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div
      className="flex items-center gap-2 py-6 text-sm text-neutral-500"
      role="status"
    >
      <LoaderCircle className="size-4 animate-spin" aria-hidden />
      {label}
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-center gap-2 py-6 text-sm text-neutral-500">
      <Inbox className="size-4" aria-hidden />
      {children}
    </div>
  );
}

/** Renders an API error envelope: message, code, and request id for support/audit. */
export function ErrorState({
  error,
  title,
  className,
}: {
  error: ApiError;
  title?: string;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={cn(
        "flex gap-2.5 rounded-sm bg-red-50 px-4 py-3 text-sm text-red-800",
        className,
      )}
    >
      <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="min-w-0">
        {title && <p className="font-medium">{title}</p>}
        <p>{error.message}</p>
        {flatDetails(error.details)}
        <p className="mt-0.5 font-mono text-xs text-red-600">
          {error.code}
          {error.status > 0 && ` · HTTP ${error.status}`}
          {error.requestId && ` · request ${error.requestId}`}
        </p>
      </div>
    </div>
  );
}

/** Renders `details` only when it is a flat object (e.g. cap_exceeded → {cap, limit, window}). */
function flatDetails(details: unknown) {
  if (typeof details !== "object" || details === null || Array.isArray(details))
    return null;
  const entries = Object.entries(details).filter(([, value]) =>
    ["string", "number", "boolean"].includes(typeof value),
  );
  if (entries.length === 0) return null;
  return (
    <p className="mt-0.5 text-xs text-red-700">
      {entries.map(([key, value]) => `${key}: ${String(value)}`).join(" · ")}
    </p>
  );
}
