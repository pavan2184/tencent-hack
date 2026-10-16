/** Which edges, people and documents light up for the hovered or selected node. */

import type { AccessMap, AccessMapEdge } from "@/lib/types";
import { NO_GROUP, type NodeRef } from "./layout";

export interface Highlight {
  /** Edges touching the focus; null when nothing is focused. */
  lit: Set<AccessMapEdge> | null;
  people: Set<string>;
  docs: Set<string>;
  /** Rule labels sit near the documents when a document or source is focused. */
  labelT: number;
}

export function groupMembers(map: AccessMap, groupId: string): Set<string> {
  return new Set(
    groupId === NO_GROUP
      ? map.principals.filter((p) => p.groups.length === 0).map((p) => p.id)
      : map.principals
          .filter((p) => p.groups.includes(groupId))
          .map((p) => p.id),
  );
}

function touches(
  map: AccessMap,
  edge: AccessMapEdge,
  node: NodeRef,
  sourceOf: Map<string, string>,
): boolean {
  switch (node.kind) {
    case "person":
      return edge.principal_id === node.id;
    case "document":
      return edge.document_id === node.id;
    case "source":
      return sourceOf.get(edge.document_id) === node.id;
    case "group":
      return groupMembers(map, node.id).has(edge.principal_id);
  }
}

export function computeHighlight(
  map: AccessMap,
  edges: AccessMapEdge[],
  focus: NodeRef | null,
): Highlight {
  const people = new Set<string>();
  const docs = new Set<string>();
  if (!focus) return { lit: null, people, docs, labelT: 0.72 };

  const sourceOf = new Map(map.documents.map((d) => [d.id, d.source_id]));
  const lit = new Set(edges.filter((e) => touches(map, e, focus, sourceOf)));
  for (const edge of lit) {
    people.add(edge.principal_id);
    docs.add(edge.document_id);
  }
  if (focus.kind === "person") people.add(focus.id);
  if (focus.kind === "document") docs.add(focus.id);
  if (focus.kind === "group")
    for (const id of groupMembers(map, focus.id)) people.add(id);
  if (focus.kind === "source")
    for (const doc of map.documents)
      if (doc.source_id === focus.id) docs.add(doc.id);
  const nearDocs = focus.kind === "document" || focus.kind === "source";
  return { lit, people, docs, labelT: nearDocs ? 0.3 : 0.72 };
}
