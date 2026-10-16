"use client";

import type { KeyboardEvent } from "react";
import { Card } from "@/components/ui/card";
import type { AccessMap, AccessMapEdge, Principal } from "@/lib/types";
import type { CanvasState, InteractiveProps } from "./canvas";
import type { Highlight } from "./highlight";
import { HEIGHT, type Layout, type NodeRef } from "./layout";
import { AccessEdges, EdgeLabels, MembershipLines } from "./MapEdges";
import { Documents, GroupHubs, People, SourcePanels } from "./MapNodes";

function onActivate(handler: () => void) {
  return (event: KeyboardEvent) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      handler();
    }
  };
}

/** The SVG map. Layers are drawn back to front so labels stay on top. */
export function MapCanvas({
  map,
  layout,
  me,
  edges,
  focus,
  selected,
  highlight,
  onSelect,
  onHover,
}: {
  map: AccessMap;
  layout: Layout;
  me: Principal;
  edges: AccessMapEdge[];
  focus: NodeRef | null;
  selected: NodeRef | null;
  highlight: Highlight;
  onSelect: (node: NodeRef | null) => void;
  onHover: (node: NodeRef | null) => void;
}) {
  function interactive(node: NodeRef, label: string): InteractiveProps {
    const active = selected?.kind === node.kind && selected.id === node.id;
    const toggle = () => onSelect(active ? null : node);
    return {
      role: "button",
      tabIndex: 0,
      "aria-label": label,
      "aria-pressed": active,
      className: "cursor-pointer outline-none",
      onClick: toggle,
      onKeyDown: onActivate(toggle),
      onMouseEnter: () => onHover(node),
      onMouseLeave: () => onHover(null),
      onFocus: () => onHover(node),
      onBlur: () => onHover(null),
    };
  }

  const state: CanvasState = {
    map,
    layout,
    me,
    edges,
    focus,
    selected,
    highlight,
    interactive,
  };

  return (
    <Card className="overflow-x-auto bg-neutral-50">
      <svg
        viewBox={`0 0 ${layout.width} ${HEIGHT}`}
        className="block h-auto w-full min-w-[56rem] select-none"
        role="img"
        aria-label="Access map: people and groups above, documents grouped by source below, one line per allowed read"
        onClick={(event) => {
          if (event.target === event.currentTarget) onSelect(null);
        }}
      >
        <MembershipLines state={state} />
        <SourcePanels state={state} />
        <AccessEdges state={state} />
        <GroupHubs state={state} />
        <People state={state} />
        <Documents state={state} />
        <EdgeLabels state={state} />
      </svg>
    </Card>
  );
}
