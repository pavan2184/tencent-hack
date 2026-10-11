import { Badge, type BadgeTone } from "@/components/ui/badge";
import { humanize } from "@/lib/format";

function StatusBadge({
  value,
  tones,
  title,
}: {
  value: string | null | undefined;
  tones: Record<string, BadgeTone>;
  title?: string;
}) {
  if (!value) return <span className="text-slate-400">—</span>;
  return (
    <Badge tone={tones[value] ?? "neutral"} title={title}>
      {humanize(value)}
    </Badge>
  );
}

type ValueProps = { value: string | null | undefined; title?: string };

const supportTones: Record<string, BadgeTone> = {
  supported: "success",
  partially_supported: "warning",
  unsupported: "neutral",
  contradicted: "danger",
  not_checked: "neutral",
};

const freshnessTones: Record<string, BadgeTone> = {
  fresh: "success",
  stale: "warning",
  mixed: "warning",
  unknown: "neutral",
  not_required: "neutral",
  not_searchable: "info",
  deleted: "danger",
};

const classificationTones: Record<string, BadgeTone> = {
  public: "neutral",
  internal: "info",
  confidential: "warning",
  restricted: "danger",
};

const verdictTones: Record<string, BadgeTone> = {
  grounded: "success",
  partially_grounded: "warning",
  ungrounded: "danger",
  abstained: "neutral",
};

const decisionTones: Record<string, BadgeTone> = {
  allow: "success",
  deny: "danger",
  pending: "warning",
  approved: "success",
  denied: "danger",
};

export function SupportBadge(props: ValueProps) {
  return <StatusBadge {...props} tones={supportTones} />;
}

export function FreshnessBadge(props: ValueProps) {
  return <StatusBadge {...props} tones={freshnessTones} />;
}

export function ClassificationBadge(props: ValueProps) {
  return <StatusBadge {...props} tones={classificationTones} />;
}

export function VerdictBadge(props: ValueProps) {
  return <StatusBadge {...props} tones={verdictTones} />;
}

export function DecisionBadge(props: ValueProps) {
  return <StatusBadge {...props} tones={decisionTones} />;
}
