/**
 * Invoices: placeholder until invoice upload and AI extraction arrive (PROMPTS Step 7).
 */
import { EmptyState, PageHeader } from "@/components/page";

export default function InvoicesPage() {
  return (
    <>
      <PageHeader title="Invoices" description="Upload supplier invoices, check them against PO and receipt." />
      <EmptyState>Invoice upload and matching arrive in a later step (PROMPTS Steps 7–9).</EmptyState>
    </>
  );
}
