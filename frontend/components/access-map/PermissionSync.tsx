"use client";

import { RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { formatDateTime, formatDuration } from "@/lib/format";
import type { AccessMapDocument } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Warn this long before the first snapshot on the map expires. */
const WARN_S = 60;

const EXPLAINER =
  "Every sync re-reads each source's permissions. They count for a limited time " +
  "(5 minutes for confidential documents). If no sync runs in that time, the " +
  "document is closed to everyone, and leaves this map, until the next sync.";

function parse(iso: string | null): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isNaN(t) ? null : t;
}

/** Server time now, from the map's `generated_at` plus the time since it arrived, so a skewed
 * browser clock cannot make the countdown lie. Ticks once a second. */
function useServerNow(generatedAt: string): number {
  const [now, setNow] = useState(() => Date.parse(generatedAt));
  useEffect(() => {
    const server = Date.parse(generatedAt);
    const client = Date.now();
    const timer = window.setInterval(
      () => setNow(server + (Date.now() - client)),
      1000,
    );
    return () => window.clearInterval(timer);
  }, [generatedAt]);
  return now;
}

/** "Permissions synced 40s ago": the oldest source-permission sync behind the map, and how long
 * until the first one expires. Uploads are left out: their permissions are managed here.
 * Render it with `key={generatedAt}` so a reload restarts the clock. */
export function PermissionSync({
  documents,
  generatedAt,
  onReload,
  reloading,
}: {
  documents: AccessMapDocument[];
  generatedAt: string;
  onReload: () => void;
  reloading: boolean;
}) {
  const now = useServerNow(generatedAt);
  const synced = documents
    .map((d) => parse(d.permissions_synced_at))
    .filter((t): t is number => t !== null);
  const expiries = documents
    .map((d) => parse(d.permissions_expire_at))
    .filter((t): t is number => t !== null);
  if (synced.length === 0) return null;

  const oldest = Math.min(...synced);
  const firstExpiry = expiries.length ? Math.min(...expiries) : null;
  const left =
    firstExpiry === null ? null : Math.round((firstExpiry - now) / 1000);
  const expired = left !== null && left <= 0;
  const soon = left !== null && !expired && left <= WARN_S;
  const age = Math.max(0, Math.round((now - oldest) / 1000));

  return (
    <div
      role="status"
      title={EXPLAINER}
      className={cn(
        "flex flex-wrap items-center gap-x-3 gap-y-2 rounded-sm px-4 py-2 text-sm",
        expired || soon
          ? "bg-amber-50 text-amber-900"
          : "bg-neutral-100 text-neutral-600",
      )}
    >
      <span
        aria-hidden
        className={cn(
          "size-2 shrink-0 rounded-full",
          expired || soon ? "bg-amber-500" : "bg-accent",
        )}
      />
      {expired ? (
        <span className="min-w-0 flex-1">
          Source permissions on this map have expired since it loaded. Reload to
          see who can read what now.
        </span>
      ) : (
        <span className="min-w-0 flex-1">
          Source permissions synced{" "}
          <time dateTime={new Date(oldest).toISOString()}>
            {age < 5 ? "just now" : `${formatDuration(age)} ago`}
          </time>
          {left !== null && (
            <>
              {" "}
              · {soon ? "the first ones expire" : "first expiry"} in{" "}
              <time dateTime={new Date(firstExpiry ?? now).toISOString()}>
                {formatDuration(left)}
              </time>
              {soon && " unless a sync runs"}
            </>
          )}
          <span className="sr-only">
            {" "}
            (oldest sync {formatDateTime(new Date(oldest).toISOString())})
          </span>
        </span>
      )}
      <Button
        size="sm"
        variant="outline"
        onClick={onReload}
        disabled={reloading}
        className="shrink-0"
      >
        <RefreshCw
          className={cn("size-3.5", reloading && "animate-spin")}
          aria-hidden
        />
        Reload
      </Button>
    </div>
  );
}
