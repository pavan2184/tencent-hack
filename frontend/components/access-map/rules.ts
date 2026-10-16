/** Rule families: how each allow rule is drawn and explained on the map. */

export type Family = "source" | "owner" | "admin" | "grant" | "other";

export const FAMILIES: Record<
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

export const FAMILY_ORDER: Family[] = [
  "source",
  "owner",
  "admin",
  "grant",
  "other",
];

export function familyOf(rule: string): Family {
  if (rule.startsWith("R8:")) return "source";
  if (rule.startsWith("R3:")) return "owner";
  if (rule.startsWith("R4:")) return "admin";
  if (rule.startsWith("R5:")) return "grant";
  return "other";
}
