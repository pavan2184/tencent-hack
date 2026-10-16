"use client";

import { useMemo, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/input";
import { getAccessMap, revokeGrant } from "@/lib/api";
import type { Principal } from "@/lib/types";
import { useApiAction, useApiQuery } from "@/lib/useApi";
import { EmptyState, ErrorState, LoadingState } from "../StateViews";
import { DetailPanel } from "./DetailPanel";
import { computeHighlight } from "./highlight";
import { computeLayout, type NodeRef } from "./layout";
import { MapCanvas } from "./MapCanvas";
import { PermissionSync } from "./PermissionSync";
import { RuleFilter } from "./RuleFilter";
import { familyOf, type Family } from "./rules";

/** Who can read what, and by which rule, over the documents the viewer can read. */
export function AccessMapView({ me }: { me: Principal }) {
  const query = useApiQuery("access-map", getAccessMap);
  const revoke = useApiAction(revokeGrant);
  const [selected, setSelected] = useState<NodeRef | null>(null);
  const [hovered, setHovered] = useState<NodeRef | null>(null);
  const [hidden, setHidden] = useState<Set<Family>>(new Set());

  const map = query.data;
  const layout = useMemo(() => (map ? computeLayout(map) : null), [map]);

  if (query.error) return <ErrorState error={query.error} />;
  if (!map || !layout) return <LoadingState label="Mapping access…" />;
  if (map.documents.length === 0)
    return (
      <Card>
        <CardContent>
          <EmptyState>
            You cannot read any documents, so there is nothing to map.
          </EmptyState>
        </CardContent>
      </Card>
    );

  const focus = hovered ?? selected;
  const edges = map.edges.filter((e) => !hidden.has(familyOf(e.rule)));
  const highlight = computeHighlight(map, edges, focus);
  const counts = new Map<Family, number>();
  for (const edge of map.edges) {
    const family = familyOf(edge.rule);
    counts.set(family, (counts.get(family) ?? 0) + 1);
  }

  function toggleFamily(family: Family) {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(family)) next.delete(family);
      else next.add(family);
      return next;
    });
  }

  async function onRevoke(grantId: string) {
    const result = await revoke.run(grantId);
    if (result.ok) query.reload();
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-neutral-500">
          {map.principals.length} people · {map.groups.length} groups ·{" "}
          {map.documents.length} documents in your view · {map.edges.length}{" "}
          access paths · policy{" "}
          <span className="font-mono text-xs">{map.policy_version}</span>
        </p>
        <NativeSelect
          aria-label="Highlight a person"
          className="w-full sm:w-64"
          value={selected?.kind === "person" ? selected.id : ""}
          onChange={(event) =>
            setSelected(
              event.target.value
                ? { kind: "person", id: event.target.value }
                : null,
            )
          }
        >
          <option value="">Highlight a person…</option>
          {map.principals.map((p) => (
            <option key={p.id} value={p.id}>
              {p.display_name}
              {p.id === me.id ? " (you)" : ""}
            </option>
          ))}
        </NativeSelect>
      </div>

      <PermissionSync
        key={map.generated_at}
        documents={map.documents}
        generatedAt={map.generated_at}
        onReload={query.reload}
        reloading={query.loading}
      />

      <RuleFilter counts={counts} hidden={hidden} onToggle={toggleFamily} />

      <div className="space-y-4">
        <MapCanvas
          map={map}
          layout={layout}
          me={me}
          edges={edges}
          focus={focus}
          selected={selected}
          highlight={highlight}
          onSelect={setSelected}
          onHover={setHovered}
        />
        <DetailPanel
          map={map}
          me={me}
          selected={selected}
          onRevoke={onRevoke}
          revoking={revoke.pending}
          revokeError={revoke.error}
        />
      </div>
    </div>
  );
}
