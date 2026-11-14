"use client";

/**
 * Approval workflow builder (BUILD_PLAN v3.0 change 39, ADR 0010). Admins only; the API refuses others.
 *
 * The builder shows a workflow as an ordered list of approval steps, each with an optional
 * "only when" rule. That is easier to read than a diagram and covers the common cases. It is
 * turned into the engine's general definition (lib below) before it is checked, tested or saved.
 * The server does all checking: this page only shows what it answers.
 *
 * Nothing here switches a workflow on by accident: Save makes a draft, Test changes nothing,
 * and Publish is a separate button that the server may refuse (for example when a version asks
 * for fewer approvals, a second admin must publish it).
 */
import { useState } from "react";
import { ArrowDown, CircleCheck, FlaskConical, Plus, Save, Send, Trash2 } from "lucide-react";

import { ErrorNotice, Loading, PageHeader, Panel } from "@/components/page";
import { Button } from "@/components/ui/button";
import { api, post } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useApi } from "@/lib/use-api";

const WORKFLOW_KEY = "request-approval";
const ROLES = [
  { value: "manager", label: "The requester's manager" },
  { value: "approver", label: "Any approver" },
  { value: "finance", label: "Finance" },
  { value: "admin", label: "Admin" },
] as const;
const CONDITIONS = [
  { value: "always", label: "Always" },
  { value: "amount_above", label: "Only when the amount is above" },
  { value: "category_is", label: "Only when the category is" },
  { value: "cost_center_is", label: "Only when the cost centre is" },
] as const;

type Role = (typeof ROLES)[number]["value"];
type ConditionKind = (typeof CONDITIONS)[number]["value"];

interface StepCard {
  role: Role;
  label: string;
  condition: ConditionKind;
  value: string;
}

interface DefinitionNode {
  id: string;
  kind: string;
  role?: string;
  label?: string;
  next?: string;
  then?: string;
  else?: string;
  when?: { field: string; op: string; value: string | string[] };
}
interface Definition { subject: string; start: string; nodes: DefinitionNode[] }
interface VersionRow { id: string; number: number; status: string; drafted_by_ai: boolean; created_at: string; definition: Definition }
interface WorkflowDetail { id: string; active_version_id: string | null; versions: VersionRow[] }
interface Simulation { problems: string[]; approvals: { role: string; label: string | null; approver_name: string | null }[] }

const STARTER: StepCard[] = [
  { role: "manager", label: "", condition: "always", value: "" },
  { role: "finance", label: "", condition: "amount_above", value: "50000.00" },
];

/** Ordered cards → the engine's definition: a card with a rule becomes a condition step followed by its approval. */
function toDefinition(cards: StepCard[]): Definition {
  const firstNodeOf = (index: number) =>
    index >= cards.length ? "end" : cards[index].condition === "always" ? `step${index + 1}` : `when${index + 1}`;
  const nodes: DefinitionNode[] = [];
  cards.forEach((card, index) => {
    const approvalId = `step${index + 1}`;
    const after = firstNodeOf(index + 1);
    if (card.condition !== "always") {
      const when =
        card.condition === "amount_above" ? { field: "amount", op: ">", value: card.value.trim() }
        : card.condition === "category_is" ? { field: "category", op: "in", value: [card.value] }
        : { field: "cost_center", op: "==", value: card.value.trim() };
      nodes.push({ id: `when${index + 1}`, kind: "condition", when, then: approvalId, else: after });
    }
    nodes.push({ id: approvalId, kind: "approval", role: card.role, next: after,
                 ...(card.label.trim() ? { label: card.label.trim() } : {}) });
  });
  return { subject: "request", start: firstNodeOf(0), nodes };
}

/** The reverse, for a definition this builder made. Anything else (e.g. drafted another way) returns null. */
function toCards(definition: Definition): StepCard[] | null {
  const byId = new Map(definition.nodes.map((node) => [node.id, node]));
  const cards: StepCard[] = [];
  let current = definition.start;
  while (current !== "end") {
    let node = byId.get(current);
    let condition: ConditionKind = "always";
    let value = "";
    if (node?.kind === "condition" && node.when && node.then) {
      const { field, op, value: raw } = node.when;
      if (field === "amount" && op === ">" && typeof raw === "string") [condition, value] = ["amount_above", raw];
      else if (field === "category" && op === "in" && Array.isArray(raw) && raw.length === 1) [condition, value] = ["category_is", raw[0]];
      else if (field === "cost_center" && op === "==" && typeof raw === "string") [condition, value] = ["cost_center_is", raw];
      else return null;
      const skipTo = node.else;
      node = byId.get(node.then);
      if (node?.next !== skipTo) return null;
    }
    if (node?.kind !== "approval" || !node.role || !node.next || !ROLES.some((r) => r.value === node.role)) return null;
    cards.push({ role: node.role as Role, label: node.label ?? "", condition, value });
    current = node.next;
    if (cards.length > 50) return null;
  }
  return cards;
}

const inputClass = "h-9 w-full rounded-lg border border-border bg-white px-3 text-sm outline-none focus-visible:border-primary focus-visible:ring-3 focus-visible:ring-ring/30";

function roleLabel(role: string): string {
  return ROLES.find((r) => r.value === role)?.label ?? "A named reviewer";
}

export default function WorkflowBuilderPage() {
  const list = useApi<{ id: string; key: string }[]>("/workflow-definitions");
  const workflowId = list.data?.find((w) => w.key === WORKFLOW_KEY)?.id ?? null;
  const detail = useApi<WorkflowDetail>(workflowId ? `/workflow-definitions/${workflowId}` : null);
  const rules = useApi<{ categories: { name: string }[] }>("/rules");

  const [edited, setEdited] = useState<StepCard[] | null>(null);
  const [sample, setSample] = useState({ amount: "75000.00", category: "", cost_center: "" });
  const [simulation, setSimulation] = useState<Simulation | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [described, setDescribed] = useState("");

  if (list.loading || (workflowId && detail.loading)) return <Loading />;
  if (list.error) return <ErrorNotice message={list.error} />;

  const versions = detail.data?.versions ?? [];
  const latest = versions[0];
  const published = versions.find((v) => v.id === detail.data?.active_version_id);
  const loadedCards = latest ? toCards(latest.definition) : STARTER;
  const cards = edited ?? loadedCards ?? STARTER;
  const categories = rules.data?.categories.map((c) => c.name) ?? [];

  function change(index: number, patch: Partial<StepCard>) {
    setEdited(cards.map((card, i) => (i === index ? { ...card, ...patch } : card)));
    setSimulation(null);
    setNotice(null);
  }

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : "That did not work. Try again.");
    } finally {
      setBusy(false);
    }
  }

  const test = () => run(async () => {
    const facts = Object.fromEntries(Object.entries(sample).filter(([, v]) => v.trim() !== ""));
    const result = await post<Simulation>("/workflow-definitions/simulate", { definition: toDefinition(cards), facts });
    setSimulation(result);
    setProblems(result.problems);
  });

  const save = () => run(async () => {
    const saved = await post<{ number: number; problems: string[] }>("/workflow-definitions", {
      key: WORKFLOW_KEY, name: "Request approval", definition: toDefinition(cards),
    });
    setProblems(saved.problems);
    setEdited(null);
    setNotice(saved.problems.length
      ? `Saved as draft version ${saved.number}. Fix the problems below before it can be published.`
      : `Saved as draft version ${saved.number}. It changes nothing until it is published.`);
    await list.reload();
    await detail.reload();
  });

  const publish = (version: VersionRow) => run(async () => {
    await api(`/workflow-definitions/versions/${version.id}/publish`, { method: "POST" });
    setNotice(`Version ${version.number} is now in use for requests sent for approval from now on.`);
    await detail.reload();
  });

  return (
    <>
      <PageHeader
        title="Approval workflow"
        description="Choose who must approve a purchase request. A saved draft changes nothing; only a published version applies, and only to requests sent for approval after that."
      />
      <div className="mb-4 rounded-xl border border-border bg-white p-4 shadow-raised">
        <label htmlFor="describe" className="text-sm font-medium text-heading">Describe it in words (the workflow agent drafts the steps; you check, test and save)</label>
        <div className="mt-2 flex flex-col gap-2 sm:flex-row">
          <textarea id="describe" className={`${inputClass} min-h-16 flex-1 py-2`} value={described} onChange={(e) => setDescribed(e.target.value)}
                    placeholder="Manager approves every request. Finance approves above 50,000. Admin approves above 5 lakh." />
          <Button variant="outline" disabled={busy || described.trim().length < 3} onClick={() => run(async () => {
            const drafted = await post<{ definition: Definition; problems: string[]; not_understood: string[] }>("/agents/workflow-draft", { text: described });
            const fromWords = toCards(drafted.definition);
            if (drafted.problems.length || !fromWords) { setProblems(drafted.problems); return; }
            setEdited(fromWords);
            setSimulation(null);
            setNotice(drafted.not_understood.length ? `Drafted. Not understood: ${drafted.not_understood.join("; ")}` : "Drafted from your words. Check the steps, test, then save.");
          })}>Draft steps</Button>
        </div>
      </div>
      <div className="mb-4 flex flex-col gap-2">
        <ErrorNotice message={error} />
        {notice ? (
          <p role="status" className="flex items-start gap-2 rounded-lg border border-border bg-ice px-3 py-2 text-sm text-heading">
            <CircleCheck className="mt-0.5 size-4 shrink-0" aria-hidden /> {notice}
          </p>
        ) : null}
        {latest && loadedCards === null && edited === null ? (
          <p className="rounded-lg border border-warning/40 bg-warning/5 px-3 py-2 text-sm">
            Version {latest.number} was built in a way this screen cannot show step by step. The steps below are a fresh start; saving them makes a new draft.
          </p>
        ) : null}
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <Panel title="Steps, in order" actions={
          <Button size="sm" variant="outline" onClick={() => setEdited([...cards, { role: "finance", label: "", condition: "always", value: "" }])}>
            <Plus aria-hidden /> Add a step
          </Button>}>
          <ol className="flex flex-col gap-2">
            {cards.map((card, index) => (
              <li key={index} className="flex flex-col gap-2">
                {index > 0 ? <ArrowDown className="mx-auto size-4 text-muted-foreground" aria-hidden /> : null}
                <div className="rounded-xl border border-border bg-ice-light p-3">
                  <div className="mb-2 flex items-center justify-between">
                    <span className="text-sm font-semibold text-heading">Step {index + 1}</span>
                    <button type="button" aria-label={`Remove step ${index + 1}`} disabled={cards.length === 1}
                            onClick={() => setEdited(cards.filter((_, i) => i !== index))}
                            className="rounded-lg p-1.5 text-muted-foreground hover:bg-white hover:text-error disabled:opacity-40">
                      <Trash2 className="size-4" aria-hidden />
                    </button>
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
                      Who approves
                      <select className={inputClass} value={card.role} onChange={(e) => change(index, { role: e.target.value as Role })}>
                        {ROLES.map((role) => <option key={role.value} value={role.value}>{role.label}</option>)}
                      </select>
                    </label>
                    <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
                      Name shown on the request (optional)
                      <input className={inputClass} value={card.label} maxLength={80} placeholder="e.g. Finance approval"
                             onChange={(e) => change(index, { label: e.target.value })} />
                    </label>
                    <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
                      When this step applies
                      <select className={inputClass} value={card.condition}
                              onChange={(e) => change(index, { condition: e.target.value as ConditionKind, value: "" })}>
                        {CONDITIONS.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
                      </select>
                    </label>
                    {card.condition === "amount_above" ? (
                      <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
                        Amount (₹)
                        <input className={`${inputClass} tabular-nums`} inputMode="decimal" value={card.value} placeholder="50000.00"
                               onChange={(e) => change(index, { value: e.target.value })} />
                      </label>
                    ) : card.condition === "category_is" ? (
                      <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
                        Category
                        <select className={inputClass} value={card.value} onChange={(e) => change(index, { value: e.target.value })}>
                          <option value="">Choose a category</option>
                          {categories.map((name) => <option key={name} value={name}>{name}</option>)}
                        </select>
                      </label>
                    ) : card.condition === "cost_center_is" ? (
                      <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
                        Cost centre
                        <input className={inputClass} value={card.value} placeholder="e.g. IT-OPS"
                               onChange={(e) => change(index, { value: e.target.value })} />
                      </label>
                    ) : null}
                  </div>
                </div>
              </li>
            ))}
          </ol>
          {problems.length ? (
            <ul role="alert" className="mt-4 flex list-disc flex-col gap-1 rounded-lg border border-error/30 bg-error/5 py-2 pl-8 pr-3 text-sm text-error">
              {problems.map((problem) => <li key={problem}>{problem}</li>)}
            </ul>
          ) : null}
          <div className="mt-4 flex justify-end">
            <Button onClick={save} disabled={busy}><Save aria-hidden /> Save as draft</Button>
          </div>
        </Panel>

        <div className="flex flex-col gap-6">
          <Panel title="Test with a sample request">
            <p className="mb-3 text-sm text-muted-foreground">See who would have to approve. This changes nothing.</p>
            <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-1 xl:grid-cols-3">
              <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
                Amount (₹)
                <input className={`${inputClass} tabular-nums`} inputMode="decimal" value={sample.amount}
                       onChange={(e) => setSample({ ...sample, amount: e.target.value })} />
              </label>
              <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
                Category
                <select className={inputClass} value={sample.category} onChange={(e) => setSample({ ...sample, category: e.target.value })}>
                  <option value="">Any</option>
                  {categories.map((name) => <option key={name} value={name}>{name}</option>)}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
                Cost centre
                <input className={inputClass} value={sample.cost_center} onChange={(e) => setSample({ ...sample, cost_center: e.target.value })} />
              </label>
            </div>
            <div className="mt-3">
              <Button variant="outline" onClick={test} disabled={busy}><FlaskConical aria-hidden /> Run the test</Button>
            </div>
            {simulation && !simulation.problems.length ? (
              <ol className="mt-4 flex flex-col gap-2">
                {simulation.approvals.map((step, index) => (
                  <li key={index} className="flex items-center gap-3 rounded-lg border border-border bg-white px-3 py-2 text-sm">
                    <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-navy text-xs font-semibold text-white">{index + 1}</span>
                    <span className="min-w-0">
                      <span className="font-medium text-heading">{step.label ?? roleLabel(step.role)}</span>
                      {step.label ? <span className="text-muted-foreground"> · {step.approver_name ?? roleLabel(step.role)}</span> : null}
                    </span>
                  </li>
                ))}
              </ol>
            ) : null}
          </Panel>

          <Panel title="Versions">
            {versions.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No workflow has been saved yet, so requests follow the approval tiers on the Rules page.
              </p>
            ) : (
              <ul className="flex flex-col gap-2">
                {versions.map((version) => (
                  <li key={version.id} className="flex items-center justify-between gap-3 rounded-lg border border-border bg-white px-3 py-2 text-sm">
                    <span>
                      <span className="font-medium text-heading">Version {version.number}</span>
                      <span className="text-muted-foreground"> · saved {formatDate(version.created_at)}</span>
                      {version.drafted_by_ai ? <span className="text-muted-foreground"> · drafted by AI</span> : null}
                    </span>
                    {version.status === "draft" ? (
                      <Button size="sm" onClick={() => publish(version)} disabled={busy}><Send aria-hidden /> Publish</Button>
                    ) : (
                      <span className={version.status === "published" ? "font-medium text-heading" : "text-muted-foreground"}>
                        {version.status === "published" ? "In use" : "Replaced"}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {published ? null : versions.length ? (
              <p className="mt-3 text-sm text-muted-foreground">Nothing is published yet: requests still follow the tiers on the Rules page.</p>
            ) : null}
          </Panel>
        </div>
      </div>
    </>
  );
}
