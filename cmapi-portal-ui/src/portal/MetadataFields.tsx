// The labels or the annotations of the New namespace form, from the instance's rules (GET /api/v1/metadata-keys, #336).
// A required key is an input; a key that cmapi sets is a read-only input with the value cmapi will write; the optional
// keys wait in a collapsed group. The field's words are the config's (title, description, example) and the rule's.
import {
  ExpandableSection, FormGroup, FormHelperText, FormSection, FormSelect, FormSelectOption, Grid, GridItem, HelperText, HelperTextItem, TextInput
} from "@patternfly/react-core";
import type { MetaField, Source } from "./metadataForm";
import { derivedValue, valueKey } from "./metadataForm";

const SECTION = { label: "Labels", annotation: "Annotations" } as const;
const OPTIONAL = { label: "Optional labels", annotation: "Optional annotations" } as const;

/** The ids of a field's helper text: the error, when there is one, then the field's words. */
export const helpIds = (f: MetaField, error: string | null | undefined): string => (error ? `${f.id}-error ${f.id}-help` : `${f.id}-help`);

function Help({ field, error }: { field: MetaField; error?: string | null }) {
  return (
    <FormHelperText>
      <HelperText>
        {error && <HelperTextItem id={`${field.id}-error`} variant="error">{error}</HelperTextItem>}
        <HelperTextItem id={`${field.id}-help`}>
          {field.title !== null && <code>{field.key}</code>}{field.title !== null && " "}{field.description}
        </HelperTextItem>
      </HelperText>
    </FormHelperText>
  );
}

/** One field: its label says required or optional in words, not by an asterisk alone (WCAG 2.2, 3.3.2). */
function Field({ field, value, error, target, onChange }: {
  field: MetaField; value: string; error?: string | null; target: Record<Source, string>; onChange: (value: string) => void;
}) {
  const name = field.title ?? field.key;
  const describedBy = helpIds(field, error);
  const validated = error ? "error" : "default";
  if (field.derivedFrom !== null) {
    // Read-only, not disabled: it stays in the tab order and a screen reader reads it (WAI-ARIA, aria-readonly). Never sent.
    return (
      <FormGroup label={name} fieldId={field.id}>
        <TextInput id={field.id} readOnlyVariant="default" value={derivedValue(field, target)} aria-describedby={describedBy} />
        <Help field={field} error={error} />
      </FormGroup>
    );
  }
  const label = `${name} (${field.required ? "required" : "optional"})`;
  if (field.enum) {
    // No preselected value: an example is a sample, not a default, so nothing is sent that the person did not choose.
    return (
      <FormGroup label={label} fieldId={field.id}>
        <FormSelect id={field.id} value={value} isRequired={field.required} validated={validated} aria-describedby={describedBy}
          onChange={(_, v) => onChange(v)}>
          <FormSelectOption value="" label="—" />
          {field.enum.map((v) => <FormSelectOption key={v} value={v} label={v} />)}
        </FormSelect>
        <Help field={field} error={error} />
      </FormGroup>
    );
  }
  // email-in-domains: the browser's own address check agrees with cmapi's (#336, design B, section 2). url: type=url would
  // refuse addresses that cmapi accepts, so it is text with the URL keyboard.
  const type = field.format === "email-in-domains" ? "email" : "text";
  return (
    <FormGroup label={label} fieldId={field.id}>
      <TextInput id={field.id} type={type} inputMode={field.format === "url" ? "url" : undefined} isRequired={field.required} value={value}
        placeholder={field.example ?? undefined} validated={validated} aria-describedby={describedBy} spellCheck={false} autoComplete="off"
        onChange={(_, v) => onChange(v)} />
      <Help field={field} error={error} />
    </FormGroup>
  );
}

/** One kind's section: "Labels" or "Annotations", so a key that is both says which one each field is (WCAG 2.2, 2.4.6). */
export function MetadataSection({ kind, fields, values, errors, target, expanded, onExpand, onChange }: {
  kind: MetaField["kind"];
  fields: MetaField[];
  values: Record<string, string>;
  errors: Record<string, string | null | undefined>;
  target: Record<Source, string>;
  expanded: boolean;
  onExpand: (expanded: boolean) => void;
  onChange: (field: MetaField, value: string) => void;
}) {
  const mine = fields.filter((f) => f.kind === kind);
  const main = mine.filter((f) => f.required || f.derivedFrom !== null);
  const optional = mine.filter((f) => !f.required && f.derivedFrom === null);
  if (!mine.length) return null;
  const grid = (list: MetaField[]) => (
    <Grid hasGutter>
      {list.map((f) => (
        <GridItem md={6} key={f.id}>
          <Field field={f} value={values[valueKey(f)] ?? ""} error={errors[f.id]} target={target} onChange={(v) => onChange(f, v)} />
        </GridItem>
      ))}
    </Grid>
  );
  return (
    <FormSection title={SECTION[kind]} titleElement="h3">
      {main.length > 0 && grid(main)}
      {optional.length > 0 && (
        <ExpandableSection toggleText={`${OPTIONAL[kind]} (${optional.length})`} isExpanded={expanded} onToggle={(_, open) => onExpand(open)}>
          {grid(optional)}
        </ExpandableSection>
      )}
    </FormSection>
  );
}
