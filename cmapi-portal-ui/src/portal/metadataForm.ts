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
  /** The namespace name ends with a "-" and this value (x-cmapi-namespace-suffix, #479). */
  namespaceSuffix: boolean;
  /** The key whose value cmapi copies here when the request leaves this key out (x-cmapi-default-from, #479), or null. */
  defaultFrom: string | null;
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

/**
 * The keys that a request may add beyond the declared ones (#365, #479 P10): propertyNames, additionalProperties and
 * x-cmapi-other-keys of one map. JSON Schema cannot count only the undeclared keys, so the counts come from
 * x-cmapi-other-keys.
 */
export interface OtherKeys {
  /** The key syntax that every key has (propertyNames: pattern, maxLength, and the long prefix it refuses). */
  syntax: { pattern: string; maxLength: number; notPattern: string | null };
  /** The declared keys of this map (the enum branch of propertyNames): each has its own field, or is an operator's. */
  declared: string[];
  /** The branch of undeclared keys: their prefixes as a pattern, the keys cmapi refuses there, and the reserved prefixes. */
  other: { pattern: string; refused: string[]; reservedPattern: string | null } | null;
  /** A value's syntax (additionalProperties): a label value's pattern and length; for an annotation, its length only. */
  value: { pattern: string | null; maxLength: number | null };
  /** x-cmapi-other-keys: the prefixes in words ("" is none), at most `max` keys, and an annotation's byte limits. */
  prefixes: string[];
  max: number;
  maxValueBytes: number | null;
  maxBytesTotal: number | null;
}

/** One environment's expiry rules (x-cmapi-expiration, #479 A11). `enabled: false`, or no entry: no date in it. */
export interface ExpiryRules {
  enabled: boolean;
  allowedAtCreate: boolean;
  maxLifetimeDays: number;
  notifyDaysBefore: number[];
  graceDays: number;
}

/** What the form reads from one answer of GET /api/v1/metadata-keys. */
export interface MetaForm {
  /** Inputs, then read-only fields, then optional inputs, for each kind; operator-only keys are not offered. */
  fields: MetaField[];
  /** A label value's syntax (labels.additionalProperties): Kubernetes' IsValidLabelValue, which cmapi checks first. */
  labelValue: { pattern: string; maxLength: number } | null;
  /** The labels that only an operator may set (x-cmapi-operator-only), such as cmapi.net/protected (#366). */
  operatorOnlyLabels: string[];
  /** The keys of each kind that are declared and only an operator sets (refused in the extra-key tables). */
  operatorOnly: Record<Kind, string[]>;
  /** The extra keys of each map, or null where the answer offers none. */
  otherKeys: Record<Kind, OtherKeys | null>;
  /** The expiry rules of each environment that the instance serves. */
  expiration: Record<string, ExpiryRules>;
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
  /** The members of the answer itself. */
  answer: { read: ["labels", "annotations", "x-cmapi-expiration"], ignored: {} },
  map: { read: ["type", "properties", "required", "additionalProperties", "propertyNames", "x-cmapi-other-keys"], ignored: {} },
  property: {
    read: ["type", "pattern", "allOf", "maxLength", "minLength", "enum", "title", "description", "examples", "readOnly", "x-cmapi-rule",
      "x-cmapi-derived-from", "x-cmapi-format", "x-cmapi-namespace-prefix", "x-cmapi-namespace-suffix", "x-cmapi-default-from",
      "x-cmapi-operator-only"],
    ignored: {
      "x-cmapi-edit": "how the key may change on an existing namespace (#481): a create sets every key; the Namespaces tab reads it (#484)"
    }
  },
  /** An entry of a property's allOf: the label-value syntax beside a key's own pattern. */
  allOf: { read: ["type", "pattern"], ignored: {} },
  /** labels.additionalProperties: a label value's syntax. annotations.additionalProperties bounds other keys only. */
  additionalProperties: { read: ["type", "pattern", "maxLength"], ignored: {} },
  /** propertyNames of a map, its anyOf branches, and the `not` of the branch of undeclared keys (OtherKeys). */
  propertyNames: { read: ["maxLength", "pattern", "not", "anyOf"], ignored: {} },
  keyBranch: { read: ["enum", "pattern", "not", "anyOf"], ignored: {} },
  /** x-cmapi-other-keys of a map. */
  otherKeys: { read: ["prefixes", "max", "maxValueBytes", "maxBytesTotal"], ignored: {} },
  /** One environment of x-cmapi-expiration.environments. */
  expiration: { read: ["enabled", "allowedAtCreate", "maxLifetimeDays", "notifyDaysBefore", "graceDays"], ignored: {} }
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
    namespaceSuffix: prop["x-cmapi-namespace-suffix"] === true,
    defaultFrom: textOf(prop["x-cmapi-default-from"]),
    enum: prop.enum === undefined ? null : [...(prop.enum as string[])],
    format: FORMATS.includes(format as (typeof FORMATS)[number]) ? (format as MetaField["format"]) : null,
    description: textOf(prop.description) ?? "",
    rule: textOf(prop["x-cmapi-rule"]) ?? "",
    example: typeof examples[0] === "string" ? examples[0] : null,
    patterns, maxLength: countOf(prop.maxLength), minLength: countOf(prop.minLength)
  };
}

const textList = (value: unknown): string[] | null =>
  Array.isArray(value) && value.every((v) => typeof v === "string") ? [...value] : null;

/**
 * One map's extra keys, from the shape that MetadataKeys._key_names builds on a create: the key syntax beside an anyOf of
 * the declared keys (enum) and the branch of undeclared keys (pattern, with a `not` of the keys and prefixes it refuses).
 * A map with no propertyNames offers no extra key. Any other shape is refused: the form never checks less than cmapi.
 */
function otherKeysOf(name: string, map: Json): OtherKeys | null {
  const names = map.propertyNames, limits = map["x-cmapi-other-keys"], values = map.additionalProperties;
  if (names === undefined && limits === undefined) return null;
  const bad = (why: string) => new RulesUnreadable(`${name}.propertyNames ${why}`);
  if (!isObject(names) || !isObject(limits) || !Array.isArray(names.anyOf)) throw bad("is not a syntax and an anyOf of key branches");
  const pattern = textOf(names.pattern), maxLength = countOf(names.maxLength);
  if (pattern === null || maxLength === null) throw bad("has no key syntax");
  const notPattern = names.not === undefined ? null : isObject(names.not) ? textOf(names.not.pattern) : null;
  if (names.not !== undefined && notPattern === null) throw bad("has a `not` that is not a pattern");
  let declared: string[] = [];
  let other: OtherKeys["other"] = null;
  for (const branch of names.anyOf) {
    if (!isObject(branch)) throw bad("has a branch that is not an object");
    if (branch.enum !== undefined) {
      declared = textList(branch.enum) ?? (() => { throw bad("lists a key that is not text"); })();
      continue;
    }
    const allowed = textOf(branch.pattern);
    if (allowed === null) throw bad("has a branch with neither enum nor pattern");
    const refused: string[] = [];
    let reservedPattern: string | null = null;
    const nots = branch.not === undefined ? [] : isObject(branch.not) && Array.isArray(branch.not.anyOf) ? branch.not.anyOf : null;
    if (nots === null) throw bad("has a `not` that is not an anyOf");
    for (const n of nots) {
      if (isObject(n) && textList(n.enum)) refused.push(...textList(n.enum)!);
      else if (isObject(n) && typeof n.pattern === "string") reservedPattern = n.pattern;
      else throw bad("refuses keys in a form this portal does not read");
    }
    other = { pattern: allowed, refused, reservedPattern };
  }
  const prefixes = textList(limits.prefixes), max = countOf(limits.max);
  if (prefixes === null || max === null) throw new RulesUnreadable(`${name}.x-cmapi-other-keys has no prefixes or max`);
  const value = isObject(values) ? { pattern: textOf(values.pattern), maxLength: countOf(values.maxLength) } : { pattern: null, maxLength: null };
  return { syntax: { pattern, maxLength, notPattern }, declared, other, value, prefixes, max,
    maxValueBytes: countOf(limits.maxValueBytes), maxBytesTotal: countOf(limits.maxBytesTotal) };
}

/** x-cmapi-expiration.environments: an environment that is off is {enabled: false} alone (ExpirationRules.contract_view). */
function expirationOf(view: Json): Record<string, ExpiryRules> {
  const block = view["x-cmapi-expiration"];
  if (block === undefined) return {};
  if (!isObject(block) || !isObject(block.environments)) throw new RulesUnreadable("x-cmapi-expiration has no environments");
  const out: Record<string, ExpiryRules> = {};
  for (const [env, raw] of Object.entries(block.environments)) {
    if (!isObject(raw) || typeof raw.enabled !== "boolean") throw new RulesUnreadable(`x-cmapi-expiration of ${env} has no enabled flag`);
    if (!raw.enabled) {
      out[env] = { enabled: false, allowedAtCreate: false, maxLifetimeDays: 0, notifyDaysBefore: [], graceDays: 0 };
      continue;
    }
    const days = countOf(raw.maxLifetimeDays), grace = countOf(raw.graceDays);
    const notify = Array.isArray(raw.notifyDaysBefore) && raw.notifyDaysBefore.every((d) => countOf(d) !== null) ? raw.notifyDaysBefore as number[] : null;
    if (typeof raw.allowedAtCreate !== "boolean" || days === null || grace === null || notify === null) {
      throw new RulesUnreadable(`x-cmapi-expiration of ${env} is not its limits`);
    }
    out[env] = { enabled: true, allowedAtCreate: raw.allowedAtCreate, maxLifetimeDays: days, notifyDaysBefore: [...notify], graceDays: grace };
  }
  return out;
}

/** The fields of one answer. Throws RulesUnreadable when the answer is not the shape of MetadataKeys.json_schema. */
export function fieldsOf(view: unknown): MetaForm {
  if (!isObject(view)) throw new RulesUnreadable("the answer is not an object");
  const extra = isObject(view.labels) ? view.labels.additionalProperties : undefined;
  const labelValue = isObject(extra) && typeof extra.pattern === "string" && countOf(extra.maxLength) !== null
    ? { pattern: extra.pattern, maxLength: countOf(extra.maxLength)! } : null;
  const fields: MetaField[] = [];
  const operatorOnlyLabels: string[] = [];
  const operatorOnly: Record<Kind, string[]> = { label: [], annotation: [] };
  const otherKeys: Record<Kind, OtherKeys | null> = { label: null, annotation: null };
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
    operatorOnly[kind] = Object.keys(props).filter((_, i) => read[i] === "operator-only");
    if (kind === "label") operatorOnlyLabels.push(...operatorOnly[kind]);
    otherKeys[kind] = otherKeysOf(name, map);
    // Required in the order of `required` (an array keeps its order through JSON; an object's integer-like keys do not),
    // then what cmapi sets, then the optional keys.
    const ordered = [
      ...required.flatMap((k) => offered.filter((f) => f.key === k && f.derivedFrom === null)),
      ...offered.filter((f) => f.derivedFrom !== null),
      ...offered.filter((f) => f.derivedFrom === null && !f.required)
    ];
    ordered.forEach((f, i) => fields.push({ ...f, id: `ns-${kind}-${i}` }));
  }
  return { fields, labelValue, operatorOnlyLabels, operatorOnly, otherKeys, expiration: expirationOf(view) };
}

/** The key of a field's value in the form's state: a key can be a label and an annotation, each with its own value. */
export const valueKey = (f: Pick<MetaField, "kind" | "key">): string => `${f.kind}:${f.key}`;

/** The value that cmapi will write for a read-only field, from the request's target. */
export function derivedValue(f: MetaField, target: Record<Source, string>): string {
  return f.derivedFrom ? target[f.derivedFrom] : "";
}

/**
 * What the form sends: each field that the requester fills, with a value, and the extra keys. Never an empty optional key
 * (cmapi refuses "" for a declared pattern), never a key that cmapi sets (it fills the value itself, and refuses another
 * one), never an unedited default (`values` holds what was typed, so cmapi fills it), never an operator-only key.
 */
export function bodyOf(form: MetaForm, values: Record<string, string>,
  extras: Record<Kind, ExtraRow[]> = { label: [], annotation: [] }): { labels: Record<string, string>; annotations: Record<string, string> } {
  const out = { labels: {} as Record<string, string>, annotations: {} as Record<string, string> };
  for (const f of form.fields) {
    const value = values[valueKey(f)] ?? "";
    if (f.derivedFrom === null && value !== "") (f.kind === "label" ? out.labels : out.annotations)[f.key] = value;
  }
  // Extra keys go in the same maps (#479 P11). A row with no key is a row not filled in yet; checkExtras holds it back.
  for (const [kind, map] of [["label", out.labels], ["annotation", out.annotations]] as const) {
    for (const r of extras[kind]) if (r.key !== "") map[r.key] = r.value;
  }
  return out;
}

/**
 * The values that the form shows and checks: what the person typed, and for each key with a default (default.from, #479
 * P4) that they never edited, a copy of its source key's value. A key is edited once the person changes it: its value is
 * then in `typed`, even when they empty it, so a later change of the source leaves it alone (plan R5). An unedited
 * default is never sent (bodyOf reads `typed`): cmapi fills it in, and its dry run says so (source default:<key>).
 */
export function shownValues(form: MetaForm, typed: Record<string, string>): Record<string, string> {
  const out = { ...typed };
  for (const f of form.fields) {
    if (f.defaultFrom === null || valueKey(f) in typed) continue;
    out[valueKey(f)] = typed[`${f.kind}:${f.defaultFrom}`] ?? "";
  }
  return out;
}

/** The field whose value is copied into a default field, for its "from <title>" mark; null when it has none. */
export function defaultSource(form: MetaForm, f: MetaField): MetaField | null {
  return f.defaultFrom === null ? null : form.fields.find((s) => s.kind === f.kind && s.key === f.defaultFrom) ?? null;
}

/** The keys that start and end the namespace name (namespacePrefix, namespaceSuffix, #479 P2); null where none does. */
export function nameEnds(form: MetaForm): { start: MetaField | null; end: MetaField | null } {
  return { start: form.fields.find((f) => f.namespacePrefix) ?? null, end: form.fields.find((f) => f.namespaceSuffix) ?? null };
}

/** The value of one end of the name: what cmapi fills in for a key that it sets, else what the form shows. */
export function endValue(f: MetaField | null, shown: Record<string, string>, target: Record<Source, string>): string | null {
  if (f === null) return null;
  return f.derivedFrom !== null ? target[f.derivedFrom] : shown[valueKey(f)] ?? "";
}

/** `<start>-<desired>-<end>`: the ends that the instance has, around the part that the person types. */
export const joinName = (start: string | null, desired: string, end: string | null): string =>
  [start, desired, end].filter((part): part is string => part !== null).join("-");

/** The longest namespace name: a DNS-1123 label (core/naming.py). */
export const NAME_MAX = 63;
const DNS_LABEL = /^[a-z0-9]([-a-z0-9]*[a-z0-9])?$/;

/**
 * The name's problem, or null: what cmapi refuses too (core/naming.py and _check_desired_name), and nothing more. With an
 * end whose value is missing, only the desired part is checked: that end's own field says what is missing.
 */
export function checkName(start: string | null, desired: string, end: string | null): string | null {
  const ends = start !== null || end !== null;
  if (desired === "") return ends ? "Type the middle of the name." : "Required: a namespace name";
  if (start === "" || end === "") return null;
  const name = joinName(start, desired, end);
  if (length(name) > NAME_MAX) return `The full name is longer than ${NAME_MAX} characters.`;
  if (!DNS_LABEL.test(name)) return ends ? "The middle of the name: lowercase letters, digits and '-'. The name starts and ends with a letter or digit."
    : "A DNS-1123 name: lowercase letters, digits and '-', starting and ending with a letter or digit.";
  return null;
}

/** One row of an extra-key table: its id stays with the row when another row is removed. */
export interface ExtraRow { id: number; key: string; value: string }

/** UTF-8 bytes, as cmapi counts an annotation's size (len(value.encode())). */
export const bytesOf = (text: string): number => new TextEncoder().encode(text).length;

/** "*.company.net/ (or none)": the prefixes of x-cmapi-other-keys in words. */
export function prefixWords(prefixes: string[]): string {
  const named = prefixes.filter((p) => p !== "");
  if (!named.length) return "none";
  return `${named.join(" or ")}${prefixes.includes("") ? " (or none)" : ""}`;
}

/**
 * The first problem of one extra key, in the order of the schema that cmapi publishes for it (propertyNames, which is sound:
 * each key that validate() accepts passes it), then a duplicate in the same table. null when the form sees none.
 */
export async function checkExtraKey(form: MetaForm, kind: Kind, key: string, rows: ExtraRow[], test: PatternTest): Promise<string | null> {
  const rules = form.otherKeys[kind];
  if (!rules) return "This instance takes no additional keys here.";
  if (key === "") return "Enter a key.";
  const { syntax } = rules;
  if (length(key) > syntax.maxLength || (await test(syntax.pattern, key)) === false || (syntax.notPattern !== null && (await test(syntax.notPattern, key)) === true)) {
    return "Not a valid key: an optional DNS prefix and '/', then up to 63 letters, digits, '-', '_' or '.'.";
  }
  if (form.operatorOnly[kind].includes(key)) return "Only an operator sets this key.";
  if (rules.declared.includes(key)) return "This key has its own field above.";
  const other = rules.other;
  if (other === null || (await test(other.pattern, key)) === false) return `The prefix must be ${prefixWords(rules.prefixes)}.`;
  if (other.refused.includes(key)) return "cmapi sets this key, or it has its own field in the other table.";
  if (other.reservedPattern !== null && (await test(other.reservedPattern, key)) === true) return "This prefix is reserved.";
  if (rows.filter((r) => r.key === key).length > 1) return "This key is already in the table.";
  return null;
}

/** The problem of one extra value: a label value's syntax (additionalProperties), an annotation's bytes (x-cmapi-other-keys). */
export async function checkExtraValue(form: MetaForm, kind: Kind, value: string, test: PatternTest): Promise<string | null> {
  const rules = form.otherKeys[kind];
  if (!rules) return null;
  const { pattern, maxLength } = rules.value;
  if (kind === "label" && ((maxLength !== null && length(value) > maxLength) || (pattern !== null && (await test(pattern, value)) === false))) {
    return `A label value: up to ${maxLength ?? 63} letters, digits, '-', '_' or '.', starting and ending with a letter or digit.`;
  }
  if (kind === "annotation" && rules.maxValueBytes !== null && bytesOf(value) > rules.maxValueBytes) return `Up to ${rules.maxValueBytes} bytes.`;
  return null;
}

/** The problems of a whole table, by row id, and those of the table itself: its count and, for annotations, its bytes. */
export interface ExtraCheck { rows: Record<number, { key: string | null; value: string | null }>; table: string[] }

export async function checkExtras(form: MetaForm, kind: Kind, rows: ExtraRow[], test: PatternTest): Promise<ExtraCheck> {
  const out: ExtraCheck = { rows: {}, table: [] };
  for (const r of rows) out.rows[r.id] = { key: await checkExtraKey(form, kind, r.key, rows, test), value: await checkExtraValue(form, kind, r.value, test) };
  const rules = form.otherKeys[kind];
  if (rules && rows.length > rules.max) out.table.push(`At most ${rules.max} additional ${kind}s.`);
  const total = rows.reduce((n, r) => n + bytesOf(r.value), 0);
  if (kind === "annotation" && rules?.maxBytesTotal != null && total > rules.maxBytesTotal) out.table.push(`The additional annotations hold more than ${rules.maxBytesTotal} bytes in all.`);
  return out;
}

/** The expiry rules of an environment, or null where it takes no date at create (off, unlisted, or not at create). */
export function expiryRulesOf(form: MetaForm, environment: string): ExpiryRules | null {
  const rules = form.expiration[environment];
  return rules?.enabled && rules.allowedAtCreate ? rules : null;
}

/** What the form knows of an expiry date: none (permanent), a date not after today or not a date, or a date in N days. */
export type ExpiryInfo = { state: "none" } | { state: "bad"; error: string } | { state: "date"; date: string; days: number; beyond: boolean };

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;

/**
 * An expiry date against its environment's rules, counted from `today` (a calendar date, as cmapi's). Past
 * maxLifetimeDays it is allowed with one more approval (design P12, D15): a warning, never a refusal. The limit never sets
 * a date: an empty value is a permanent namespace.
 */
export function expiryInfo(value: string, today: string, rules: ExpiryRules): ExpiryInfo {
  if (value === "") return { state: "none" };
  const at = Date.parse(`${value}T00:00:00Z`);
  if (!ISO_DAY.test(value) || Number.isNaN(at) || new Date(at).toISOString().slice(0, 10) !== value) return { state: "bad", error: "Enter a date as YYYY-MM-DD." };
  const days = Math.round((at - Date.parse(`${today}T00:00:00Z`)) / 864e5);
  if (days < 1) return { state: "bad", error: "Pick a date after today." };
  return { state: "date", date: value, days, beyond: days > rules.maxLifetimeDays };
}

/** "14, 7 and 1": a list of numbers in words. */
export function listWords(items: number[]): string {
  return items.length < 2 ? items.join("") : `${items.slice(0, -1).join(", ")} and ${items.at(-1)}`;
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
