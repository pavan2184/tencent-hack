/** State shared by every layer of the SVG map. */

import type { KeyboardEvent } from "react";
import type { AccessMap, AccessMapEdge, Principal } from "@/lib/types";
import type { Highlight } from "./highlight";
import type { Layout, NodeRef } from "./layout";

export interface InteractiveProps {
  role: "button";
  tabIndex: number;
  "aria-label": string;
  "aria-pressed": boolean;
  className: string;
  onClick: () => void;
  onKeyDown: (event: KeyboardEvent) => void;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
  onFocus: () => void;
  onBlur: () => void;
}

export interface CanvasState {
  map: AccessMap;
  layout: Layout;
  me: Principal;
  /** Edges left after the rule filter. */
  edges: AccessMapEdge[];
  focus: NodeRef | null;
  selected: NodeRef | null;
  highlight: Highlight;
  interactive: (node: NodeRef, label: string) => InteractiveProps;
}

/** Faded when something else is focused. */
export function dimmed(state: CanvasState, on: boolean): number {
  return state.focus && !on ? 0.18 : 1;
}

export function isSelected(
  state: CanvasState,
  kind: NodeRef["kind"],
  id: string,
): boolean {
  return state.selected?.kind === kind && state.selected.id === id;
}

export function isFocused(
  state: CanvasState,
  kind: NodeRef["kind"],
  id: string,
): boolean {
  return state.focus?.kind === kind && state.focus.id === id;
}
