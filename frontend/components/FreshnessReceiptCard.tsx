import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import {
  formatDateTime,
  formatDuration,
  humanize,
  truncateHash,
} from "@/lib/format";
import type { FreshnessReceipt, ReceiptItem } from "@/lib/types";
import { cn } from "@/lib/utils";
import { EmptyState } from "./StateViews";
import { FreshnessBadge } from "./StatusBadge";

export function FreshnessReceiptCard({
  receipt,
}: {
  receipt: FreshnessReceipt | null;
}) {
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Freshness receipt</CardTitle>
          {receipt && (
            <CardDescription>
              <span className="font-mono" title={receipt.receipt_hash}>
                {truncateHash(receipt.receipt_hash)}
              </span>{" "}
              · {formatDateTime(receipt.created_at)}
            </CardDescription>
          )}
        </div>
        {receipt && <FreshnessBadge value={receipt.overall_status} />}
      </CardHeader>
      <CardContent className="px-2 py-2">
        {!receipt || receipt.evidence_items.length === 0 ? (
          <div className="px-3">
            <EmptyState>No evidence was evaluated for freshness.</EmptyState>
          </div>
        ) : (
          <Table>
            <THead>
              <TR>
                <TH>Evidence</TH>
                <TH>Status</TH>
                <TH>Age / budget</TH>
                <TH>Verified</TH>
                <TH>Used</TH>
              </TR>
            </THead>
            <TBody>
              {receipt.evidence_items.map((item) => (
                <ReceiptRow
                  key={`${item.source_id}:${item.external_object_id}`}
                  item={item}
                />
              ))}
            </TBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function ReceiptRow({ item }: { item: ReceiptItem }) {
  const overBudget =
    item.age_seconds !== null &&
    item.budget_seconds !== null &&
    item.age_seconds > item.budget_seconds;
  return (
    <TR>
      <TD>
        <p className="font-medium text-slate-900">
          {item.page_slug ?? item.external_object_id}
        </p>
        <p className="text-xs text-slate-500">
          {item.source_id}
          {item.provider_version && ` · version ${item.provider_version}`}
        </p>
      </TD>
      <TD>
        <FreshnessBadge value={item.freshness_status} />
      </TD>
      <TD
        className={cn(
          "whitespace-nowrap",
          overBudget && "font-medium text-amber-700",
        )}
      >
        {formatDuration(item.age_seconds)} /{" "}
        {formatDuration(item.budget_seconds)}
      </TD>
      <TD className="text-xs">
        {item.verification_result ? humanize(item.verification_result) : "—"}
      </TD>
      <TD className="text-xs">
        {item.safe_to_use ? (
          <span className="text-emerald-700">yes</span>
        ) : (
          <span className="text-amber-700">omitted</span>
        )}
      </TD>
    </TR>
  );
}
