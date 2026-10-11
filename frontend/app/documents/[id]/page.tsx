import { DocumentDetailView } from "@/components/DocumentDetailView";

export default async function DocumentPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <DocumentDetailView id={id} />;
}
