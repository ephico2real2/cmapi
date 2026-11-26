// The metadata that a namespace lacks, asked for in one place (#739): the Adopt form asks for it with the adoption, and the
// Namespaces tab's "Add missing metadata" asks for it later with a change. The API names the keys (missingKeys of the
// candidates list and of the namespace read) and the one value of each key that cmapi fills in or that starts the name; the
// form's rules (GET /api/v1/metadata-keys) give each other key its input. cmapi decides: the dry run checks what is sent.
//
// Pure functions, no React and no local imports but types, so Node runs this file as it is in the direct tests.
import type { Kind, MetaField, MetaForm } from "./metadataForm";

/** One key that the namespace lacks, as the API lists it (MissingKey). */
export interface Missing { kind: Kind; key: string; required: boolean; value: string | null }

/** One field of the section: a declared key that the namespace lacks, with its fixed value, or null for one the person types. */
export interface MissingField {
  /** The key's valueKey ("label:<key>"): its place in the typed values and in the Namespaces tab's draft. */
  id: string;
  field: MetaField;
  required: boolean;
  /** The one value cmapi accepts (a key it fills in, or the start of the name): shown read-only and always sent. */
  fixed: string | null;
}

/**
 * The fields of the missing keys, required ones first, in the API's order. A key whose rule the form does not have (the
 * rules changed since they were read) is left out: the dry run still lists it as a finding. A key that cmapi fills in or that
 * starts the name is offered only with the value the API gives: with none, no request can add it.
 */
export function missingFields(form: MetaForm, missing: readonly Missing[]): MissingField[] {
  const out: MissingField[] = [];
  for (const m of missing) {
    const field = form.fields.find((f) => f.kind === m.kind && f.key === m.key);
    if (!field) continue;
    const fixedKey = field.derivedFrom !== null || field.namespacePrefix || field.namespaceSuffix;
    if (fixedKey && m.value === null) continue;
    out.push({ id: `${m.kind}:${m.key}`, field, required: m.required, fixed: fixedKey ? m.value : null });
  }
  return [...out.filter((f) => f.required), ...out.filter((f) => !f.required)];
}

/** The labels and annotations that the section adds: each fixed value, and each value typed that is not empty. */
export function addedOf(fields: readonly MissingField[], typed: Record<string, string>): { labels: Record<string, string>; annotations: Record<string, string> } {
  const out = { labels: {} as Record<string, string>, annotations: {} as Record<string, string> };
  for (const f of fields) {
    const value = f.fixed ?? typed[f.id] ?? "";
    if (value !== "") (f.field.kind === "label" ? out.labels : out.annotations)[f.field.key] = value;
  }
  return out;
}

/** The required keys that the section leaves missing: those a later request still has to add. */
export const stillMissing = (fields: readonly MissingField[], typed: Record<string, string>): MissingField[] =>
  fields.filter((f) => f.required && f.fixed === null && (typed[f.id] ?? "") === "");
