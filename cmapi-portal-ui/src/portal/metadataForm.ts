// The labels and annotations of the New namespace form, read from GET /api/v1/metadata-keys (#336): the instance's
// metadata-keys.yaml as the JSON Schema of NamespaceCreate's two maps, the same objects as in the API document.
//
// cmapi decides. The form only helps: it evaluates the keywords that the API publishes for each field, in the
// validator's order and with its words (x-cmapi-rule), and it never refuses a value that cmapi accepts. A differential
// test holds that on every case of tests/api/metadata-corpus.json (tests/api/direct.test.mjs), and a contract test fails
// when the API publishes a keyword that this module neither evaluates nor lists as ignored (KEYWORDS).
//
// Pure functions, no React and no local imports, so Node runs this file as it is (type stripping) in the direct tests.
// The decisions and their sources: docs/reviews/2026-11-17-issue-336/.

export type Kind = "label" | "annotation";
export type Source = "namespace" | "environment" | "cluster" | "instance";

/** One field of the form: a declared key that the requester sets, or one that cmapi sets (read-only, never sent). */
export interface MetaField {
  /** `ns-label-0`: by kind and position, so no text of the config reaches an id, a selector or aria-describedby. */
  id: string;
  kind: Kind;
  key: string;
  /** The rule's `title` (Validation 2020-12, 9.1), or null: the form then labels the field with the key. */
  title: string | null;
  required: boolean;
  /** The target that cmapi fills the value from (x-cmapi-derived-from), or null for a field the requester fills. */
  derivedFrom: Source | null;
  /** The namespace name starts with this value and a "-" (x-cmapi-namespace-prefix). */
  namespacePrefix: boolean;
  enum: string[] | null;
  format: "email-in-domains" | "url" | null;
  /** The config's words and the rule in words, as the API document says them. */
  description: string;
  /** The rule in the validator's words (x-cmapi-rule): what a refusal's detail says. */
  rule: string;
  /** The first example: the input's placeholder, never its value (Validation 9.5: a sample, not a default). */
  example: string | null;
  /** The value's patterns, except the label-value one that every label is checked against first. */
  patterns: string[];
  maxLength: number | null;
  minLength: number | null;
}

/** What the form reads from one answer of GET /api/v1/metadata-keys. */
export interface MetaForm {
  /** Inputs, then read-only fields, then optional inputs, for each kind; operator-only keys are not offered. */
  fields: MetaField[];
  /** A label value's syntax (labels.additionalProperties): Kubernetes' IsValidLabelValue, which cmapi checks first. */
  labelValue: { pattern: string; maxLength: number } | null;
  /** The labels that only an operator may set (x-cmapi-operator-only), such as cmapi.net/protected (#366). */
  operatorOnlyLabels: string[];
}

/** The answer is not the shape that this portal reads: the form shows an error, never a form with fields missing. */
export class RulesUnreadable extends Error {
  constructor(why: string) {
    super(`The metadata rules of this instance are not in the form this portal reads: ${why}.`);
    this.name = "RulesUnreadable";
  }
}

const SOURCES: readonly Source[] = ["namespace", "environment", "cluster", "instance"];
const FORMATS = ["email-in-domains", "url"] as const;
type Json = Record<string, unknown>;

/**
 * Each keyword of the answer: the ones this module evaluates or shows, and the ones it does not, each with why. The
 * contract test (tests/contract.test.mjs) fails on a keyword in neither list: a new keyword is a decision, not a field
 * that the form silently checks less than cmapi does.
 */
export const KEYWORDS = {
  map: {
    read: ["type", "properties", "required", "additionalProperties"],
    ignored: {
      propertyNames: "the names of other keys: the form offers declared keys only (#365)",
      "x-cmapi-other-keys": "the prefixes and limits of other keys: the form offers declared keys only (#365)"
    }
  },
  property: {
    read: ["type", "pattern", "allOf", "maxLength", "minLength", "enum", "title", "description", "examples", "readOnly", "x-cmapi-rule",
      "x-cmapi-derived-from", "x-cmapi-format", "x-cmapi-namespace-prefix", "x-cmapi-operator-only"],
    ignored: {}
  },
  /** An entry of a property's allOf: the label-value syntax beside a key's own pattern. */
  allOf: { read: ["type", "pattern"], ignored: {} },
  /** labels.additionalProperties: a label value's syntax. annotations.additionalProperties bounds other keys only. */
  additionalProperties: { read: ["type", "pattern", "maxLength"], ignored: {} }
} as const;

const isObject = (value: unknown): value is Json => typeof value === "object" && value !== null && !Array.isArray(value);
const textOf = (value: unknown): string | null => (typeof value === "string" ? value : null);
const countOf = (value: unknown): number | null => (typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null);

function fieldOf(kind: Kind, key: string, prop: unknown, required: boolean, labelPattern: string | null): MetaField | "operator-only" {
  if (!isObject(prop)) throw new RulesUnreadable(`the ${kind} ${key} is not an object`);
  if (prop["x-cmapi-operator-only"] === true) return "operator-only";
  const derived = textOf(prop["x-cmapi-derived-from"]);
  if (derived !== null && !SOURCES.includes(derived as Source)) throw new RulesUnreadable(`the ${kind} ${key} is set from ${derived}`);
  if (prop.enum !== undefined && !(Array.isArray(prop.enum) && prop.enum.every((v) => typeof v === "string"))) {
    throw new RulesUnreadable(`the enum of the ${kind} ${key} is not a list of text`);
  }
  const all = Array.isArray(prop.allOf) ? prop.allOf : [];
  const patterns = [prop.pattern, ...all.map((s) => (isObject(s) ? s.pattern : undefined))]
    .filter((p): p is string => typeof p === "string" && p !== labelPattern);
  const format = textOf(prop["x-cmapi-format"]);
  const examples = Array.isArray(prop.examples) ? prop.examples : [];
  return {
    id: "", kind, key, required, title: textOf(prop.title), derivedFrom: derived as Source | null,
    namespacePrefix: prop["x-cmapi-namespace-prefix"] === true,
    enum: prop.enum === undefined ? null : [...(prop.enum as string[])],
    format: FORMATS.includes(format as (typeof FORMATS)[number]) ? (format as MetaField["format"]) : null,
    description: textOf(prop.description) ?? "",
    rule: textOf(prop["x-cmapi-rule"]) ?? "",
    example: typeof examples[0] === "string" ? examples[0] : null,
    patterns, maxLength: countOf(prop.maxLength), minLength: countOf(prop.minLength)
  };
}

/** The fields of one answer. Throws RulesUnreadable when the answer is not the shape of MetadataKeys.json_schema. */
export function fieldsOf(view: unknown): MetaForm {
  if (!isObject(view)) throw new RulesUnreadable("the answer is not an object");
  const extra = isObject(view.labels) ? view.labels.additionalProperties : undefined;
  const labelValue = isObject(extra) && typeof extra.pattern === "string" && countOf(extra.maxLength) !== null
    ? { pattern: extra.pattern, maxLength: countOf(extra.maxLength)! } : null;
  const fields: MetaField[] = [];
  const operatorOnlyLabels: string[] = [];
  for (const [kind, name] of [["label", "labels"], ["annotation", "annotations"]] as const) {
    const map = view[name];
    if (!isObject(map) || map.type !== "object" || !isObject(map.properties)) throw new RulesUnreadable(`${name} has no properties`);
    if (map.required !== undefined && !(Array.isArray(map.required) && map.required.every((k) => typeof k === "string"))) {
      throw new RulesUnreadable(`${name}.required is not a list of keys`);
    }
    const required = (map.required as string[] | undefined) ?? [];
    const props = map.properties;
    const missing = required.filter((k) => !(k in props));
    if (missing.length) throw new RulesUnreadable(`${name} requires ${missing.join(", ")} and does not describe it`);
    const read = Object.entries(props).map(([key, prop]) =>
      fieldOf(kind, key, prop, required.includes(key), kind === "label" ? labelValue?.pattern ?? null : null));
    const offered = read.filter((f): f is MetaField => f !== "operator-only");
    if (kind === "label") operatorOnlyLabels.push(...Object.keys(props).filter((_, i) => read[i] === "operator-only"));
    // Required in the order of `required` (an array keeps its order through JSON; an object's integer-like keys do not),
    // then what cmapi sets, then the optional keys.
    const ordered = [
      ...required.flatMap((k) => offered.filter((f) => f.key === k && f.derivedFrom === null)),
      ...offered.filter((f) => f.derivedFrom !== null),
      ...offered.filter((f) => f.derivedFrom === null && !f.required)
    ];
    ordered.forEach((f, i) => fields.push({ ...f, id: `ns-${kind}-${i}` }));
  }
  return { fields, labelValue, operatorOnlyLabels };
}

/** The key of a field's value in the form's state: a key can be a label and an annotation, each with its own value. */
export const valueKey = (f: Pick<MetaField, "kind" | "key">): string => `${f.kind}:${f.key}`;

/** The value that cmapi will write for a read-only field, from the request's target. */
export function derivedValue(f: MetaField, target: Record<Source, string>): string {
  return f.derivedFrom ? target[f.derivedFrom] : "";
}

/**
 * What the form sends: each field that the requester fills, with a value. Never an empty optional key (cmapi refuses
 * "" for a declared pattern), never a key that cmapi sets (it fills the value itself, and refuses another one), never an
 * operator-only key (not offered).
 */
export function bodyOf(form: MetaForm, values: Record<string, string>): { labels: Record<string, string>; annotations: Record<string, string> } {
  const out = { labels: {} as Record<string, string>, annotations: {} as Record<string, string> };
  for (const f of form.fields) {
    const value = values[valueKey(f)] ?? "";
    if (f.derivedFrom === null && value !== "") (f.kind === "label" ? out.labels : out.annotations)[f.key] = value;
  }
  return out;
}

/**
 * The suggested namespace name, `<value>-<environment>`: from the required key that starts the name (namespacePrefix),
 * or, on an instance with none, from the first required label (the mockup's team: `payments-dev`). A recorded default
 * of #336 that the owner may change. A name that the person types always wins.
 */
export function nameSuggestion(form: MetaForm, values: Record<string, string>, environment: string): string {
  const inputs = form.fields.filter((f) => f.derivedFrom === null && f.required);
  const from = inputs.find((f) => f.namespacePrefix) ?? inputs.find((f) => f.kind === "label");
  const value = from ? values[valueKey(from)] ?? "" : "";
  return value ? `${value}-${environment}` : "";
}

/** A pattern's verdict on a value: true, false, or null when it was not checked here (too slow, or no engine). */
export type PatternTest = (pattern: string, value: string) => boolean | null | Promise<boolean | null>;

/** Characters as JSON Schema counts them (RFC 8259 characters: code points) and as Python and cmapi count them. */
const length = (value: string): number => [...value].length;

/**
 * The first problem of one field's value, in the validator's order (core/metadata.py: _syntax, then _governed) and in
 * its words; null when the form sees none. A pattern that was not checked here counts as passed: cmapi's dry run decides.
 */
export async function checkField(f: MetaField, value: string, ctx: { namespace: string; labelValue: MetaForm["labelValue"] },
  test: PatternTest): Promise<string | null> {
  if (f.derivedFrom !== null) return null;
  if (value === "") return f.required ? `Required: ${f.rule}` : null;
  if (f.kind === "label" && ctx.labelValue) {
    const { pattern, maxLength } = ctx.labelValue;
    if (length(value) > maxLength || (await test(pattern, value)) === false) return "Not a valid label value";
  }
  for (const pattern of f.patterns) {
    if ((await test(pattern, value)) === false) return `Not valid: ${f.rule}`;
  }
  if (f.enum && !f.enum.includes(value)) return `Not valid: ${f.rule}`;
  if (f.namespacePrefix && ctx.namespace && !ctx.namespace.startsWith(`${value}-`)) return `${ctx.namespace} does not start with ${value}-`;
  if (f.maxLength !== null && length(value) > f.maxLength) return `At most ${f.maxLength} characters`;
  if (f.minLength !== null && length(value) < f.minLength) return `At least ${f.minLength} characters`;
  return null;
}

/** The problem of each field, by its id (null for none), for one state of the form. */
export async function checkAll(form: MetaForm, values: Record<string, string>, namespace: string, test: PatternTest): Promise<Record<string, string | null>> {
  const out: Record<string, string | null> = {};
  for (const f of form.fields) out[f.id] = await checkField(f, values[valueKey(f)] ?? "", { namespace, labelValue: form.labelValue }, test);
  return out;
}

/** One item of a refusal's `errors`, as the API sends it (RFC 9457 extension, core/errors.py). */
export interface RefusalItem {
  code: string;
  key?: string;
  kind?: string;
  detail?: string;
}

/** A refusal's items, mapped to the form: each one on a field that it names, and the others for the error summary. */
export interface MappedRefusal {
  byField: Record<string, string>;
  items: { item: RefusalItem; field: MetaField | null; text: string }[];
  /** The refusal names a key that the form does not show: the instance's rules changed, so the form reads them again. */
  unknownKey: boolean;
}

const RULE_CODES = new Set(["missing_required_key", "invalid_key", "derived_key"]);

export function errorsByField(items: RefusalItem[], form: MetaForm): MappedRefusal {
  const byField: Record<string, string> = {};
  let unknownKey = false;
  const mapped = items.map((item) => {
    const named = item.key === undefined ? [] : form.fields.filter((f) => f.key === item.key && (item.kind === undefined || f.kind === item.kind));
    // A key that is a label and an annotation, named with no kind: the label first, as validate() checks labels first.
    const field = named.find((f) => f.kind === "label") ?? named[0] ?? null;
    const message = item.detail ?? item.code;
    if (field) byField[field.id] = byField[field.id] ? `${byField[field.id]}; ${message}` : message;
    else if (item.key !== undefined && RULE_CODES.has(item.code)) unknownKey = true;
    return { item, field, text: `${item.key ?? item.kind ?? item.code}: ${message}` };
  });
  return { byField, items: mapped, unknownKey };
}
