import { Suspense } from "react";
import { AuditView } from "@/components/AuditView";
import { PageHeader } from "@/components/PageHeader";
import { LoadingState } from "@/components/StateViews";

export default function AuditPage() {
  return (
    <div>
      <PageHeader
        title="Audit trail"
        description="Hash-chained record of every question, retrieval, access decision, and change. Select an ask to reconstruct it."
      />
      {/* useSearchParams (?event=) needs a Suspense boundary for static rendering. */}
      <Suspense fallback={<LoadingState />}>
        <AuditView />
      </Suspense>
    </div>
  );
}
