// A change of an existing namespace's labels and annotations, for the Namespaces tab (#484, design of #481, sections 3 to
// 6). The rows of the table (Git, Live and Your change for each key), the person's draft as a JSON Merge Patch over what
// Git holds (RFC 7396: a value sets a key, null removes it, a key left out is kept), the change box, and the one complex
// step that the design allows: after a 412, the draft is put again on the new Git, and a key that both sides changed is
// the person's choice, never silently overwritten (section 5, the lost update).
//
// Pure functions, no React and no local imports but types, so Node runs this file as it is in the direct tests.
import type { ExtraRow, Kind, KeyEdit, MetaField, MetaForm } from "./metadataForm";

/** A namespace's labels and annotations, by kind: what Git holds or what the cluster has. */
export type Maps = Record<Kind, Record<string, string>>;

/**
 * What the person may do with a row (design section 3): type in a declared key's own input (field), type a value with no
 * declared rule (value: an additional key, or an operator-only key for a caller with namespaces:protect), only remove it
 * (remove: a key that no rule admits, #492 M2), or nothing (locked).
 */
export type Access = "field" | "value" | "remove" | "locked";

/** x-cmapi-edit of each key that Git holds and metadata-keys.yaml does not declare, from the namespace read (#528). */
export type GitEdits = Record<"labels" | "annotations", Record<string, KeyEdit & { removable?: boolean }>>;

/** One key of the namespace, as one row of the table. */
export interface KeyRow {
  /** The key's valueKey ("label:<key>"): its place in the draft. */
  id: string;
  kind: Kind;
  key: string;
  /** The rule's title, else the key. */
  title: string;
  edit: KeyEdit;
  access: Access;
  /** The declared rules of its input (access "field"); null otherwise. */
  field: MetaField | null;
  /** An additional key (allowOther) that Git holds. */
  extra: boolean;
  git: string | null;
  live: string | null;
}

/** The person's change: each key that they set (a value) or remove (null), relative to what Git holds. */
export type Draft = Record<string, string | null>;

/** One line of the change box: a key, its value in Git, and its value after the change (null: removed). */
export interface ChangeLine { kind: Kind; key: string; before: string | null; after: string | null; sensitive: boolean }

const split = (id: string): [Kind, string] => {
  const at = id.indexOf(":");
  return [id.slice(0, at) as Kind, id.slice(at + 1)];
};

/** The mockup's order within a kind: what cmapi fills in, the other locked keys, then the required and the optional ones. */
const rank = (r: KeyRow): number => (r.access === "locked" ? (r.edit.mode === "automatic" ? 0 : 1) : r.edit.mode === "required" ? 2 : 3);

/**
 * The rows of one namespace, each kind in the mockup's order: the locked keys, the required ones, the optional ones, then the
 * keys that Git holds and the file does not declare. A declared field is changeable unless x-cmapi-edit fixes it or cmapi
 * fills it in. An operator-only key is a value to type for a caller who holds namespaces:protect in the namespace's
 * environment (`operator`); for anyone else it shows only where Git holds it, locked with its reason (design section 3,
 * row 4). Of the undeclared keys of Git (`edits`, the read's x-cmapi-edit of each), an additional key (optional) is a value
 * to type, a key that no rule admits (removable) can only be removed, and cmapi's own and the platform's keys are not shown.
 */
export function rowsOf(form: MetaForm, git: Maps, live: Maps, edits: GitEdits, operator: boolean): KeyRow[] {
  const rows: KeyRow[] = [];
  const row = (kind: Kind, key: string, title: string, edit: KeyEdit, access: Access, field: MetaField | null = null, extra = false): KeyRow =>
    ({ id: `${kind}:${key}`, kind, key, title, edit, access, field, extra, git: git[kind][key] ?? null, live: live[kind][key] ?? null });
  for (const kind of ["label", "annotation"] as const) {
    const mine: KeyRow[] = [];
    for (const f of form.fields.filter((x) => x.kind === kind)) {
      const edit = form.edits[`${kind}:${f.key}`];
      if (!edit) continue;
      const locked = f.derivedFrom !== null || edit.mode === "fixed" || edit.mode === "automatic";
      mine.push(row(kind, f.key, f.title ?? f.key, edit, locked ? "locked" : "field", locked ? null : f));
    }
    for (const key of form.operatorOnly[kind]) {
      const edit = form.edits[`${kind}:${key}`];
      if (edit && (operator || key in git[kind])) mine.push(row(kind, key, key, edit, operator ? "value" : "locked"));
    }
    mine.sort((a, b) => rank(a) - rank(b));
    rows.push(...mine);
    for (const [key, edit] of Object.entries(edits[kind === "label" ? "labels" : "annotations"])) {
      if (!(key in git[kind])) continue;
      if (edit.removable) rows.push(row(kind, key, key, edit, "remove"));
      else if (edit.mode === "optional") rows.push(row(kind, key, key, edit, "value", null, true));
    }
  }
  return rows;
}

/** Whether the person may type in the row: a changeable field, or a value with no declared rule. */
export const isEditable = (row: KeyRow): boolean => row.access === "field" || row.access === "value";

/** The row's value now: the draft's, else what Git holds. */
export const valueNow = (row: KeyRow, draft: Draft): string | null => (row.id in draft ? draft[row.id] : row.git);

/**
 * The draft with one row's value: a value equal to Git's is no change, so it leaves the draft (only effective changes stay).
 * An emptied input of a key that Git does not hold adds nothing: it is not a key set to "".
 */
export function withValue(draft: Draft, row: KeyRow, value: string | null): Draft {
  const next = { ...draft };
  if (value === row.git || (value === "" && row.git === null)) delete next[row.id];
  else next[row.id] = value;
  return next;
}

/** The change box before Check: each drafted key, then each new additional key, with its value in Git and after. */
export function changeLines(rows: KeyRow[], draft: Draft, added: Record<Kind, ExtraRow[]>): ChangeLine[] {
  const lines: ChangeLine[] = rows.filter((r) => r.id in draft).map((r) => ({ kind: r.kind, key: r.key, before: r.git, after: draft[r.id], sensitive: r.edit.sensitive }));
  for (const kind of ["label", "annotation"] as const) {
    for (const r of added[kind]) if (r.key !== "") lines.push({ kind, key: r.key, before: null, after: r.value, sensitive: false });
  }
  return lines;
}

/** The PATCH body's two maps, as a merge patch: the drafted keys (null removes one) and the new additional keys. */
export function patchOf(draft: Draft, added: Record<Kind, ExtraRow[]>): { labels: Record<string, string | null>; annotations: Record<string, string | null> } {
  const out = { labels: {} as Record<string, string | null>, annotations: {} as Record<string, string | null> };
  for (const [id, value] of Object.entries(draft)) {
    const [kind, key] = split(id);
    (kind === "label" ? out.labels : out.annotations)[key] = value;
  }
  for (const [kind, map] of [["label", out.labels], ["annotation", out.annotations]] as const) {
    for (const r of added[kind]) if (r.key !== "") map[r.key] = r.value;
  }
  return out;
}

/** The result of putting a draft on the Git that a 412 revealed: the draft that still changes something, and the keys to ask about. */
export interface Rebased { draft: Draft; conflicts: string[] }

/**
 * The draft, made against `before`, put on `after` (design section 5, the 412). A key that Git did not change keeps the
 * person's edit. A key that Git changed to what the person wanted is no change any more. A key that Git changed to anything
 * else is a conflict: both sides changed it, so the person chooses "Use current" or "Keep my edit". Re-applying it blindly
 * would overwrite the other person's change (the lost update of RFC 9110, section 13.1.1).
 */
export function rebase(draft: Draft, before: Maps, after: Maps): Rebased {
  const next: Draft = {};
  const conflicts: string[] = [];
  for (const [id, mine] of Object.entries(draft)) {
    const [kind, key] = split(id);
    const was = before[kind][key] ?? null, now = after[kind][key] ?? null;
    if (mine === now) continue;
    next[id] = mine;
    if (was !== now) conflicts.push(id);
  }
  return { draft: next, conflicts };
}
