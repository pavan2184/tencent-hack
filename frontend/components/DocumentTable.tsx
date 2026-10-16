import Link from "next/link";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { formatDateTime } from "@/lib/format";
import type { Document } from "@/lib/types";
import { ClassificationBadge, FreshnessBadge } from "./StatusBadge";

export function DocumentTable({ documents }: { documents: Document[] }) {
  return (
    <Table>
      <THead>
        <TR>
          <TH>Title</TH>
          <TH>Source</TH>
          <TH>Classification</TH>
          <TH>Freshness</TH>
          <TH>Updated</TH>
        </TR>
      </THead>
      <TBody>
        {documents.map((document) => (
          <TR key={document.id}>
            <TD>
              <Link
                href={`/documents/${encodeURIComponent(document.id)}`}
                className="font-medium link"
              >
                {document.title}
              </Link>
              <p className="text-xs text-neutral-400">{document.slug}</p>
            </TD>
            <TD>
              <p>{document.source_kind}</p>
              <p className="text-xs text-neutral-400">{document.source_id}</p>
            </TD>
            <TD>
              <ClassificationBadge value={document.classification} />
            </TD>
            <TD>
              <FreshnessBadge value={document.freshness_status} />
            </TD>
            <TD className="text-xs whitespace-nowrap">
              {formatDateTime(
                document.provider_modified_at ?? document.updated_at,
              )}
            </TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}
