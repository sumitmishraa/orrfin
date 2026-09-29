"use client";

/**
 * New request (PROMPTS Step 5 intake form). "Submit" creates the request and routes it to the
 * category's buyer in one go; "Save as draft" keeps it private until the requester submits.
 */
import { useRouter } from "next/navigation";

import { PageHeader } from "@/components/page";
import { RequestForm, type RequestFormValues } from "@/components/request-form";
import { post } from "@/lib/api";
import type { RequestDetail } from "@/lib/types";

export default function NewRequestPage() {
  const router = useRouter();

  async function create(values: RequestFormValues): Promise<RequestDetail> {
    return post<RequestDetail>("/requests", values);
  }

  return (
    <>
      <PageHeader title="New request" description="Describe what you need. Your category's buyer takes it from there." />
      <RequestForm
        submitLabel="Submit request"
        onSave={async (values) => {
          const created = await create(values);
          await post(`/requests/${created.id}/submit`);
          router.push(`/requests/${created.id}`);
        }}
        secondaryLabel="Save as draft"
        onSecondary={async (values) => {
          const created = await create(values);
          router.push(`/requests/${created.id}`);
        }}
      />
    </>
  );
}
