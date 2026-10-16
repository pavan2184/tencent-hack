"use client";

import { FileText, Lock } from "lucide-react";
import { cn } from "@/lib/utils";
import { dimmed, isFocused, isSelected, type CanvasState } from "./canvas";
import { groupMembers } from "./highlight";
import {
  AVATAR_R,
  AVATAR_Y,
  DOC_SIZE,
  DOC_Y,
  HUB_H,
  HUB_W,
  HUB_Y,
  PANEL_H,
  PANEL_Y,
  initials,
  truncate,
  wrap,
} from "./layout";

/** Source panels sit behind their documents. */
export function SourcePanels({ state }: { state: CanvasState }) {
  const { layout, focus, highlight } = state;
  return layout.sourceHubs.map((hub) => {
    const on =
      !focus ||
      [...highlight.docs].some(
        (id) => layout.docs.get(id)?.doc.source_id === hub.id,
      );
    return (
      <g
        key={hub.id}
        opacity={dimmed(state, on)}
        {...state.interactive(
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
            isSelected(state, "source", hub.id)
              ? "stroke-neutral-900"
              : "stroke-neutral-200",
          )}
        />
        <text
          x={hub.x + 12}
          y={PANEL_Y + PANEL_H - 30}
          className="fill-neutral-400 text-[9px] tracking-[0.08em] uppercase"
        >
          {hub.eyebrow} · {hub.count} {hub.count === 1 ? "doc" : "docs"}
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
  });
}

export function GroupHubs({ state }: { state: CanvasState }) {
  const { map, layout, focus, highlight } = state;
  return layout.groupHubs.map((hub) => {
    const on =
      !focus ||
      isFocused(state, "group", hub.id) ||
      [...groupMembers(map, hub.id)].some((id) => highlight.people.has(id));
    const left = hub.x + (hub.width - HUB_W) / 2;
    return (
      <g
        key={hub.id}
        opacity={dimmed(state, on)}
        {...state.interactive(
          { kind: "group", id: hub.id },
          `${hub.eyebrow} ${hub.name}`,
        )}
      >
        <rect
          x={left}
          y={HUB_Y}
          width={HUB_W}
          height={HUB_H}
          rx={4}
          className={cn(
            "fill-white",
            isSelected(state, "group", hub.id)
              ? "stroke-neutral-900"
              : "stroke-neutral-200",
          )}
        />
        <text
          x={left + 12}
          y={HUB_Y + 18}
          className="fill-neutral-400 text-[9px] tracking-[0.08em] uppercase"
        >
          {hub.eyebrow}
        </text>
        <text
          x={left + 12}
          y={HUB_Y + 34}
          className="fill-neutral-900 text-[12px] font-medium"
        >
          {hub.name}
        </text>
        <text
          x={left + 12}
          y={HUB_Y + 47}
          className="fill-neutral-500 text-[10px]"
        >
          {hub.count} {hub.count === 1 ? "member" : "members"}
        </text>
      </g>
    );
  });
}

export function People({ state }: { state: CanvasState }) {
  const { layout, focus, highlight, me } = state;
  return [...layout.people.values()].map(({ x, person }) => {
    const on = !focus || highlight.people.has(person.id);
    const strong =
      isSelected(state, "person", person.id) ||
      isFocused(state, "person", person.id);
    const you = person.id === me.id;
    return (
      <g
        key={person.id}
        opacity={dimmed(state, on)}
        {...state.interactive(
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
  });
}

export function Documents({ state }: { state: CanvasState }) {
  const { layout, focus, highlight } = state;
  return [...layout.docs.values()].map(({ x, doc }) => {
    const on = !focus || highlight.docs.has(doc.id);
    const strong =
      isSelected(state, "document", doc.id) ||
      isFocused(state, "document", doc.id);
    const sensitive =
      doc.classification === "confidential" ||
      doc.classification === "restricted";
    const Icon = sensitive ? Lock : FileText;
    return (
      <g
        key={doc.id}
        opacity={dimmed(state, on)}
        {...state.interactive({ kind: "document", id: doc.id }, doc.title)}
      >
        <rect
          x={x - DOC_SIZE / 2}
          y={DOC_Y}
          width={DOC_SIZE}
          height={DOC_SIZE}
          rx={6}
          className={cn(
            strong ? "fill-neutral-900 stroke-neutral-900" : "fill-neutral-100",
            !strong && (sensitive ? "stroke-amber-500" : "stroke-neutral-300"),
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
  });
}
