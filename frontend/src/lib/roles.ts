/**
 * What each role can do, in plain words, for the Team page and the invite dialog (Step 41, ADR 0011).
 *
 * This is a description, not the rule: the API checks every permission itself (BUILD_PLAN §9). Each
 * row below mirrors a role list in the backend (named in the comment), so keep them in step when a
 * module's roles change.
 */
import type { Role } from "@/lib/types";

export const ROLE_ORDER: Role[] = ["requester", "buyer", "approver", "finance", "admin"];

/** Requesters are free and unlimited; the other roles each use one power seat (simulated plan). */
export const POWER_ROLES: Role[] = ["buyer", "approver", "finance", "admin"];

export const ROLE_SUMMARY: Record<Role, string> = {
  requester: "Raises purchase requests and follows them to the PO. Sees only their own requests.",
  buyer: "Turns approved requests into POs, runs RFQs and contracts, and invites suppliers.",
  approver: "Approves requests up to their approval limit and reviews suppliers, invoices and spend.",
  finance: "Owns invoices, payments, bank reconciliation, GST and month-end close.",
  admin: "Everything finance can do, plus the team, rules, workflows, forms and ERP connectors.",
};

const ALL: Role[] = ["requester", "buyer", "approver", "finance", "admin"];
const STAFF: Role[] = ["buyer", "approver", "finance", "admin"];
const FIN: Role[] = ["finance", "admin"];
const ADMIN: Role[] = ["admin"];

export interface Capability {
  group: string;
  label: string;
  roles: Role[];
}

export const CAPABILITIES: Capability[] = [
  { group: "Procure", label: "Raise purchase requests", roles: ALL },
  { group: "Procure", label: "Approve requests (within their limit)", roles: ["approver", "finance", "admin"] }, // rules STEP_ROLES
  { group: "Procure", label: "Draft POs and run RFQs", roles: ["buyer", "finance", "admin"] },                   // sourcing BUYER_ROLES
  { group: "Procure", label: "Edit contracts", roles: ["buyer", "finance", "admin"] },                           // contracts EDIT_ROLES
  { group: "Suppliers", label: "See suppliers, contracts and spend", roles: STAFF },                            // suppliers VIEW_ROLES
  { group: "Suppliers", label: "Invite a supplier", roles: ["buyer", "finance", "admin"] },                     // suppliers INVITER_ROLES
  { group: "Suppliers", label: "Approve a supplier's onboarding", roles: FIN },                                 // suppliers REVIEWER_ROLES
  { group: "Pay", label: "See invoices", roles: STAFF },                                                        // invoices VIEW_ROLES
  { group: "Pay", label: "Upload invoices and decide exceptions", roles: FIN },                                 // invoices WRITE_ROLES
  { group: "Pay", label: "Payments, cards, bank and GST", roles: FIN },                                         // payments, cards, bank, gst
  { group: "Controls", label: "Read the audit trail", roles: ["approver", "finance", "admin"] },                // review AUDIT_ROLES
  { group: "Controls", label: "Change rules, workflows and forms", roles: ADMIN },                              // rules/workflow_engine EDITOR_ROLES
  { group: "Workspace", label: "Connect ERPs and legal entities", roles: ADMIN },                               // connectors, entities
  { group: "Workspace", label: "Invite people and change roles", roles: ADMIN },                                // team
];

/** Segregation of duties (BUILD_PLAN §9): true for every role, and no workflow can switch them off. */
export const SOD_RULES: string[] = [
  "Nobody approves their own request, or a request they completed as the buyer.",
  "One person can't approve two steps of the same request.",
  "An approval above a person's limit is refused.",
  "Whoever uploaded or edited an invoice can't approve its exception.",
  "Whoever invited a supplier can't approve its onboarding.",
  "Nobody changes their own role or approval limit, and the last admin can't be removed.",
];
