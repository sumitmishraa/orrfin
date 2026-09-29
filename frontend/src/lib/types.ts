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
}

export interface Job {
  id: string;
  kind: string;
  status: "queued" | "running" | "done" | "failed";
  attempts: number;
  last_error: string | null;
  result: Record<string, { created: number; updated: number; unchanged: number }> | null;
  created_at: string;
  finished_at: string | null;
}

export interface PoSummary {
  id: string;
  erp_ref: string;
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
