"use client";

import { ArrowUpRight, Ban } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { ApiError } from "@/lib/apiClient";
import { formatDateTime } from "@/lib/format";
import { hasRole } from "@/lib/roles";
import type { AccessMap, AccessMapDocument, Principal } from "@/lib/types";
import { ErrorState } from "../StateViews";
import { RuleBadge } from "./RuleBadge";

function PermissionTimes({ doc }: { doc: AccessMapDocument }) {
  if (!doc.permissions_synced_at)
    return (
      <p className="text-xs text-neutral-500">
        Permissions are managed here, not synced from a source.
      </p>
    );
  return (
    <p className="text-xs text-neutral-500">
      Source permissions synced {formatDateTime(doc.permissions_synced_at)}
      {doc.permissions_expire_at && (
        <>
          {" "}
          · count until {formatDateTime(doc.permissions_expire_at)}, then the
          document closes to everyone until the next sync
        </>
      )}
    </p>
  );
}

export function DocumentDetail({
  map,
  me,
  doc,
  onRevoke,
  revoking,
  revokeError,
}: {
  map: AccessMap;
  me: Principal;
  doc: AccessMapDocument;
  onRevoke: (grantId: string) => void;
  revoking: boolean;
  revokeError: ApiError | null;
}) {
  const people = new Map(map.principals.map((p) => [p.id, p]));
  const edges = map.edges.filter((e) => e.document_id === doc.id);
  const grants = new Map<string, { subject: string; people: string[] }>();
  for (const edge of edges)
    for (const via of edge.via) {
      const entry = grants.get(via.grant_id) ?? {
        subject: `${via.subject_type} ${via.subject_id}`,
        people: [],
      };
      entry.people.push(
        people.get(edge.principal_id)?.display_name ?? edge.principal_id,
      );
      grants.set(via.grant_id, entry);
    }
  const canRevoke =
    hasRole(me, "admin") ||
    edges.some((e) => e.principal_id === me.id && e.rule === "R3:owner");

  return (
    <Card>
      <CardContent className="space-y-4">
        <div className="space-y-1">
          <p className="text-[11px] tracking-[0.08em] text-neutral-400 uppercase">
            {doc.source_id} · {doc.classification}
          </p>
          <Link
            href={`/documents/${encodeURIComponent(doc.id)}`}
            className="link inline-flex items-start gap-0.5 font-medium"
          >
            {doc.title}
            <ArrowUpRight className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          </Link>
          <PermissionTimes doc={doc} />
        </div>
        <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <div>
            <p className="mb-2 text-xs text-neutral-500">
              {edges.length} {edges.length === 1 ? "person" : "people"} can read
              it
            </p>
            <ul className="grid gap-x-10 lg:grid-cols-2">
              {edges.map((edge) => (
                <li
                  key={edge.principal_id}
                  className="flex items-center justify-between gap-3 border-b border-neutral-200 py-2 text-sm"
                >
                  <span>
                    {people.get(edge.principal_id)?.display_name ??
                      edge.principal_id}
                  </span>
                  <RuleBadge rule={edge.rule} />
                </li>
              ))}
            </ul>
          </div>
          {grants.size > 0 && (
            <div className="space-y-2">
              <p className="text-xs text-neutral-500">Grants in effect</p>
              {[...grants].map(([grantId, grant]) => (
                <div
                  key={grantId}
                  className="flex items-center justify-between gap-3 rounded-sm bg-accent-soft px-3 py-2"
                >
                  <span className="min-w-0 text-sm">
                    <span className="font-medium text-accent-strong">
                      {grant.subject}
                    </span>
                    <span className="block text-xs text-neutral-600">
                      reaches {grant.people.join(", ")}
                    </span>
                  </span>
                  {canRevoke && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={revoking}
                      onClick={() => onRevoke(grantId)}
                    >
                      <Ban className="size-3.5" aria-hidden />
                      Revoke
                    </Button>
                  )}
                </div>
              ))}
              {revokeError && <ErrorState error={revokeError} />}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
