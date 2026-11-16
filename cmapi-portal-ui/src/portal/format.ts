// How the Requests tab words one request of the API, in the mockup's forms (mockups/portal/Main.dc.html, REQUESTS).
import type { ChangeRequest } from "../api/hooks";

/** The mockup's REQ_TONE for the states it has, and the same rule for the others: a failure is bad, an end is neutral. */
const TONE: Record<ChangeRequest["status"], string> = {
  pending_approval: "warn", awaiting_prune: "warn",
  approved: "info", pr_open: "info", applied: "info", merged: "info",
  synced: "ok",
  rejected: "bad", failed: "bad", sync_failed: "bad", merge_failed: "bad",
  superseded: "", cancelled: "", timeout: "", reverted: ""
};
export const toneOf = (status: ChangeRequest["status"]): string => TONE[status] ?? "";

/** "create", or "delete (expired)" when a plugin gave the reason. */
export const actionOf = (r: ChangeRequest): string => (r.reason ? `${r.action} (${r.reason})` : r.action);

/** "dev-change · 0 of 1", or "auto: baseline-rnd-namespace" when a policy approved it. */
export function approvalOf(r: ChangeRequest): string {
  const a = r.approval;
  if (!a) return "—";
  if (a.auto) return a.auto.startsWith("auto:") ? `auto: ${a.auto.slice(5)}` : a.auto;
  const { need, have } = countsOf(r);
  return `${a.rule} · ${have} of ${need}`;
}

export const prOf = (r: ChangeRequest): string => (r.pr ? `#${r.pr.number}` : "—");

/** The last event that the API recorded: where the request is now, and who or what put it there. */
export function whereOf(r: ChangeRequest): { event: string; by: string } {
  const last = r.events.at(-1);
  return last ? { event: last.event, by: `by ${last.by}` } : { event: "—", by: "" };
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** UTC, as the mockup says: "17:35" for today, "Nov 3 17:02" for another day. */
export function whenOf(iso: string, now: Date): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "—";
  const time = at.toISOString().slice(11, 16);
  const sameDay = at.toISOString().slice(0, 10) === now.toISOString().slice(0, 10);
  return sameDay ? time : `${MONTHS[at.getUTCMonth()]} ${at.getUTCDate()} ${time}`;
}

/** "1–25 of 61 · newest first", or "0 requests". */
export const rangeOf = (page: { from: number; to: number; total: number }): string =>
  (page.total ? `${page.from}–${page.to} of ${page.total} · newest first` : "0 requests");

/** "17:05:42": the mockup's clock for an event, in UTC. */
export function clockOf(iso: string): string {
  const at = new Date(iso);
  return Number.isNaN(at.getTime()) ? "—" : at.toISOString().slice(11, 19);
}

/** "3 min 12 s", the mockup's form of a duration (its dur()). */
export function durationOf(ms: number): string {
  const t = Math.max(0, Math.round(ms / 1000)), m = Math.floor(t / 60), s = t % 60;
  return (m ? `${m} min ` : "") + `${s} s`;
}

/** "Nov 4" for "2026-11-04", the mockup's dayName(). */
export const dayName = (iso: string): string => `${MONTHS[Number(iso.slice(5, 7)) - 1]} ${Number(iso.slice(8, 10))}`;

/** Today in UTC as "2026-11-15", and the day `days` after it. The mockup's dates are UTC days. */
export function isoDay(now: Date, days = 0): string {
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()) + days * 864e5).toISOString().slice(0, 10);
}

/** Whole days from today (UTC) to a date, the mockup's dayDiff(). */
export const daysUntil = (iso: string, now: Date): number => Math.round((Date.parse(iso) - Date.parse(isoDay(now))) / 864e5);

/** Approvals needed and recorded: "need" from the slots, "have" as need minus what remains. */
export function countsOf(r: Pick<ChangeRequest, "approval">): { need: number; have: number } {
  const a = r.approval;
  if (!a) return { need: 0, have: 0 };
  const need = a.slots.reduce((n, slot) => n + slot.count, 0);
  return { need, have: need - a.remaining.reduce((n, slot) => n + slot.needed, 0) };
}

/** "approver-platform", or "approver-prod 1, approver-platform 2" when more than one group must approve: the mockup's form. */
export function groupsOf(r: Pick<ChangeRequest, "approval">): string {
  const slots = r.approval?.slots ?? [];
  return slots.length === 1 ? slots[0].group : slots.map((s) => `${s.group} ${s.count}`).join(", ");
}

/** "Auto-approved by baseline-rnd-namespace" from "auto:baseline-rnd-namespace". */
export const policyOf = (auto: string): string => (auto.startsWith("auto:") ? auto.slice(5) : auto);

// Kubernetes quantities (k8s.io/apimachinery resource.Quantity): a decimal number with an SI or binary suffix.
const SUFFIX: Record<string, number> = {
  "": 1, m: 1e-3, k: 1e3, M: 1e6, G: 1e9, T: 1e12, P: 1e15, E: 1e18,
  Ki: 2 ** 10, Mi: 2 ** 20, Gi: 2 ** 30, Ti: 2 ** 40, Pi: 2 ** 50, Ei: 2 ** 60
};

/** "500m" is 0.5 and "16Gi" is 17179869184. Null for no value or for text that is not a quantity. */
export function quantityOf(text: string | null | undefined): number | null {
  const m = /^([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)(m|k|M|G|T|P|E|Ki|Mi|Gi|Ti|Pi|Ei)?$/.exec((text ?? "").trim());
  return m ? Number(m[1]) * SUFFIX[m[2] ?? ""] : null;
}

/** The mockup's fmt(): one decimal, no trailing zero. */
export const fmt = (n: number): string => (Math.round(n * 10) / 10).toString();

/** The mockup's pctBar(): the share of the hard limit, the bar's tone at 80% and 95%, and "used / hard". */
export function barOf(used: number | null, hard: number | null): { pct: number; bar: string; text: string } | null {
  if (used === null || hard === null || hard <= 0) return null;
  const r = used / hard;
  return { pct: Math.round(r * 100), bar: r >= 0.95 ? "crit" : r >= 0.8 ? "warn" : "", text: `${fmt(used)} / ${fmt(hard)}` };
}

export const GIB = 2 ** 30;
