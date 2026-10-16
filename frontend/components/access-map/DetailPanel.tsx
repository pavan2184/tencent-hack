"use client";

import { Card, CardContent } from "@/components/ui/card";
import type { ApiError } from "@/lib/apiClient";
import { formatDateTime } from "@/lib/format";
import type { AccessMap, Principal } from "@/lib/types";
import { DocumentDetail } from "./DocumentDetail";
import { NO_GROUP, type NodeRef } from "./layout";
import { PersonDetail } from "./PersonDetail";
import { FAMILIES, FAMILY_ORDER } from "./rules";

function Overview({ map }: { map: AccessMap }) {
  return (
    <Card>
      <CardContent className="space-y-4">
        <p className="text-sm text-neutral-500">
          Select a person, group, source or document to see each access path and
          the rule that allows it. Generated {formatDateTime(map.generated_at)}.
        </p>
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {FAMILY_ORDER.filter((f) => f !== "other").map((family) => (
            <li key={family} className="text-sm">
              <span className="font-medium text-neutral-900">
                {FAMILIES[family].label}
              </span>
              <span className="block text-xs text-neutral-500">
                {FAMILIES[family].description}
              </span>
            </li>
          ))}
        </ul>
        <p className="text-xs text-neutral-400">
          Documents you cannot read never appear here. A missing line means no
          access.
        </p>
      </CardContent>
    </Card>
  );
}

/** A group's members or a source's documents, with a count for each. */
function MemberList({ map, selected }: { map: AccessMap; selected: NodeRef }) {
  const isGroup = selected.kind === "group";
  const title = isGroup
    ? selected.id === NO_GROUP
      ? "No group"
      : (map.groups.find((g) => g.id === selected.id)?.name ?? selected.id)
    : (map.sources.find((s) => s.id === selected.id)?.name ?? selected.id);
  const rows = isGroup
    ? map.principals
        .filter((p) =>
          selected.id === NO_GROUP
            ? p.groups.length === 0
            : p.groups.includes(selected.id),
        )
        .map((p) => ({
          key: p.id,
          label: p.display_name,
          detail: `${map.edges.filter((e) => e.principal_id === p.id).length} documents`,
        }))
    : map.documents
        .filter((d) => d.source_id === selected.id)
        .map((d) => ({
          key: d.id,
          label: d.title,
          detail: `${map.edges.filter((e) => e.document_id === d.id).length} readers`,
        }));
  return (
    <Card>
      <CardContent className="space-y-3">
        <div>
          <p className="text-[11px] tracking-[0.08em] text-neutral-400 uppercase">
            {isGroup ? "Group" : "Source"}
          </p>
          <p className="font-medium text-neutral-900">{title}</p>
        </div>
        <ul className="grid gap-x-10 lg:grid-cols-2">
          {rows.map((row) => (
            <li
              key={row.key}
              className="flex items-start justify-between gap-3 border-b border-neutral-200 py-2 text-sm"
            >
              <span className="min-w-0">{row.label}</span>
              <span className="shrink-0 text-xs text-neutral-500">
                {row.detail}
              </span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

export function DetailPanel({
  map,
  me,
  selected,
  onRevoke,
  revoking,
  revokeError,
}: {
  map: AccessMap;
  me: Principal;
  selected: NodeRef | null;
  onRevoke: (grantId: string) => void;
  revoking: boolean;
  revokeError: ApiError | null;
}) {
  if (!selected) return <Overview map={map} />;
  if (selected.kind === "document") {
    const doc = map.documents.find((d) => d.id === selected.id);
    return doc ? (
      <DocumentDetail
        map={map}
        me={me}
        doc={doc}
        onRevoke={onRevoke}
        revoking={revoking}
        revokeError={revokeError}
      />
    ) : null;
  }
  if (selected.kind === "person") {
    const person = map.principals.find((p) => p.id === selected.id);
    return person ? <PersonDetail map={map} me={me} person={person} /> : null;
  }
  return <MemberList map={map} selected={selected} />;
}
