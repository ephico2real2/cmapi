// The "Missing metadata" fields (#739): one input for each required key that the namespace lacks, and the optional ones
// behind "More". A key that cmapi fills in or that starts the name is shown read-only with the one value the API gives, and
// can be selected for the request. The Adopt form and the Namespaces tab's "Add missing metadata" show the same fields (missingKeys.ts).
import {
  Checkbox, ExpandableSection, FormGroup, FormHelperText, Grid, GridItem, HelperText, HelperTextItem, Label, TextInput
} from "@patternfly/react-core";
import { useState } from "react";
import { FieldInput } from "./MetadataFields";
import type { MissingField } from "./missingKeys";
import { Small } from "../components/ui";

/** Why a field is read-only, in the words of the create form (#479 P3). */
const fixedWhy = (f: MissingField): string =>
  f.field.derivedFrom !== null ? `cmapi fills it in from the ${f.field.derivedFrom}.` : "It is the start of the namespace name.";

function One({ f, value, error, prefix, onChange }: { f: MissingField; value: string; error: string | null; prefix: string; onChange: (value: string) => void }) {
  const id = `${prefix}-${f.field.id}`;
  const label = `${f.field.title ?? f.field.key} (${f.required ? "required" : "optional"})`;
  const describedBy = error ? `${id}-error ${id}-help` : `${id}-help`;
  const help = (
    <FormHelperText>
      <HelperText>
        {error && <HelperTextItem id={`${id}-error`} variant="error">{error}</HelperTextItem>}
        <HelperTextItem id={`${id}-help`}>
          <code>{`${f.field.kind} ${f.field.key}`}</code> {f.fixed !== null ? fixedWhy(f) : f.field.description}
        </HelperTextItem>
      </HelperText>
    </FormHelperText>
  );
  const fixed = f.fixed;
  if (fixed !== null) {
    // Read-only, not disabled: it stays in the tab order and a screen reader reads it (WAI-ARIA, aria-readonly).
    return (
      <FormGroup label={label} fieldId={id} labelInfo={<Label isCompact>{f.field.derivedFrom !== null ? "automatic" : "from the name"}</Label>}>
        <Checkbox id={`${id}-include`} label={`Add ${f.field.title ?? f.field.key}`}
          isChecked={value === fixed} onChange={(_, checked) => onChange(checked ? fixed : "")} />
        <TextInput id={id} readOnlyVariant="default" value={fixed} aria-describedby={describedBy} />
        {help}
      </FormGroup>
    );
  }
  return (
    <FormGroup label={label} fieldId={id}>
      <FieldInput field={{ ...f.field, id }} value={value} error={error} describedBy={describedBy} onChange={onChange} />
      {help}
    </FormGroup>
  );
}

/**
 * The fields of the keys a namespace lacks. `prefix` keeps each input's id apart from the same key's input elsewhere on the
 * page. With no missing key, it says so in one line.
 */
export function MissingMetadata({ fields, values, errors, prefix, onChange }: {
  fields: MissingField[];
  values: Record<string, string>;
  errors: Record<string, string | null>;
  prefix: string;
  onChange: (f: MissingField, value: string) => void;
}) {
  const required = fields.filter((f) => f.required), optional = fields.filter((f) => !f.required);
  // "More" opens by itself when an optional field holds a value or an error, so nothing sent is hidden.
  const [more, setMore] = useState(false);
  const moreOpen = more || optional.some((f) => (values[f.id] ?? "") !== "" || errors[f.id]);
  const grid = (list: MissingField[]) => (
    <Grid hasGutter>
      {list.map((f) => (
        <GridItem md={6} key={f.id}>
          <One f={f} value={values[f.id] ?? ""} error={errors[f.id] ?? null} prefix={prefix} onChange={(v) => onChange(f, v)} />
        </GridItem>
      ))}
    </Grid>
  );
  if (!fields.length) return <Small>The namespace has every key that the rules declare.</Small>;
  return (
    <>
      {required.length > 0 ? grid(required) : <Small>No required key is missing.</Small>}
      {optional.length > 0 && (
        <ExpandableSection toggleText={moreOpen ? "Fewer keys" : `More: ${optional.length} optional key${optional.length > 1 ? "s" : ""}`}
          isExpanded={moreOpen} onToggle={(_, open) => setMore(open)} toggleId={`${prefix}-more`}>
          {grid(optional)}
        </ExpandableSection>
      )}
    </>
  );
}
