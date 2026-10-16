"use client";

import { cn } from "@/lib/utils";
import { dimmed, type CanvasState } from "./canvas";
import {
  AVATAR_R,
  AVATAR_Y,
  HUB_H,
  HUB_Y,
  edgePath,
  edgePoint,
} from "./layout";
import { FAMILIES, familyOf } from "./rules";

/** Membership lines: person → each of their groups. */
export function MembershipLines({ state }: { state: CanvasState }) {
  const { layout, focus, highlight } = state;
  return layout.memberships.map(({ personId, groupId }) => {
    const person = layout.people.get(personId);
    const hub = layout.groupHubs.find((h) => h.id === groupId);
    if (!person || !hub) return null;
    const hx = hub.x + hub.width / 2;
    const y1 = AVATAR_Y - AVATAR_R;
    const y2 = HUB_Y + HUB_H;
    const on = highlight.people.has(personId);
    return (
      <path
        key={`${personId}:${groupId}`}
        d={`M ${person.x} ${y1} C ${person.x} ${y1 - 24}, ${hx} ${y2 + 24}, ${hx} ${y2}`}
        fill="none"
        strokeWidth={on && focus ? 1.5 : 1}
        className={on && focus ? "stroke-neutral-900" : "stroke-neutral-300"}
        opacity={dimmed(state, on)}
      />
    );
  });
}

/** Access edges: one per allow decision. */
export function AccessEdges({ state }: { state: CanvasState }) {
  const { layout, focus, highlight } = state;
  return state.edges.map((edge) => {
    const person = layout.people.get(edge.principal_id);
    const doc = layout.docs.get(edge.document_id);
    if (!person || !doc) return null;
    const family = FAMILIES[familyOf(edge.rule)];
    const on = highlight.lit?.has(edge) ?? false;
    return (
      <path
        key={`${edge.principal_id}:${edge.document_id}`}
        d={edgePath(person.x, doc.x)}
        fill="none"
        strokeWidth={on ? 2 : 1.25}
        strokeDasharray={family.dash}
        className={cn(family.stroke, "transition-opacity duration-200")}
        opacity={focus ? (on ? 1 : 0.07) : 0.55}
      >
        <title>{`${person.person.display_name} → ${doc.doc.title}: ${edge.rule}`}</title>
      </path>
    );
  });
}

/** Rule labels on the highlighted edges. */
export function EdgeLabels({ state }: { state: CanvasState }) {
  const { layout, focus, highlight } = state;
  if (!focus) return null;
  return state.edges
    .filter((edge) => highlight.lit?.has(edge))
    .map((edge) => {
      const person = layout.people.get(edge.principal_id);
      const doc = layout.docs.get(edge.document_id);
      if (!person || !doc) return null;
      const [lx, ly] = edgePoint(person.x, doc.x, highlight.labelT);
      const grant = familyOf(edge.rule) === "grant";
      const text =
        grant && edge.via[0] ? `R5 · ${edge.via[0].subject_id}` : edge.rule;
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
    });
}
