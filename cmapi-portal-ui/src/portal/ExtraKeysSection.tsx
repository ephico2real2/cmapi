// The additional labels and annotations of the New namespace form (#479 P9-P11, #365): keys beyond the declared ones, in
// two key/value tables inside one PatternFly ExpandableSection that is closed and empty by default, so nothing is sent
// that the person did not add. Each row is checked as it is typed against the rules that GET /api/v1/metadata-keys
// publishes for undeclared keys (propertyNames, additionalProperties, x-cmapi-other-keys; checkExtras in metadataForm.ts).
// Closing the section keeps the rows: they stay in the request, and in the preview.
import { Button, ExpandableSection, Flex, FlexItem, FormHelperText, HelperText, HelperTextItem, Stack, TextInput } from "@patternfly/react-core";
import { TimesIcon } from "@patternfly/react-icons";
import { Table, Tbody, Td, Th, Thead, Tr } from "@patternfly/react-table";
import { Hint, Small } from "../components/ui";
import type { ExtraCheck, ExtraRow, Kind, MetaForm, OtherKeys } from "./metadataForm";
import { bytesOf } from "./metadataForm";

const WORDS = { label: { one: "label", many: "labels", title: "Additional labels", add: "+ Add label" },
  annotation: { one: "annotation", many: "annotations", title: "Additional annotations", add: "+ Add annotation" } } as const;
const ID = { label: "xl", annotation: "xa" } as const;

/** The id of a row's input: by kind and the row's own id, so no text that the person types reaches an id. */
export const extraInputId = (kind: Kind, id: number, part: "key" | "value"): string => `ns-${ID[kind]}-${id}-${part}`;

/** "1 label, 0 annotations", or "none": the count that the closed section shows. */
export function extraCount(rows: Record<Kind, ExtraRow[]>): string {
  const n = rows.label.length, m = rows.annotation.length;
  if (!n && !m) return "none";
  return `${n} ${n === 1 ? WORDS.label.one : WORDS.label.many}, ${m} ${m === 1 ? WORDS.annotation.one : WORDS.annotation.many}`;
}

/** The allowed prefixes in the mockup's words: "Allowed: no prefix, or *.company.net/." */
const allowedWords = (rules: OtherKeys): string => `Allowed: ${rules.prefixes.map((p) => (p === "" ? "no prefix" : p)).join(", or ")}.`;

/** A placeholder key under the first named prefix: "e.g. example.company.net/key". Never a value: it is grey hint text. */
const keyPlaceholder = (rules: OtherKeys): string => {
  const named = rules.prefixes.find((p) => p !== "");
  return `e.g. ${named ? named.replace(/^\*\./, "example.") : ""}key`;
};

function counterOf(kind: Kind, rules: OtherKeys, rows: ExtraRow[]): string {
  const count = `${rows.length} of ${rules.max}`;
  if (kind !== "annotation" || rules.maxBytesTotal === null) return count;
  return `${count} · ${rows.reduce((n, r) => n + bytesOf(r.value), 0)} of ${rules.maxBytesTotal} bytes`;
}

function KeyTable({ kind, rules, rows, check, shown, onChange, onAdd }: {
  kind: Kind;
  rules: OtherKeys;
  rows: ExtraRow[];
  check: ExtraCheck | undefined;
  /** Whether a row's problem shows: an empty new row says "Enter a key." only once the person tried the form. */
  shown: (row: ExtraRow, problem: string | null) => string | null;
  onChange: (rows: ExtraRow[]) => void;
  onAdd: () => void;
}) {
  const w = WORDS[kind];
  const set = (id: number, part: "key" | "value", text: string) =>
    onChange(rows.map((r) => (r.id === id ? { ...r, [part]: part === "key" ? text.trim() : text } : r)));
  return (
    <Stack hasGutter>
      <Flex justifyContent={{ default: "justifyContentSpaceBetween" }} alignItems={{ default: "alignItemsBaseline" }}>
        <FlexItem><b>{w.title}</b></FlexItem>
        <FlexItem><Small>{counterOf(kind, rules, rows)}</Small></FlexItem>
      </Flex>
      <Table aria-label={w.title} variant="compact" gridBreakPoint="grid-md">
        <Thead><Tr><Th>Key</Th><Th>Value</Th><Th screenReaderText="Remove" /></Tr></Thead>
        <Tbody>
          {rows.length === 0 && <Tr><Td colSpan={3}><Small>None. Add one only if you need it.</Small></Td></Tr>}
          {rows.map((r, i) => {
            const keyError = shown(r, check?.rows[r.id]?.key ?? null), valueError = check?.rows[r.id]?.value ?? null;
            const keyId = extraInputId(kind, r.id, "key"), valueId = extraInputId(kind, r.id, "value");
            return (
              <Tr key={r.id}>
                <Td dataLabel="Key">
                  <TextInput id={keyId} value={r.key} aria-label={`Key of additional ${w.one} ${i + 1}`} placeholder={keyPlaceholder(rules)}
                    validated={keyError ? "error" : "default"} aria-describedby={keyError ? `${keyId}-error` : undefined} spellCheck={false} autoComplete="off"
                    onChange={(_, v) => set(r.id, "key", v)} />
                  {keyError && <FormHelperText><HelperText><HelperTextItem id={`${keyId}-error`} variant="error">{keyError}</HelperTextItem></HelperText></FormHelperText>}
                </Td>
                <Td dataLabel="Value">
                  <TextInput id={valueId} value={r.value} aria-label={`Value of additional ${w.one} ${i + 1}`} placeholder="e.g. value"
                    validated={valueError ? "error" : "default"} aria-describedby={valueError ? `${valueId}-error` : undefined} spellCheck={false} autoComplete="off"
                    onChange={(_, v) => set(r.id, "value", v)} />
                  {valueError && <FormHelperText><HelperText><HelperTextItem id={`${valueId}-error`} variant="error">{valueError}</HelperTextItem></HelperText></FormHelperText>}
                </Td>
                <Td dataLabel="Remove" modifier="fitContent">
                  <Button variant="plain" icon={<TimesIcon />} aria-label={`Remove additional ${w.one} ${i + 1}`} onClick={() => onChange(rows.filter((x) => x.id !== r.id))} />
                </Td>
              </Tr>
            );
          })}
        </Tbody>
      </Table>
      {check && check.table.length > 0 && (
        <FormHelperText><HelperText>{check.table.map((t) => <HelperTextItem key={t} variant="error">{t}</HelperTextItem>)}</HelperText></FormHelperText>
      )}
      <FlexItem><Button variant="link" isInline onClick={onAdd}>{w.add}</Button></FlexItem>
      <Hint>{kind === "label"
        ? `${allowedWords(rules)} Not a reserved prefix, a key that cmapi sets, or a key that has its own field above.`
        : `${allowedWords(rules)} Each value up to ${rules.maxValueBytes ?? "—"} bytes, ${rules.maxBytesTotal ?? "—"} in all.`}</Hint>
    </Stack>
  );
}

export function ExtraKeysSection({ form, rows, checks, attempted, expanded, onExpand, onChange, onAdd }: {
  form: MetaForm;
  rows: Record<Kind, ExtraRow[]>;
  checks: Partial<Record<Kind, ExtraCheck>>;
  attempted: boolean;
  expanded: boolean;
  onExpand: (expanded: boolean) => void;
  onChange: (kind: Kind, rows: ExtraRow[]) => void;
  onAdd: (kind: Kind) => void;
}) {
  const kinds = (["label", "annotation"] as const).filter((k) => form.otherKeys[k] !== null);
  if (!kinds.length) return null;
  const shown = (row: ExtraRow, problem: string | null) => (row.key === "" && !attempted ? null : problem);
  return (
    <ExpandableSection isExpanded={expanded} onToggle={(_, open) => onExpand(open)} toggleId="ns-extra-toggle" contentId="ns-extra"
      toggleContent={<>Additional labels and annotations (optional) <Small>{extraCount(rows)}</Small></>}>
      <Stack hasGutter>
        {kinds.map((k) => (
          <KeyTable key={k} kind={k} rules={form.otherKeys[k]!} rows={rows[k]} check={checks[k]} shown={shown}
            onChange={(next) => onChange(k, next)} onAdd={() => onAdd(k)} />
        ))}
      </Stack>
    </ExpandableSection>
  );
}
