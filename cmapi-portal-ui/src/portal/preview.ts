// The live preview of the New namespace form (#479 P6): the labels and annotations that the request will set, before the
// dry run, each marked with where its value comes from. After a passing dry run the page shows the plan's own
// namespace.yaml instead (P7, A7), so the API's answer is what the person reads last. Pure functions, no React and no
// local imports but types, so Node runs this file as it is in the direct tests.
import type { ExtraRow, Kind, MetaField, MetaForm, Source } from "./metadataForm";

/** The keys that cmapi writes for an expiry date (core/render/manifests.py, the date's label and annotation; design 2.7). */
export const EXPIRES_AT = "cmapi.net/expires-at";
export const EXPIRY_LABEL = "cmapi.net/expiry";
export const EXPIRY_VALUE = "managed";

/** One line of the preview: a key, its value, and where the value comes from (empty for what the person typed). */
export interface PreviewLine { key: string; value: string; note: string }

/** What the preview reads from the form as it is now. */
export interface PreviewInput {
  form: MetaForm;
  /** The values that the person typed; a default field that is not here copies its source. */
  typed: Record<string, string>;
  /** The values shown, with each unedited default copied. */
  shown: Record<string, string>;
  target: Record<Source, string>;
  extras: Record<Kind, ExtraRow[]>;
  /** The expiry date when it is a valid one in an environment that takes it, else null. */
  expiresAt: string | null;
  /** An operator's protection label (#366), or null. */
  protect: { key: string; value: string } | null;
}

/** The fields of one kind in the form's order: the keys that cmapi sets, then the required inputs, then the optional ones. */
const ordered = (form: MetaForm, kind: Kind): MetaField[] => {
  const mine = form.fields.filter((f) => f.kind === kind);
  return [...mine.filter((f) => f.derivedFrom !== null), ...mine.filter((f) => f.derivedFrom === null && f.required),
    ...mine.filter((f) => f.derivedFrom === null && !f.required)];
};

/** One field's line: what cmapi fills in (automatic), a default copied from its source, what was typed, or none. */
function fieldLine(input: PreviewInput, f: MetaField): PreviewLine | null {
  const k = `${f.kind}:${f.key}`;
  if (f.derivedFrom !== null) return { key: f.key, value: input.target[f.derivedFrom], note: "automatic" };
  const value = input.shown[k] ?? "";
  if (f.defaultFrom !== null && !(k in input.typed)) {
    const source = input.form.fields.find((s) => s.kind === f.kind && s.key === f.defaultFrom);
    return value === "" ? null : { key: f.key, value, note: `from ${source?.title ?? f.defaultFrom}` };
  }
  if (value === "" && f.required) return { key: f.key, value: "", note: "required, not set yet" };
  // An emptied default is sent as "" (bodyOf), so it is written; any other empty optional key is not sent.
  if (value === "" && f.defaultFrom === null) return null;
  return { key: f.key, value, note: "" };
}

/** The lines of each map, in the order that the YAML shows them. */
export function previewLines(input: PreviewInput): Record<Kind, PreviewLine[]> {
  const out: Record<Kind, PreviewLine[]> = { label: [], annotation: [] };
  for (const kind of ["label", "annotation"] as const) {
    for (const f of ordered(input.form, kind)) {
      const line = fieldLine(input, f);
      if (line) out[kind].push(line);
    }
    for (const r of input.extras[kind]) if (r.key !== "") out[kind].push({ key: r.key, value: r.value, note: "additional" });
  }
  if (input.protect) out.label.push({ key: input.protect.key, value: input.protect.value, note: "Protect from deletion" });
  if (input.expiresAt) {
    out.label.push({ key: EXPIRY_LABEL, value: EXPIRY_VALUE, note: "from Expires" });
    out.annotation.push({ key: EXPIRES_AT, value: input.expiresAt, note: "from Expires" });
  }
  return out;
}

/**
 * A YAML scalar: a key as it is when YAML reads it as that text, every value double-quoted (JSON's string syntax is YAML's).
 * A key such as "on", "no" or "01" is quoted: YAML 1.1, which Kubernetes reads, takes it for a boolean or a number.
 */
const plainKey = (key: string): boolean => /^[A-Za-z][-A-Za-z0-9_./]*$/.test(key) && !/^(y|yes|n|no|true|false|on|off|null)$/i.test(key);
const yamlKey = (key: string): string => (plainKey(key) ? key : JSON.stringify(key));
const yamlLine = (l: PreviewLine): string => `    ${yamlKey(l.key)}: ${JSON.stringify(l.value)}${l.note ? `   # ${l.note}` : ""}`;

/** The Namespace as the form describes it now. The keys that only cmapi writes are named in one comment. */
export function previewYaml(name: string, lines: Record<Kind, PreviewLine[]>): string {
  return [
    "apiVersion: v1", "kind: Namespace", "metadata:", `  name: ${JSON.stringify(name)}`,
    // An empty map is {}: "labels:" alone is null in YAML.
    lines.label.length ? "  labels:" : "  labels: {}", ...lines.label.map(yamlLine), "    # cmapi.net/managed, cluster-id, request-id, tier … added by cmapi",
    lines.annotation.length ? "  annotations:" : "  annotations: {}", ...lines.annotation.map(yamlLine)
  ].join("\n");
}

/** The plan's namespace.yaml (its path ends with /namespace.yaml), the file that the request writes; null when it has none. */
export function planNamespaceFile(files: Record<string, string>): { path: string; text: string } | null {
  const path = Object.keys(files).find((p) => p.endsWith("/namespace.yaml"));
  return path === undefined ? null : { path, text: files[path] };
}

/** Where the dry run says a value comes from (A7), in words: request, a target of cmapi's, or default:<key>. */
export function sourceWords(source: string): string {
  if (source === "request") return "from the request";
  if (source.startsWith("default:")) return `default from ${source.slice("default:".length)}`;
  return `from the ${source}`;
}
