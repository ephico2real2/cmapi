// The optional expiry date of the New namespace form (#479 P12): a PatternFly DatePicker, empty by default, which means a
// permanent namespace. Its rules are the environment's entry of x-cmapi-expiration (GET /api/v1/metadata-keys, A11, D15):
// where expiration is off, or not taken at create, the field is not shown and a note says why. maxLifetimeDays is a limit,
// never a default: past it the field warns that one more approval is needed, and cmapi decides.
import { Button, DatePicker, Flex, FlexItem, FormGroup, FormHelperText, HelperText, HelperTextItem, yyyyMMddFormat } from "@patternfly/react-core";
import { useMemo } from "react";
import { Hint } from "../components/ui";
import type { ExpiryRules } from "./metadataForm";
import { expiryInfo, listWords } from "./metadataForm";

/** Where the environment takes no date at create: why, in the words of its rules. */
function offNote(rules: ExpiryRules | undefined): string {
  if (rules?.enabled) {
    return "This environment takes no expiry at create (expiration.yaml: allowedAtCreate: false). The namespace is permanent; set a date later from the Expiration tab.";
  }
  return "Expiration is turned off for this environment (expiration.yaml: enabled: false). The namespace is permanent.";
}

/**
 * The picker's own reading of the text (yyyy-MM-dd, local midnight), but strict: a day that the month lacks is no date.
 * Chrome's Date reads 2099-02-30 as 2 March (MDN, Date.parse: implementation-specific), so the picker would take it.
 */
function strictDay(text: string): Date {
  const date = new Date(`${text}T00:00:00`);
  return /^\d{4}-\d{2}-\d{2}$/.test(text) && yyyyMMddFormat(date) === text ? date : new Date(NaN);
}

export function ExpiryField({ rules, value, today, refused, onChange }: {
  /** The environment's entry of x-cmapi-expiration; undefined when the environment is not listed (off). */
  rules: ExpiryRules | undefined;
  value: string;
  /** Today as a calendar date (YYYY-MM-DD), from which the days are counted. */
  today: string;
  /** cmapi's refusal of the date (expiration-*), shown on the field (P8); null when there is none. */
  refused: string | null;
  onChange: (value: string) => void;
}) {
  // The calendar offers no day up to today, and the picker shows this message for a typed one (its own error line, after
  // the field loses the focus); the form's Check lists it too, so nothing is sent with it. One array per day: the picker
  // checks the date again whenever its validators change.
  const validators = useMemo(() => [(date: Date) => (yyyyMMddFormat(date) <= today ? "Pick a date after today." : "")], [today]);
  if (!rules?.enabled || !rules.allowedAtCreate) {
    return <Hint id="ns-exp-off">{offNote(rules)}</Hint>;
  }
  const info = expiryInfo(value, today, rules);
  const days = info.state === "date"
    ? `Expires on ${info.date}, in ${info.days} day${info.days === 1 ? "" : "s"}.${info.beyond ? ` More than ${rules.maxLifetimeDays} days: needs one more approval.` : ""}`
    : info.state === "none" ? "No expiry: the namespace is permanent." : "";
  return (
    <FormGroup label="Expires (optional)" fieldId="ns-exp">
      <Flex gap={{ default: "gapSm" }} alignItems={{ default: "alignItemsFlexStart" }}>
        <FlexItem>
          <DatePicker value={value} onChange={(_, v) => onChange(v)} validators={validators} dateParse={strictDay} invalidFormatText="Enter a date as YYYY-MM-DD."
            aria-label="Expires (optional)" buttonAriaLabel="Open the calendar"
            inputProps={{ id: "ns-exp", "aria-describedby": `${refused ? "ns-exp-refused " : ""}ns-exp-days ns-exp-help`, ...(refused ? { validated: "error" as const } : {}) }} />
        </FlexItem>
        <FlexItem>
          <Button variant="secondary" size="sm" onClick={() => onChange("")}>No expiry</Button>
        </FlexItem>
      </Flex>
      <FormHelperText>
        <HelperText>
          {refused && <HelperTextItem id="ns-exp-refused" variant="error">{refused}</HelperTextItem>}
          <HelperTextItem id="ns-exp-days" variant={info.state === "date" && info.beyond ? "warning" : "default"}>{days}</HelperTextItem>
          <HelperTextItem id="ns-exp-help">
            {`Notices to the team DL ${listWords(rules.notifyDaysBefore)} days before. It keeps running ${rules.graceDays} days after the date.`}
          </HelperTextItem>
        </HelperText>
      </FormHelperText>
    </FormGroup>
  );
}
