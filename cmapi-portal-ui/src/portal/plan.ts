// The parts of a dry run's plan (PlanView) that the New namespace, Namespaces and Quotas tabs show, in the mockup's forms.
import type { Plan } from "../api/hooks";
import type { Check } from "../components/ui";
import { policyOf } from "./format";

export const MARK = { pass: "✓", warn: "!", fail: "✕" } as const;

/** The API's reasons, as one sentence: "dev create: 1 from approver-platform; threshold beyondTier: +1 approver-platform." */
export const sentence = (reasons: string[]): string => (reasons.length ? `${reasons.join("; ")}.` : "");

export const CAPACITY_TONE = { fits: "ok", warn: "warn", exceeded: "bad", unknown: "" } as const;

export function capacityCheck(plan: Plan): Check {
  const c = plan.capacity;
  if (c.status === "fits") return { s: "pass", mark: MARK.pass, main: "Capacity", note: c.fresh ? "fits on fresh data" : "fits on stale data" };
  if (c.status === "exceeded") return { s: "fail", mark: MARK.fail, main: "Capacity", note: "capacity-exceeded" };
  return { s: "warn", mark: MARK.warn, main: "Capacity", note: c.status };
}

/** "cpu 3% · memory 3% · binds on cpu", from the capacity check's fields when it has them. */
export function capacityLine(plan: Plan): string {
  const c = plan.capacity as Plan["capacity"] & { cpu?: unknown; memory?: unknown };
  const pct = (x: unknown) => (typeof x === "number" ? `${Math.round(x * 100)}%` : "—");
  return `cpu ${pct(c.cpu)} · memory ${pct(c.memory)}${c.bindingResource ? ` · binds on ${c.bindingResource}` : ""}`;
}

/** The approval of a create or a change: who must approve, and why. The API decides it (docs/02); the page only says it. */
export function approvalCard(plan: Plan, env: string): { title: string; detail: string; rule: string } {
  const a = plan.approval;
  const need = a.slots.reduce((n, s) => n + s.count, 0);
  if (a.auto || need === 0) {
    const title = a.auto && a.auto !== "none-required" ? `Auto-approved by ${policyOf(a.auto)}` : "No approval needed";
    return { title, detail: sentence(a.reasons), rule: `${a.rule} · 0 of 0 (auto)` };
  }
  const groups = a.slots.map((s) => s.group).join(" + ");
  const self = a.selfApproval ? `Self-approval is allowed in ${env}.` : "The requester cannot approve their own request.";
  return {
    title: `${need} approval${need > 1 ? "s" : ""} in cmapi from ${groups}`,
    detail: `${sentence(a.reasons)} ${self}`.trim(),
    rule: `${a.rule} · ${a.slots.map((s) => `${s.count} of ${s.group}`).join(" + ")}`
  };
}
