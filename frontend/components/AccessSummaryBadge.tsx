import { ShieldCheck } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { formatDateTime } from "@/lib/format";
import type { AccessSummary } from "@/lib/types";

/** Shows how many documents the asker was allowed to see. Never shows (or derives) a denied count. */
export function AccessSummaryBadge({ summary }: { summary: AccessSummary }) {
  return (
    <Badge
      tone="info"
      title={`Evaluated ${formatDateTime(summary.evaluated_at)} for ${summary.principal_id}`}
    >
      <ShieldCheck className="size-3.5" aria-hidden />
      {summary.allowed_count}{" "}
      {summary.allowed_count === 1 ? "document" : "documents"} allowed · policy{" "}
      {summary.policy_version}
    </Badge>
  );
}
