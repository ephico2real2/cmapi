// The parts of a dry run's plan (PlanView) that the New namespace and Quotas tabs both show, in the mockup's forms.
import type { Plan } from "../api/hooks";
import type { Check } from "../components/ui";

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
