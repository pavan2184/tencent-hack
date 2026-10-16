"use client";

import Link from "next/link";
import { AccessMapView } from "@/components/access-map/AccessMapView";
import { PageHeader } from "@/components/PageHeader";
import { usePersona } from "@/components/PersonaProvider";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateViews";
import { Card, CardContent } from "@/components/ui/card";
import { canManage } from "@/lib/roles";

export default function AccessMapPage() {
  const { me, meError, meLoading } = usePersona();

  return (
    <div className="space-y-6">
      <PageHeader
        title="Access map,"
        accent="every line has a reason."
        description={
          <>
            Who can read each document in your view, and the policy rule that
            allows it. Source access caps you too, so documents you cannot read
            never appear. Manage grants on{" "}
            <Link href="/access" className="link">
              Access
            </Link>
            .
          </>
        }
      />
      {meError ? (
        <ErrorState error={meError} />
      ) : !me || meLoading ? (
        <LoadingState />
      ) : canManage(me) ? (
        <AccessMapView me={me} />
      ) : (
        <Card>
          <CardContent>
            <EmptyState>
              The access map is for managers and admins. Switch to John Tan or
              Root Admin.
            </EmptyState>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
