import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { formatDateTime, truncateHash } from "@/lib/format";
import type { AuditEvent } from "@/lib/types";
import { cn } from "@/lib/utils";

export function AuditEventTable({
  events,
  selectedId,
  onSelect,
}: {
  events: AuditEvent[];
  selectedId: string | null;
  onSelect: (eventId: string) => void;
}) {
  return (
    <Table>
      <THead>
        <TR>
          <TH>Seq</TH>
          <TH>When</TH>
          <TH>Actor</TH>
          <TH>Action</TH>
          <TH>Subject</TH>
          <TH>Hash</TH>
        </TR>
      </THead>
      <TBody>
        {events.map((event) => (
          <TR
            key={event.id}
            onClick={() => onSelect(event.id)}
            className={cn(
              "cursor-pointer hover:bg-slate-50",
              event.id === selectedId && "bg-sky-50 hover:bg-sky-50",
            )}
          >
            <TD className="font-mono text-xs">{event.seq}</TD>
            <TD className="text-xs whitespace-nowrap">
              {formatDateTime(event.occurred_at)}
            </TD>
            <TD>{event.actor_id}</TD>
            <TD>
              {/* Keyboard-focusable; its click bubbles to the row's onClick. */}
              <button
                type="button"
                className="font-medium text-sky-700 hover:underline"
              >
                {event.action}
              </button>
            </TD>
            <TD className="text-xs">
              {event.subject_type
                ? `${event.subject_type}:${event.subject_id ?? ""}`
                : "—"}
            </TD>
            <TD className="font-mono text-xs text-slate-400" title={event.hash}>
              {truncateHash(event.hash, 10)}
            </TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}
