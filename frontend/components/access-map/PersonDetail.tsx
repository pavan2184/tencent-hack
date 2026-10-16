import { Card, CardContent } from "@/components/ui/card";
import type { AccessMap, Principal } from "@/lib/types";
import type { Person } from "./layout";
import { RuleBadge } from "./RuleBadge";

export function PersonDetail({
  map,
  me,
  person,
}: {
  map: AccessMap;
  me: Principal;
  person: Person;
}) {
  const docs = new Map(map.documents.map((d) => [d.id, d]));
  const edges = map.edges.filter((e) => e.principal_id === person.id);
  return (
    <Card>
      <CardContent className="space-y-4">
        <div>
          <p className="font-medium text-neutral-900">
            {person.display_name}
            {person.id === me.id && (
              <span className="text-neutral-400"> · you</span>
            )}
          </p>
          <p className="text-xs text-neutral-500">
            {[...person.roles, ...person.groups.map((g) => `group ${g}`)].join(
              " · ",
            ) || "no roles or groups"}
          </p>
        </div>
        <p className="text-xs text-neutral-500">
          Can read {edges.length} of the {map.documents.length} documents in
          your view
        </p>
        <ul className="grid gap-x-10 lg:grid-cols-2">
          {edges.map((edge) => (
            <li
              key={edge.document_id}
              className="flex items-start justify-between gap-3 border-b border-neutral-200 py-2"
            >
              <span className="min-w-0 text-sm">
                {docs.get(edge.document_id)?.title}
                {edge.via.length > 0 && (
                  <span className="block text-xs text-accent-strong">
                    via{" "}
                    {edge.via
                      .map((v) => `${v.subject_type} ${v.subject_id}`)
                      .join(", ")}
                  </span>
                )}
              </span>
              <RuleBadge rule={edge.rule} />
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
