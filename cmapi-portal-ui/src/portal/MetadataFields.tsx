// The labels or the annotations of the New namespace form, from the instance's rules (GET /api/v1/metadata-keys, #336).
// A key that cmapi sets is a read-only input with the value it will write, marked "automatic" (#479 P3); a key with a
// default copies its source until the person edits it, marked "from <source>" meanwhile (P4); the other keys are inputs.
// The field's words are the config's (title, description, example) and the rule's.
import {
  FormGroup, FormHelperText, FormSection, FormSelect, FormSelectOption, Grid, GridItem, HelperText, HelperTextItem, Label, TextInput
} from "@patternfly/react-core";
import type { MetaField, Source } from "./metadataForm";
import { derivedValue, valueKey } from "./metadataForm";

const SECTION = { label: "Labels", annotation: "Annotations" } as const;

/** The ids of a field's helper text: the error, when there is one, then the field's words. */
export const helpIds = (f: MetaField, error: string | null | undefined): string => (error ? `${f.id}-error ${f.id}-help` : `${f.id}-help`);

/** The accessible name of a field: its title, else its key, then "(required)" or "(optional)" for an input (WCAG 2.2, 3.3.2). */
export const fieldName = (f: MetaField): string => (f.derivedFrom !== null ? f.title ?? f.key : `${f.title ?? f.key} (${f.required ? "required" : "optional"})`);

function Help({ field, error, note }: { field: MetaField; error?: string | null; note?: string }) {
  return (
    <FormHelperText>
      <HelperText>
        {error && <HelperTextItem id={`${field.id}-error`} variant="error">{error}</HelperTextItem>}
        <HelperTextItem id={`${field.id}-help`}>
          {field.title !== null && <code>{field.key}</code>}{field.title !== null && " "}{field.description}{note && ` ${note}`}
        </HelperTextItem>
      </HelperText>
    </FormHelperText>
  );
}

export interface FieldProps {
  field: MetaField;
  value: string;
  error?: string | null;
  target: Record<Source, string>;
  /** The field that this one copies, while the person has not edited it (default.from); null otherwise. */
  copiesFrom?: MetaField | null;
  /** The source of this field's default, edited or not, for its hint. */
  defaultSource?: MetaField | null;
  onChange: (value: string) => void;
}

/**
 * The input of a field that the person fills: a select for an enum, else a text input with the format's keyboard. The New
 * namespace form puts it under its label (Field); the Namespaces tab puts it in the "Your change" cell of the key's row,
 * named by aria-label (#484). One input for both, so a change is checked and typed as a create is.
 */
export function FieldInput({ field, value, error, describedBy, label, emptyOption = true, onChange }: {
  field: MetaField;
  value: string;
  error?: string | null;
  describedBy: string;
  /** The accessible name when no visible label names the input. */
  label?: string;
  /** Whether a select offers "—": a create starts with nothing chosen; a change starts from the value Git holds. */
  emptyOption?: boolean;
  onChange: (value: string) => void;
}) {
  const validated = error ? "error" : "default";
  if (field.enum) {
    // No preselected value: an example is a sample, not a default, so nothing is sent that the person did not choose.
    return (
      <FormSelect id={field.id} value={value} isRequired={field.required} validated={validated} aria-describedby={describedBy} aria-label={label}
        onChange={(_, v) => onChange(v)}>
        {emptyOption && <FormSelectOption value="" label="—" />}
        {field.enum.map((v) => <FormSelectOption key={v} value={v} label={v} />)}
      </FormSelect>
    );
  }
  // email-in-domains: the browser's own address check agrees with cmapi's (#336, design B, section 2). url: type=url would
  // refuse addresses that cmapi accepts, so it is text with the URL keyboard.
  const type = field.format === "email-in-domains" ? "email" : "text";
  return (
    <TextInput id={field.id} type={type} inputMode={field.format === "url" ? "url" : undefined} isRequired={field.required} value={value}
      placeholder={field.example ?? undefined} validated={validated} aria-describedby={describedBy} aria-label={label} spellCheck={false} autoComplete="off"
      onChange={(_, v) => onChange(v)} />
  );
}

/** One field: its label says required or optional in words, not by an asterisk alone (WCAG 2.2, 3.3.2). */
export function Field({ field, value, error, target, copiesFrom = null, defaultSource = null, onChange }: FieldProps) {
  const describedBy = helpIds(field, error);
  if (field.derivedFrom !== null) {
    // Read-only, not disabled: it stays in the tab order and a screen reader reads it (WAI-ARIA, aria-readonly). Never sent.
    return (
      <FormGroup label={fieldName(field)} fieldId={field.id} labelInfo={<Label isCompact>automatic</Label>}>
        <TextInput id={field.id} readOnlyVariant="default" value={derivedValue(field, target)} aria-describedby={describedBy} />
        <Help field={field} error={error} />
      </FormGroup>
    );
  }
  const label = fieldName(field);
  const info = copiesFrom ? <Label isCompact color="blue">{`from ${copiesFrom.title ?? copiesFrom.key}`}</Label> : undefined;
  const note = defaultSource ? `Filled from ${defaultSource.title ?? defaultSource.key}; you can change it.` : undefined;
  return (
    <FormGroup label={label} fieldId={field.id} labelInfo={info}>
      <FieldInput field={field} value={value} error={error} describedBy={describedBy} onChange={onChange} />
      <Help field={field} error={error} note={note} />
    </FormGroup>
  );
}

/**
 * One kind's section: "Labels" or "Annotations", so a key that is both says which one each field is (WCAG 2.2, 2.4.6). The
 * keys that cmapi sets come first, then the required inputs, then the optional ones, as the mockup orders them. `skip` is
 * the key that the Name section shows (the one that starts the name).
 */
export function MetadataSection({ kind, fields, values, typed, errors, target, skip, sourceOf, onChange }: {
  kind: MetaField["kind"];
  fields: MetaField[];
  /** The values shown: typed, with each unedited default copied from its source. */
  values: Record<string, string>;
  /** What the person typed: a default field is edited once its key is here. */
  typed: Record<string, string>;
  errors: Record<string, string | null | undefined>;
  target: Record<Source, string>;
  skip: MetaField | null;
  sourceOf: (field: MetaField) => MetaField | null;
  onChange: (field: MetaField, value: string) => void;
}) {
  const mine = fields.filter((f) => f.kind === kind && f !== skip);
  if (!mine.length) return null;
  const ordered = [
    ...mine.filter((f) => f.derivedFrom !== null),
    ...mine.filter((f) => f.derivedFrom === null && f.required),
    ...mine.filter((f) => f.derivedFrom === null && !f.required)
  ];
  return (
    <FormSection title={SECTION[kind]} titleElement="h3">
      <Grid hasGutter>
        {ordered.map((f) => {
          const source = sourceOf(f);
          return (
            <GridItem md={6} key={f.id}>
              <Field field={f} value={values[valueKey(f)] ?? ""} error={errors[f.id]} target={target} defaultSource={source}
                copiesFrom={source && !(valueKey(f) in typed) ? source : null} onChange={(v) => onChange(f, v)} />
            </GridItem>
          );
        })}
      </Grid>
    </FormSection>
  );
}
