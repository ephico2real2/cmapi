// The namespace name of the New namespace form (#479 P2): `<start>-<desired>-<end>`, a PatternFly input group with the two
// ends locked. The start is the value of the key that has x-cmapi-namespace-prefix (the mnemonic), the end the value of
// the key that has x-cmapi-namespace-suffix (the cluster's environment, which cmapi fills in). The person types only the
// middle, so neither end can be typed twice or wrong. An instance whose keys make neither end gets one plain input for the
// whole name. The full name and its length are shown under it.
import { FormGroup, FormHelperText, HelperText, HelperTextItem, InputGroup, InputGroupItem, InputGroupText, TextInput } from "@patternfly/react-core";
import { LockIcon } from "@patternfly/react-icons";
import type { MetaField, Source } from "./metadataForm";
import { joinName, NAME_MAX } from "./metadataForm";

const FROM_TARGET: Record<Source, string> = {
  namespace: "the namespace", environment: "the cluster's environment", cluster: "the cluster", instance: "the instance"
};

/** Where an end's value comes from, in words: a key that cmapi fills from the target, or the field that the person fills. */
const sourceWords = (f: MetaField): string => (f.derivedFrom !== null ? FROM_TARGET[f.derivedFrom] : f.title ?? f.key);

/** The hint under the field: which end comes from where, so the locked text is explained in visible words. */
function hintOf(start: MetaField | null, end: MetaField | null): string {
  if (start && end) return `The start comes from ${sourceWords(start)} and the end from ${sourceWords(end)}. Type only the middle.`;
  if (start) return `The start comes from ${sourceWords(start)}. Type the rest.`;
  if (end) return `The end comes from ${sourceWords(end)}. Type the start.`;
  return "Any DNS-1123 name. Not allowed: reserved names (default, openshift-*, kube-*, cmapi-system, ocp-*) and a name already on the cluster outside cmapi.";
}

/** A locked end: the lock and the text, never editable here. "…" stands for a start that is not typed yet, as in the mockup. */
const Locked = ({ id, text }: { id: string; text: string }) => (
  <InputGroupText id={id}><LockIcon aria-hidden="true" /> {text}</InputGroupText>
);

export function NamespaceNameField({ start, end, startValue, endValue, desired, full, error, onChange }: {
  start: MetaField | null;
  end: MetaField | null;
  /** The ends' values; null where the instance has no such end. */
  startValue: string | null;
  endValue: string | null;
  /** The part that the person types: the middle, or the whole name when the instance has neither end. */
  desired: string;
  full: string;
  error: string | null;
  onChange: (desired: string) => void;
}) {
  const required = start === null || end === null;
  const described = ["ns-name-help", "ns-name-full", ...(start ? ["ns-name-start"] : []), ...(end ? ["ns-name-end"] : []), ...(error ? ["ns-name-error"] : [])];
  const input = (
    <TextInput id="ns-name" isRequired={required} value={desired} validated={error ? "error" : "default"} aria-describedby={described.join(" ")}
      spellCheck={false} autoComplete="off" onChange={(_, v) => onChange(v)} />
  );
  return (
    <FormGroup label={required ? "Namespace (required)" : "Namespace"} fieldId="ns-name">
      {start || end ? (
        <InputGroup>
          {start && <InputGroupItem><Locked id="ns-name-start" text={`${startValue || "…"}-`} /></InputGroupItem>}
          <InputGroupItem isFill>{input}</InputGroupItem>
          {end && <InputGroupItem><Locked id="ns-name-end" text={`-${endValue || "…"}`} /></InputGroupItem>}
        </InputGroup>
      ) : input}
      <FormHelperText>
        <HelperText>
          {error && <HelperTextItem id="ns-name-error" variant="error">{error}</HelperTextItem>}
          <HelperTextItem id="ns-name-help">
            {hintOf(start, end)}
            {startValue && endValue && ` Leave empty for a team-wide namespace: ${joinName(startValue, "", endValue)}.`}
          </HelperTextItem>
          <HelperTextItem id="ns-name-full">
            Will be created as <code>{full}</code> {`(${[...full].length} of ${NAME_MAX} characters)`}
          </HelperTextItem>
        </HelperText>
      </FormHelperText>
    </FormGroup>
  );
}
