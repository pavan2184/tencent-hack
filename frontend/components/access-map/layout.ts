/** Geometry of the map: group cards → people → one line per read → documents in source panels. */

import type { AccessMap, AccessMapDocument } from "@/lib/types";

export const NO_GROUP = "__none__";
const MARGIN = 24;
const MIN_WIDTH = 960;
export const HUB_W = 168;
export const HUB_H = 54;
export const HUB_Y = 16;
const HUB_GAP = 28;
const AVATAR_GAP = 60;
export const AVATAR_R = 18;
export const AVATAR_Y = 124;
const EDGE_TOP = 170;
export const PANEL_Y = 350;
export const PANEL_H = 142;
const PANEL_GAP = 24;
const DOC_GAP = 92;
export const DOC_SIZE = 32;
export const DOC_Y = 370;
export const HEIGHT = PANEL_Y + PANEL_H + 16;

export type Person = AccessMap["principals"][number];
export type NodeRef = {
  kind: "person" | "group" | "source" | "document";
  id: string;
};

export interface Hub {
  id: string;
  name: string;
  eyebrow: string;
  x: number;
  width: number;
  count: number;
}

export interface Layout {
  width: number;
  groupHubs: Hub[];
  sourceHubs: Hub[];
  people: Map<string, { x: number; person: Person }>;
  docs: Map<string, { x: number; doc: AccessMapDocument }>;
  memberships: { personId: string; groupId: string }[];
}

export function computeLayout(map: AccessMap): Layout {
  const groupIds = new Set(map.groups.map((g) => g.id));
  const membersOf = new Map<string, Person[]>();
  const memberships: Layout["memberships"] = [];
  for (const person of map.principals) {
    const own = person.groups.filter((g) => groupIds.has(g));
    const home = own[0] ?? NO_GROUP;
    membersOf.set(home, [...(membersOf.get(home) ?? []), person]);
    for (const groupId of own)
      memberships.push({ personId: person.id, groupId });
  }

  const groupRows = [
    ...map.groups.map((g) => ({ id: g.id, name: g.name, eyebrow: "Group" })),
    ...(membersOf.has(NO_GROUP)
      ? [{ id: NO_GROUP, name: "No group", eyebrow: "Direct identity" }]
      : []),
  ];
  const sourceRows = map.sources.map((s) => ({
    id: s.id,
    name: s.name,
    eyebrow: `Source · ${s.kind}`,
  }));
  const docsOf = new Map<string, AccessMapDocument[]>();
  for (const doc of map.documents)
    docsOf.set(doc.source_id, [...(docsOf.get(doc.source_id) ?? []), doc]);

  const memberCount = (groupId: string) =>
    groupId === NO_GROUP
      ? (membersOf.get(NO_GROUP)?.length ?? 0)
      : memberships.filter((m) => m.groupId === groupId).length;
  const groupWidths = groupRows.map((g) =>
    Math.max(HUB_W, (membersOf.get(g.id)?.length ?? 0) * AVATAR_GAP),
  );
  const sourceWidths = sourceRows.map((s) =>
    Math.max(HUB_W, (docsOf.get(s.id)?.length ?? 0) * DOC_GAP),
  );
  const span = (widths: number[], gap: number) =>
    widths.reduce((sum, w) => sum + w, 0) +
    gap * Math.max(0, widths.length - 1);
  const width = Math.max(
    MIN_WIDTH,
    span(groupWidths, HUB_GAP) + 2 * MARGIN,
    span(sourceWidths, PANEL_GAP) + 2 * MARGIN,
  );

  function place<T extends { id: string; name: string; eyebrow: string }>(
    rows: T[],
    widths: number[],
    gap: number,
    count: (id: string) => number,
  ): Hub[] {
    let x = (width - span(widths, gap)) / 2;
    return rows.map((row, i) => {
      const hub = { ...row, x, width: widths[i], count: count(row.id) };
      x += widths[i] + gap;
      return hub;
    });
  }

  const groupHubs = place(groupRows, groupWidths, HUB_GAP, memberCount);
  const sourceHubs = place(
    sourceRows,
    sourceWidths,
    PANEL_GAP,
    (id) => docsOf.get(id)?.length ?? 0,
  );

  const people = new Map<string, { x: number; person: Person }>();
  for (const hub of groupHubs) {
    const members = membersOf.get(hub.id) ?? [];
    members.forEach((person, i) => {
      const x =
        hub.x + hub.width / 2 + (i - (members.length - 1) / 2) * AVATAR_GAP;
      people.set(person.id, { x, person });
    });
  }
  const docs = new Map<string, { x: number; doc: AccessMapDocument }>();
  for (const hub of sourceHubs) {
    const own = docsOf.get(hub.id) ?? [];
    own.forEach((doc, i) => {
      const x = hub.x + hub.width / 2 + (i - (own.length - 1) / 2) * DOC_GAP;
      docs.set(doc.id, { x, doc });
    });
  }
  return { width, groupHubs, sourceHubs, people, docs, memberships };
}

export function edgePath(x1: number, x2: number): string {
  const y1 = EDGE_TOP;
  const y2 = DOC_Y;
  return `M ${x1} ${y1} C ${x1} ${y1 + 110}, ${x2} ${y2 - 110}, ${x2} ${y2}`;
}

/** Point at `t` on the same cubic as `edgePath`. */
export function edgePoint(x1: number, x2: number, t: number): [number, number] {
  const u = 1 - t;
  const y1 = EDGE_TOP;
  const y2 = DOC_Y;
  const x =
    u * u * u * x1 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t * t * t * x2;
  const y =
    u * u * u * y1 +
    3 * u * u * t * (y1 + 110) +
    3 * u * t * t * (y2 - 110) +
    t * t * t * y2;
  return [x, y];
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .map((part) => part[0] ?? "")
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

export function truncate(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 1).trimEnd()}…`;
}

/** Up to `lines` lines of at most `max` characters, word-wrapped, ellipsised. */
export function wrap(text: string, max: number, lines: number): string[] {
  const all: string[] = [];
  for (const word of text.split(/\s+/)) {
    const last = all.at(-1);
    if (last !== undefined && `${last} ${word}`.length <= max)
      all[all.length - 1] = `${last} ${word}`;
    else all.push(word.length > max ? `${word.slice(0, max - 1)}…` : word);
  }
  if (all.length <= lines) return all;
  const kept = all.slice(0, lines);
  kept[lines - 1] = `${kept[lines - 1].slice(0, max - 1)}…`;
  return kept;
}
