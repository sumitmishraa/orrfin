/**
 * Shapes returned by the Orrfin API (mirrors the backend schemas.py and router files).
 * Money, quantities and rates are decimal strings, never numbers.
 */

export type Role = "requester" | "buyer" | "approver" | "finance" | "admin";

export interface Me {
  id: string;
  org_id: string;
  email: string;
  full_name: string;
  role: Role;
  approval_limit: string;
}

export interface Category {
  id: string;
  name: string;
  buyer_id: string | null;
}

export interface UserRef {
  id: string;
  full_name: string;
  role: Role;
}

export interface Vendor {
  id: string;
  erp_ref: string;
  name: string;
  gstin: string | null;
  state_code: string | null;
  erp_modified: string;
}

export type RequestStatus =
  | "draft"
  | "submitted"
  | "with_buyer"
  | "in_approval"
  | "returned"
  | "approved"
  | "rejected"
  | "po_drafted"
  | "po_open"
  | "cancelled";

export interface RequestSummary {
  id: string;
  number: number;
  title: string;
  status: RequestStatus;
  amount: string;
  currency: string;
  category_name: string;
  requester_name: string;
  buyer_name: string | null;
  needed_by: string | null;
  created_at: string;
  updated_at: string;
  waiting_on: string | null;
}

export interface RequestLine {
  id: string;
  line_no: number;
  description: string;
  item_code: string | null;
  qty: string;
  est_rate: string;
  amount: string;
  hsn: string | null;
}

export interface ApprovalStep {
  step: number;
  required_role: string;
  approver_id: string | null;
  approver_name: string | null;
  decision: "approve" | "reject" | "return" | null;
  reason: string | null;
  decided_at: string | null;
}

export interface TimelineEvent {
  seq: number;
  action: string;
  actor_name: string | null;
  at: string;
  payload: Record<string, unknown>;
}

export interface AllowedActions {
  edit: boolean;
  submit: boolean;
  assign_buyer: boolean;
  buyer_edit: boolean;
  send_for_approval: boolean;
  decide_step: number | null;
  can_approve: boolean;
  approve_blocked_reason: string | null;
}

export interface RequestDetail extends RequestSummary {
  justification: string;
  cost_center: string;
  category_id: string;
  requested_by: string;
  assigned_buyer_id: string | null;
  vendor_id: string | null;
  vendor_name: string | null;
  suggested_vendor_id: string | null;
  suggested_vendor_name: string | null;
  completed_by_id: string | null;
  approval_round: number;
  ready_for_po: boolean;
  lines: RequestLine[];
  current_steps: ApprovalStep[];
  timeline: TimelineEvent[];
  allowed: AllowedActions;
  po_sync: ErpSync | null; // Step 15: the draft PO in the ERP
  po_sync_note: string | null; // why an approved request was not sent to the ERP
}

export interface SyncCounts {
  created: number;
  updated: number;
  unchanged: number;
}

/** Job results: an ERP pull returns counts per record type; "Prepare demo data" returns a SeedReport. */
export interface JobResult {
  vendors?: SyncCounts;
  purchase_orders?: SyncCounts;
  receipts?: SyncCounts;
  erp?: string;
  created?: Record<string, number>;
  existing?: Record<string, number>;
  notes?: string[];
}

export interface Job {
  id: string;
  kind: string;
  status: "queued" | "running" | "done" | "failed";
  attempts: number;
  last_error: string | null;
  result: JobResult | null;
  created_at: string;
  finished_at: string | null;
}

// --- Invoices (Steps 7-9) ---------------------------------------------------------------------

export type InvoiceStatus =
  | "extracting" | "needs_review" | "manual_entry" | "confirmed" | "matching"
  | "matched" | "exception" | "approved" | "rejected" | "correction_requested";

export interface InvoiceSummary {
  id: string;
  status: InvoiceStatus;
  filename: string;
  vendor_name: string | null;
  invoice_no: string | null;
  invoice_date: string | null;
  po_reference: string | null;
  total: string | null;
  outcome: "matched" | "exception" | "stale" | null;
  amount_at_risk: string | null;
  risk_score: number | null;
  created_at: string;
}

export interface InvoiceLine {
  line_no: number;
  description: string;
  item_code: string | null;
  hsn: string | null;
  qty: string;
  rate: string;
  amount: string;
  po_line_id: string | null;
  pairing_method: string | null;
}

export interface RuleResult {
  rule: string;
  code: string;
  status: "pass" | "fail" | "warn" | "info";
  message: string;
  amount_at_risk: string;
  line_no: number | null;
}

export interface MatchView {
  outcome: "matched" | "exception" | "stale";
  matched_outcome: "matched" | "exception";
  amount_at_risk: string;
  risk_score: number;
  rule_set_version: string;
  rule_results: RuleResult[];
  explanation: string | null;
  explanation_source: string | null;
  matched_at: string;
  po: { id: string; erp_ref: string; status: string; vendor_name: string | null; vendor_gstin: string | null } | null;
  unpaired_lines: number[];
  comparison: {
    po_line: number; item_code: string; description: string; po_qty: string; po_rate: string;
    received: string; invoiced_before: string; invoice_qty: string | null; invoice_rate: string | null;
  }[];
}

export interface InvoiceDetail extends InvoiceSummary {
  vendor_gstin: string | null;
  buyer_gstin: string | null;
  place_of_supply: string | null;
  currency: string;
  subtotal: string | null;
  cgst: string | null;
  sgst: string | null;
  igst: string | null;
  uploaded_by_name: string;
  confirmed_by_name: string | null;
  confirmed_at: string | null;
  extraction_error: string | null;
  lines: InvoiceLine[];
  issues: { field: string; code: string; message: string }[];
  evidence: Record<string, { quote: string; page: number }>;
  extraction: { model_id: string; prompt_version: string; confidence: string | null; finished_at: string | null; simulated: boolean } | null;
  edits: { field: string; old: string | null; new: string | null; edited_by_name: string; at: string }[];
  timeline: TimelineEvent[];
  allowed: { edit: boolean; confirm: boolean; decide: boolean; approve_blocked_reason: string | null };
  match: MatchView | null;
  decisions: { decision: string; reason: string | null; reviewer_name: string; at: string }[];
  erp_sync: ErpSync | null; // Step 14: the draft bill in the ERP
  erp_sync_note: string | null; // why an approved invoice was not sent to the ERP
}

export interface AuditEntity {
  entity_type: "invoice" | "purchase_request";
  entity_id: string;
  label: string;
  status: string;
  events: number;
  last_action: string;
}

export interface AuditTrail {
  entity_type: string;
  entity_id: string;
  label: string;
  chain_valid: boolean;
  events: (TimelineEvent & { hash: string })[];
}

export interface GraphNode {
  kind: string;
  label: string;
  state: "done" | "current" | "blocked" | "pending" | "skipped";
  detail: string;
  href: string | null;
}

export interface PoSummary {
  id: string;
  erp_ref: string;
  po_number: string | null;
  vendor_name: string | null;
  po_date: string | null;
  schedule_date: string | null;
  status: string;
  origin: string;
  grand_total: string;
  qty_ordered: string;
  qty_received: string;
}

export interface PoLine {
  id: string;
  line_no: number;
  item_code: string;
  description: string;
  hsn: string | null;
  uom: string | null;
  qty: string;
  qty_received: string;
  rate: string;
  amount: string;
  tax_rate: string;
}

export interface PoDetail extends PoSummary {
  vendor_gstin: string | null;
  currency: string;
  net_total: string;
  tax_total: string;
  erp_modified: string;
  lines: PoLine[];
  receipts: { erp_ref: string; posting_date: string | null; status: string }[];
}

// --- ERP connectors (Step 12) -----------------------------------------------------------------

export type ErpLabel = "live" | "sandbox" | "simulated";

export interface Capabilities {
  label: ErpLabel;
  can_read: boolean;
  can_write_bill: boolean;
  can_write_po: boolean;
  draft_bill_means: string;
  draft_po_means: string;
  write_note: string;
}

export interface CheckStep {
  name: string;
  ok: boolean;
  detail: string;
}

export interface ConnectionCheck {
  ok: boolean;
  steps: CheckStep[];
}

export interface ConnectionInfo {
  id: string;
  mode: "simulated" | "live";
  label: ErpLabel;
  is_active: boolean;
  status: "not_connected" | "connected" | "error";
  last_checked_at: string | null;
  last_check: ConnectionCheck | null;
  last_error: string | null;
  /** Saved values: never a secret, only whether it is set and its last four characters. */
  fields: Record<string, { set: boolean; hint: string }>;
}

export interface CredentialField {
  name: string;
  label: string;
  secret: boolean;
  help: string;
  required: boolean;
  placeholder: string;
}

export interface ConnectorCard {
  system: string;
  name: string;
  segment: string;
  live_label: ErpLabel;
  built: boolean;
  step: number;
  signup: string;
  note: string;
  has_live_mode: boolean;
  fields: CredentialField[];
  capabilities: Capabilities | null;
  simulated: ConnectionInfo | null;
  live: ConnectionInfo | null;
}

export interface ActiveErp {
  id: string;
  system: string;
  name: string;
  mode: "simulated" | "live";
  label: ErpLabel;
  capabilities: Capabilities | null;
}

/** One document's ERP write-back (BUILD_PLAN §8 outbox). */
export interface ErpSync {
  id: string;
  state: "PENDING" | "SENT" | "CONFIRMED" | "FAILED" | "UNKNOWN";
  erp_doc_name: string | null;
  attempts: number;
  last_error: string | null;
  erp: string;
  label: ErpLabel;
  doc_type: "purchase_invoice" | "purchase_order";
  /** File-based ERPs (BUSY): where to download the import file a person loads into the ERP. */
  import_file_url: string | null;
}
