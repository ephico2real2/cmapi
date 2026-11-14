// How the Requests tab words one request of the API, in the mockup's forms (mockups/portal/Main.dc.html, REQUESTS).
import type { ChangeRequest } from "../api/hooks";

/** The mockup's REQ_TONE for the states it has, and the same rule for the others: a failure is bad, an end is neutral. */
const TONE: Record<ChangeRequest["status"], string> = {
  pending_approval: "warn", awaiting_prune: "warn",
  approved: "info", pr_open: "info", merged: "info",
  synced: "ok",
  rejected: "bad", failed: "bad", sync_failed: "bad",
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
  const need = a.slots.reduce((n, slot) => n + slot.count, 0);
  const left = a.remaining.reduce((n, slot) => n + slot.needed, 0);
  return `${a.rule} · ${need - left} of ${need}`;
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
