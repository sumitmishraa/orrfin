/**
 * Audit: placeholder for the Control Graph (PROMPTS Step 10). Each request page already shows
 * its own hash-chained audit trail.
 */
import { EmptyState, PageHeader } from "@/components/page";

export default function AuditPage() {
  return (
    <>
      <PageHeader title="Audit" description="Every state change, hash-chained and append-only." />
      <EmptyState>
        The Control Graph arrives in a later step. Until then, open any request to see its audit trail.
      </EmptyState>
    </>
  );
}
