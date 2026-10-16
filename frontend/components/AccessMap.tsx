"use client";

import { ArrowUpRight, Ban, FileText, Lock } from "lucide-react";
import Link from "next/link";
import { useMemo, useState, type KeyboardEvent } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/input";
import { getAccessMap, revokeGrant } from "@/lib/api";
import type { ApiError } from "@/lib/apiClient";
import { formatDateTime } from "@/lib/format";
import { hasRole } from "@/lib/roles";
import type {
  AccessMap,
  AccessMapDocument,
  AccessMapEdge,
  Principal,
} from "@/lib/types";
import { useApiAction, useApiQuery } from "@/lib/useApi";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "./StateViews";

// --- Rule families ----------------------------------------------------------

type Family = "source" | "owner" | "admin" | "grant" | "other";

const FAMILIES: Record<
  Family,
  { label: string; description: string; stroke: string; dash?: string }
> = {
  source: {
    label: "Source ACL",
    description:
      "R8 · the platform's own permissions: channel, project, space, Drive ACL or mailbox.",
    stroke: "stroke-neutral-400",
  },
  owner: {
    label: "Owner",
    description: "R3 · the document's owner. Still capped by source access.",
    stroke: "stroke-neutral-900",
  },
  admin: {
    label: "Admin role",
    description: "R4 · the admin role. Still capped by source access.",
    stroke: "stroke-neutral-900",
    dash: "4 3",
  },
  grant: {
    label: "Explicit grant",
    description:
      "R5 · a local grant to a person, group or role. Confidential documents need one.",
    stroke: "stroke-accent",
  },
  other: {
    label: "Other",
    description: "Any other allow rule.",
    stroke: "stroke-neutral-500",
  },
};

const FAMILY_ORDER: Family[] = ["source", "owner", "admin", "grant", "other"];

function familyOf(rule: string): Family {
  if (rule.startsWith("R8:")) return "source";
  if (rule.startsWith("R3:")) return "owner";
  if (rule.startsWith("R4:")) return "admin";
  if (rule.startsWith("R5:")) return "grant";
  return "other";
}

// --- Layout -----------------------------------------------------------------

const NO_GROUP = "__none__";
const MARGIN = 24;
const MIN_WIDTH = 960;
const HUB_W = 168;
const HUB_H = 54;
const HUB_Y = 16;
const HUB_GAP = 28;
const AVATAR_GAP = 60;
const AVATAR_R = 18;
const AVATAR_Y = 124;
const EDGE_TOP = 170;
const PANEL_Y = 350;
const PANEL_H = 142;
const PANEL_GAP = 24;
const DOC_GAP = 92;
const DOC_SIZE = 32;
const DOC_Y = 370;
const HEIGHT = PANEL_Y + PANEL_H + 16;

type Person = AccessMap["principals"][number];
type NodeRef = { kind: "person" | "group" | "source" | "document"; id: string };

interface Hub {
  id: string;
  name: string;
  eyebrow: string;
  x: number;
  width: number;
  count: number;
}

interface Layout {
  width: number;
  groupHubs: Hub[];
  sourceHubs: Hub[];
  people: Map<string, { x: number; person: Person }>;
  docs: Map<string, { x: number; doc: AccessMapDocument }>;
  memberships: { personId: string; groupId: string }[];
}

function computeLayout(map: AccessMap): Layout {
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

function edgePath(x1: number, x2: number): string {
  const y1 = EDGE_TOP;
  const y2 = DOC_Y;
  return `M ${x1} ${y1} C ${x1} ${y1 + 110}, ${x2} ${y2 - 110}, ${x2} ${y2}`;
}

/** Point at `t` on the same cubic as `edgePath`. */
function edgePoint(x1: number, x2: number, t: number): [number, number] {
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

function initials(name: string): string {
  return name
    .split(/\s+/)
    .map((part) => part[0] ?? "")
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

function truncate(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 1).trimEnd()}…`;
}

/** Up to `lines` lines of at most `max` characters, word-wrapped, ellipsised. */
function wrap(text: string, max: number, lines: number): string[] {
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

function onActivate(handler: () => void) {
  return (event: KeyboardEvent) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      handler();
    }
  };
}

// --- Component --------------------------------------------------------------

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
  const docById = new Map(map.documents.map((d) => [d.id, d]));
  const visibleEdges = map.edges.filter((e) => !hidden.has(familyOf(e.rule)));
  const groupMembers = (groupId: string) =>
    new Set(
      groupId === NO_GROUP
        ? map.principals.filter((p) => p.groups.length === 0).map((p) => p.id)
        : map.principals
            .filter((p) => p.groups.includes(groupId))
            .map((p) => p.id),
    );

  function touches(edge: AccessMapEdge, node: NodeRef): boolean {
    switch (node.kind) {
      case "person":
        return edge.principal_id === node.id;
      case "document":
        return edge.document_id === node.id;
      case "source":
        return docById.get(edge.document_id)?.source_id === node.id;
      case "group":
        return groupMembers(node.id).has(edge.principal_id);
    }
  }

  const lit = focus
    ? new Set(visibleEdges.filter((e) => touches(e, focus)))
    : null;
  const litPeople = new Set<string>();
  const litDocs = new Set<string>();
  if (focus) {
    for (const edge of lit ?? []) {
      litPeople.add(edge.principal_id);
      litDocs.add(edge.document_id);
    }
    if (focus.kind === "person") litPeople.add(focus.id);
    if (focus.kind === "document") litDocs.add(focus.id);
    if (focus.kind === "group")
      for (const id of groupMembers(focus.id)) litPeople.add(id);
    if (focus.kind === "source")
      for (const doc of map.documents)
        if (doc.source_id === focus.id) litDocs.add(doc.id);
  }
  const labelT =
    focus && (focus.kind === "document" || focus.kind === "source")
      ? 0.3
      : 0.72;
  const counts = new Map<Family, number>();
  for (const edge of map.edges) {
    const family = familyOf(edge.rule);
    counts.set(family, (counts.get(family) ?? 0) + 1);
  }

  function interactive(node: NodeRef, label: string) {
    const active = selected?.kind === node.kind && selected.id === node.id;
    const toggle = () => setSelected(active ? null : node);
    return {
      role: "button",
      tabIndex: 0,
      "aria-label": label,
      "aria-pressed": active,
      className: "cursor-pointer outline-none",
      onClick: toggle,
      onKeyDown: onActivate(toggle),
      onMouseEnter: () => setHovered(node),
      onMouseLeave: () => setHovered(null),
      onFocus: () => setHovered(node),
      onBlur: () => setHovered(null),
    } as const;
  }

  const dimmed = (on: boolean) => (focus && !on ? 0.18 : 1);

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

      <div
        className="flex flex-wrap gap-2"
        role="group"
        aria-label="Filter by rule"
      >
        {FAMILY_ORDER.filter((f) => counts.has(f)).map((family) => {
          const off = hidden.has(family);
          return (
            <button
              key={family}
              type="button"
              aria-pressed={!off}
              title={FAMILIES[family].description}
              onClick={() =>
                setHidden((prev) => {
                  const next = new Set(prev);
                  if (off) next.delete(family);
                  else next.add(family);
                  return next;
                })
              }
              className={cn(
                "inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs transition-colors",
                off
                  ? "border-neutral-200 text-neutral-400"
                  : "border-neutral-300 text-neutral-900 hover:border-neutral-900",
              )}
            >
              <svg
                width="22"
                height="6"
                aria-hidden
                className="overflow-visible"
              >
                <line
                  x1="0"
                  y1="3"
                  x2="22"
                  y2="3"
                  strokeWidth="2"
                  strokeDasharray={FAMILIES[family].dash}
                  className={FAMILIES[family].stroke}
                />
              </svg>
              {FAMILIES[family].label}
              <span className="text-neutral-400">{counts.get(family)}</span>
            </button>
          );
        })}
      </div>

      <div className="space-y-4">
        <Card className="overflow-x-auto bg-neutral-50">
          <svg
            viewBox={`0 0 ${layout.width} ${HEIGHT}`}
            className="block h-auto w-full min-w-[56rem] select-none"
            role="img"
            aria-label="Access map: people and groups above, documents grouped by source below, one line per allowed read"
            onClick={(event) => {
              if (event.target === event.currentTarget) setSelected(null);
            }}
          >
            {/* Membership lines: person → each of their groups. */}
            {layout.memberships.map(({ personId, groupId }) => {
              const person = layout.people.get(personId);
              const hub = layout.groupHubs.find((h) => h.id === groupId);
              if (!person || !hub) return null;
              const hx = hub.x + hub.width / 2;
              const y1 = AVATAR_Y - AVATAR_R;
              const y2 = HUB_Y + HUB_H;
              const on = litPeople.has(personId);
              return (
                <path
                  key={`${personId}:${groupId}`}
                  d={`M ${person.x} ${y1} C ${person.x} ${y1 - 24}, ${hx} ${y2 + 24}, ${hx} ${y2}`}
                  fill="none"
                  strokeWidth={on && focus ? 1.5 : 1}
                  className={
                    on && focus ? "stroke-neutral-900" : "stroke-neutral-300"
                  }
                  opacity={dimmed(on)}
                />
              );
            })}

            {/* Source panels sit behind their documents. */}
            {layout.sourceHubs.map((hub) => {
              const on =
                !focus ||
                [...litDocs].some(
                  (id) => docById.get(id)?.source_id === hub.id,
                );
              return (
                <g
                  key={hub.id}
                  opacity={dimmed(on)}
                  {...interactive(
                    { kind: "source", id: hub.id },
                    `Source ${hub.name}`,
                  )}
                >
                  <rect
                    x={hub.x}
                    y={PANEL_Y}
                    width={hub.width}
                    height={PANEL_H}
                    rx={4}
                    className={cn(
                      "fill-white",
                      selected?.kind === "source" && selected.id === hub.id
                        ? "stroke-neutral-900"
                        : "stroke-neutral-200",
                    )}
                  />
                  <text
                    x={hub.x + 12}
                    y={PANEL_Y + PANEL_H - 30}
                    className="fill-neutral-400 text-[9px] tracking-[0.08em] uppercase"
                  >
                    {hub.eyebrow} · {hub.count}{" "}
                    {hub.count === 1 ? "doc" : "docs"}
                  </text>
                  <text
                    x={hub.x + 12}
                    y={PANEL_Y + PANEL_H - 14}
                    className="fill-neutral-900 text-[12px] font-medium"
                  >
                    {truncate(hub.name, Math.floor((hub.width - 24) / 6.6))}
                    <title>{hub.name}</title>
                  </text>
                </g>
              );
            })}

            {/* Access edges: one per allow decision. */}
            {visibleEdges.map((edge) => {
              const person = layout.people.get(edge.principal_id);
              const doc = layout.docs.get(edge.document_id);
              if (!person || !doc) return null;
              const family = FAMILIES[familyOf(edge.rule)];
              const on = lit?.has(edge) ?? false;
              return (
                <path
                  key={`${edge.principal_id}:${edge.document_id}`}
                  d={edgePath(person.x, doc.x)}
                  fill="none"
                  strokeWidth={on ? 2 : 1.25}
                  strokeDasharray={family.dash}
                  className={cn(
                    family.stroke,
                    "transition-opacity duration-200",
                  )}
                  opacity={focus ? (on ? 1 : 0.07) : 0.55}
                >
                  <title>{`${person.person.display_name} → ${doc.doc.title}: ${edge.rule}`}</title>
                </path>
              );
            })}

            {/* Group hubs. */}
            {layout.groupHubs.map((hub) => {
              const on =
                !focus ||
                (focus.kind === "group" && focus.id === hub.id) ||
                [...groupMembers(hub.id)].some((id) => litPeople.has(id));
              const active =
                selected?.kind === "group" && selected.id === hub.id;
              return (
                <g
                  key={hub.id}
                  opacity={dimmed(on)}
                  {...interactive(
                    { kind: "group", id: hub.id },
                    `${hub.eyebrow} ${hub.name}`,
                  )}
                >
                  <rect
                    x={hub.x + (hub.width - HUB_W) / 2}
                    y={HUB_Y}
                    width={HUB_W}
                    height={HUB_H}
                    rx={4}
                    className={cn(
                      "fill-white",
                      active ? "stroke-neutral-900" : "stroke-neutral-200",
                    )}
                  />
                  <text
                    x={hub.x + (hub.width - HUB_W) / 2 + 12}
                    y={HUB_Y + 18}
                    className="fill-neutral-400 text-[9px] tracking-[0.08em] uppercase"
                  >
                    {hub.eyebrow}
                  </text>
                  <text
                    x={hub.x + (hub.width - HUB_W) / 2 + 12}
                    y={HUB_Y + 34}
                    className="fill-neutral-900 text-[12px] font-medium"
                  >
                    {hub.name}
                  </text>
                  <text
                    x={hub.x + (hub.width - HUB_W) / 2 + 12}
                    y={HUB_Y + 47}
                    className="fill-neutral-500 text-[10px]"
                  >
                    {hub.count} {hub.count === 1 ? "member" : "members"}
                  </text>
                </g>
              );
            })}

            {/* People. */}
            {[...layout.people.values()].map(({ x, person }) => {
              const on = !focus || litPeople.has(person.id);
              const active =
                selected?.kind === "person" && selected.id === person.id;
              const strong =
                active || (focus?.kind === "person" && focus.id === person.id);
              const you = person.id === me.id;
              return (
                <g
                  key={person.id}
                  opacity={dimmed(on)}
                  {...interactive(
                    { kind: "person", id: person.id },
                    person.display_name,
                  )}
                >
                  {you && (
                    <circle
                      cx={x}
                      cy={AVATAR_Y}
                      r={AVATAR_R + 4}
                      fill="none"
                      strokeWidth={1.5}
                      className="stroke-accent"
                    />
                  )}
                  <circle
                    cx={x}
                    cy={AVATAR_Y}
                    r={AVATAR_R}
                    className={cn(
                      strong ? "fill-neutral-900" : "fill-white",
                      "stroke-neutral-300",
                    )}
                  />
                  <text
                    x={x}
                    y={AVATAR_Y + 4}
                    textAnchor="middle"
                    className={cn(
                      "text-[11px] font-medium",
                      strong ? "fill-white" : "fill-neutral-900",
                    )}
                  >
                    {initials(person.display_name)}
                  </text>
                  <text
                    x={x}
                    y={AVATAR_Y + AVATAR_R + 18}
                    textAnchor="middle"
                    className="fill-neutral-600 text-[10px]"
                  >
                    {person.display_name.split(" ")[0]}
                    {you ? " · you" : ""}
                  </text>
                </g>
              );
            })}

            {/* Documents. */}
            {[...layout.docs.values()].map(({ x, doc }) => {
              const on = !focus || litDocs.has(doc.id);
              const active =
                selected?.kind === "document" && selected.id === doc.id;
              const strong =
                active || (focus?.kind === "document" && focus.id === doc.id);
              const sensitive =
                doc.classification === "confidential" ||
                doc.classification === "restricted";
              const Icon = sensitive ? Lock : FileText;
              return (
                <g
                  key={doc.id}
                  opacity={dimmed(on)}
                  {...interactive({ kind: "document", id: doc.id }, doc.title)}
                >
                  <rect
                    x={x - DOC_SIZE / 2}
                    y={DOC_Y}
                    width={DOC_SIZE}
                    height={DOC_SIZE}
                    rx={6}
                    className={cn(
                      strong
                        ? "fill-neutral-900 stroke-neutral-900"
                        : "fill-neutral-100",
                      !strong &&
                        (sensitive ? "stroke-amber-500" : "stroke-neutral-300"),
                    )}
                  />
                  <Icon
                    x={x - 8}
                    y={DOC_Y + 8}
                    width={16}
                    height={16}
                    strokeWidth={1.75}
                    className={strong ? "text-white" : "text-neutral-700"}
                    aria-hidden
                  />
                  {wrap(doc.title, 16, 2).map((line, i) => (
                    <text
                      key={i}
                      x={x}
                      y={DOC_Y + DOC_SIZE + 16 + i * 12}
                      textAnchor="middle"
                      className="fill-neutral-700 text-[10px]"
                    >
                      {line}
                    </text>
                  ))}
                  <title>{`${doc.title} · ${doc.classification}`}</title>
                </g>
              );
            })}

            {/* Rule labels on the highlighted edges. */}
            {focus &&
              visibleEdges
                .filter((edge) => lit?.has(edge))
                .map((edge) => {
                  const person = layout.people.get(edge.principal_id);
                  const doc = layout.docs.get(edge.document_id);
                  if (!person || !doc) return null;
                  const [lx, ly] = edgePoint(person.x, doc.x, labelT);
                  const grant = familyOf(edge.rule) === "grant";
                  const text =
                    grant && edge.via[0]
                      ? `R5 · ${edge.via[0].subject_id}`
                      : edge.rule;
                  const w = text.length * 5.6 + 12;
                  return (
                    <g
                      key={`label:${edge.principal_id}:${edge.document_id}`}
                      pointerEvents="none"
                    >
                      <rect
                        x={lx - w / 2}
                        y={ly - 8}
                        width={w}
                        height={16}
                        rx={8}
                        className={cn(
                          grant
                            ? "fill-accent-soft stroke-accent"
                            : "fill-white stroke-neutral-300",
                        )}
                      />
                      <text
                        x={lx}
                        y={ly + 3.5}
                        textAnchor="middle"
                        className={cn(
                          "font-mono text-[9px]",
                          grant ? "fill-accent-strong" : "fill-neutral-700",
                        )}
                      >
                        {text}
                      </text>
                    </g>
                  );
                })}
          </svg>
        </Card>

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

// --- Detail panel -----------------------------------------------------------

function RuleBadge({ rule }: { rule: string }) {
  const family = familyOf(rule);
  return (
    <Badge
      tone={
        family === "grant"
          ? "success"
          : family === "source"
            ? "neutral"
            : "info"
      }
      className="font-mono"
    >
      {rule}
    </Badge>
  );
}

function DetailPanel({
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
  const people = new Map(map.principals.map((p) => [p.id, p]));
  const docs = new Map(map.documents.map((d) => [d.id, d]));

  if (!selected) {
    return (
      <Card>
        <CardContent className="space-y-4">
          <p className="text-sm text-neutral-500">
            Select a person, group, source or document to see each access path
            and the rule that allows it. Generated{" "}
            {formatDateTime(map.generated_at)}.
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

  if (selected.kind === "document") {
    const doc = docs.get(selected.id);
    if (!doc) return null;
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
          <div>
            <p className="text-[11px] tracking-[0.08em] text-neutral-400 uppercase">
              {doc.source_id} · {doc.classification}
            </p>
            <Link
              href={`/documents/${encodeURIComponent(doc.id)}`}
              className="link mt-1 inline-flex items-start gap-0.5 font-medium"
            >
              {doc.title}
              <ArrowUpRight className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            </Link>
          </div>
          <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            <div>
              <p className="mb-2 text-xs text-neutral-500">
                {edges.length} {edges.length === 1 ? "person" : "people"} can
                read it
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

  if (selected.kind === "person") {
    const person = people.get(selected.id);
    if (!person) return null;
    const edges = map.edges.filter((e) => e.principal_id === person.id);
    return (
      <Card>
        <CardContent className="space-y-4">
          <div>
            <p className="font-medium text-neutral-900">
              {person.display_name}
              {person.id === me.id && (
                <span className="text-neutral-400"> · you</span>
              )}
            </p>
            <p className="text-xs text-neutral-500">
              {[
                ...person.roles,
                ...person.groups.map((g) => `group ${g}`),
              ].join(" · ") || "no roles or groups"}
            </p>
          </div>
          <p className="text-xs text-neutral-500">
            Can read {edges.length} of the {map.documents.length} documents in
            your view
          </p>
          <ul className="grid gap-x-10 lg:grid-cols-2">
            {edges.map((edge) => (
              <li
                key={edge.document_id}
                className="flex items-start justify-between gap-3 border-b border-neutral-200 py-2"
              >
                <span className="min-w-0 text-sm">
                  {docs.get(edge.document_id)?.title}
                  {edge.via.length > 0 && (
                    <span className="block text-xs text-accent-strong">
                      via{" "}
                      {edge.via
                        .map((v) => `${v.subject_type} ${v.subject_id}`)
                        .join(", ")}
                    </span>
                  )}
                </span>
                <RuleBadge rule={edge.rule} />
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    );
  }

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
