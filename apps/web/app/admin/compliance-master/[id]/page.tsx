import ComplianceTemplateBuilder from "@/components/compliance-template-builder";
export default async function ComplianceTemplatePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ComplianceTemplateBuilder id={id} />;
}
