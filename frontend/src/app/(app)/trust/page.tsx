/**
 * Trust page (BUILD_PLAN §13 "Say", §2 system of record, §9 controls; PROMPTS Step 10).
 * The wording follows §13 exactly; it must never claim "fully compliant" or "no data leaves India".
 */
import Link from "next/link";
import { Bot, Database, FileLock2, ScrollText, ShieldCheck, UserCheck } from "lucide-react";

import { PageHeader, Panel } from "@/components/page";

const ITEMS = [
  {
    icon: ShieldCheck, title: "What this is",
    body: "Controlled prototype on synthetic data; draft-only; not production.",
  },
  {
    icon: Bot, title: "Where the AI runs",
    body: "Document AI runs on AWS Bedrock; inference may be processed outside India, and before pilots we will choose a routing that meets each customer's requirement. The AI only reads invoices and explains results. It never decides a match: fixed, versioned rules do.",
  },
  {
    icon: Database, title: "Read-only from the ERP",
    body: "Vendors, purchase orders and goods receipts belong to ERPNext. Orrfin mirrors them and never changes them.",
  },
  {
    icon: FileLock2, title: "Draft-only into the ERP",
    body: "Orrfin writes only draft purchase orders and draft bills, exactly once each. A person submits them inside ERPNext. No payments, no GST filing, no ledger posting.",
  },
  {
    icon: UserCheck, title: "Who approved what",
    body: "Every approval is made by a named person. The server enforces segregation of duties: nobody approves their own request, the buyer who completed a request cannot approve it, the person who uploaded or edited an invoice cannot approve it, and nobody approves above their limit.",
  },
  {
    icon: ScrollText, title: "A history that cannot be quietly changed",
    body: "Every change is recorded with who and when, in the same database transaction as the change. Records are hash-chained: editing any past event breaks the chain, and the Audit page shows it.",
  },
];

export default function TrustPage() {
  return (
    <>
      <PageHeader title="Trust" description="What Orrfin does, what it never does, and how you can check." />
      <div className="grid gap-4 md:grid-cols-2">
        {ITEMS.map(({ icon: Icon, title, body }) => (
          <Panel key={title}>
            <h2 className="flex items-center gap-2 text-base font-semibold text-heading">
              <Icon className="size-5 text-brand-bright" aria-hidden /> {title}
            </h2>
            <p className="mt-2 text-sm leading-relaxed">{body}</p>
          </Panel>
        ))}
      </div>
      <p className="mt-6 text-sm text-muted-foreground">
        Check it yourself: open the <Link href="/audit" className="text-primary hover:underline">Audit</Link> page
        and press “Verify chain” on any invoice or request.
      </p>
    </>
  );
}
