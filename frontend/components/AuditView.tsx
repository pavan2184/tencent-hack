"use client";

import { Fingerprint, Search } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { listAuditEvents, verifyAuditChain } from "@/lib/api";
import { truncateHash } from "@/lib/format";
import type { AuditQuery } from "@/lib/types";
import { useApiAction, useApiQuery } from "@/lib/useApi";
import { AuditEventDetail } from "./AuditEventDetail";
import { AuditEventTable } from "./AuditEventTable";
import { EmptyState, ErrorState, LoadingState } from "./StateViews";

const EVENT_LIMIT = 200;
const EMPTY_FILTERS = { actor_id: "", document_id: "", action: "" };

export function AuditView() {
  const router = useRouter();
  const pathname = usePathname();
  const selectedId = useSearchParams().get("event");
  const [draft, setDraft] = useState(EMPTY_FILTERS);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const events = useApiQuery(`audit-events:${JSON.stringify(filters)}`, () =>
    listAuditEvents({ ...compact(filters), limit: EVENT_LIMIT }),
  );
  const verify = useApiAction(verifyAuditChain);

  function onFilter(event: FormEvent) {
    event.preventDefault();
    setFilters(draft);
  }

  function select(eventId: string | null) {
    const href = eventId
      ? `${pathname}?event=${encodeURIComponent(eventId)}`
      : pathname;
    router.replace(href, { scroll: false });
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="pb-6">
          <form onSubmit={onFilter} className="flex flex-1 flex-wrap gap-2">
            {(Object.keys(EMPTY_FILTERS) as (keyof typeof EMPTY_FILTERS)[]).map(
              (key) => (
                <Input
                  key={key}
                  value={draft[key]}
                  onChange={(event) =>
                    setDraft({ ...draft, [key]: event.target.value })
                  }
                  placeholder={key.replace("_", " ")}
                  aria-label={key.replace("_", " ")}
                  className="w-44"
                />
              ),
            )}
            <Button type="submit" variant="secondary">
              <Search className="size-4" aria-hidden />
              Filter
            </Button>
          </form>
          <Button
            variant="outline"
            onClick={() => verify.run()}
            disabled={verify.pending}
          >
            <Fingerprint className="size-4" aria-hidden />
            Verify chain
          </Button>
        </CardHeader>
        {(verify.data || verify.error) && (
          <CardContent className="border-t border-neutral-200 py-4">
            {verify.error && <ErrorState error={verify.error} />}
            {verify.data && (
              <div className="flex flex-wrap items-center gap-2 text-sm text-neutral-600">
                <Badge tone={verify.data.ok ? "success" : "danger"}>
                  {verify.data.ok ? "chain intact" : "chain broken"}
                </Badge>
                <span>{verify.data.length} events</span>
                <span
                  className="font-mono text-xs"
                  title={verify.data.head_hash ?? undefined}
                >
                  head {truncateHash(verify.data.head_hash, 16)}
                </span>
                {verify.data.first_broken_seq !== null && (
                  <span className="text-red-700">
                    first broken at seq {verify.data.first_broken_seq}
                  </span>
                )}
              </div>
            )}
          </CardContent>
        )}
      </Card>

      <div
        className={
          selectedId ? "grid items-start gap-6 xl:grid-cols-[1fr_30rem]" : undefined
        }
      >
        <Card>
          <CardContent className="px-2 py-2">
            {events.error && (
              <ErrorState
                error={events.error}
                title={
                  events.error.status === 403
                    ? "The audit log is restricted to auditors and admins"
                    : undefined
                }
                className="mx-3 my-2"
              />
            )}
            {events.loading && !events.data && (
              <div className="px-3">
                <LoadingState />
              </div>
            )}
            {events.data?.length === 0 && (
              <div className="px-3">
                <EmptyState>No audit events match.</EmptyState>
              </div>
            )}
            {events.data && events.data.length > 0 && (
              <AuditEventTable
                events={events.data}
                selectedId={selectedId}
                onSelect={select}
              />
            )}
          </CardContent>
        </Card>

        {selectedId && (
          <AuditEventDetail
            key={selectedId}
            eventId={selectedId}
            onClose={() => select(null)}
          />
        )}
      </div>
    </div>
  );
}

function compact(filters: typeof EMPTY_FILTERS): AuditQuery {
  return Object.fromEntries(
    Object.entries(filters)
      .map(([key, value]) => [key, value.trim()])
      .filter(([, value]) => value !== ""),
  );
}
