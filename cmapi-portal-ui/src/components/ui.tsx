// The PatternFly compositions the tabs share. Each mockup pattern maps to one component here.
import {
  Alert, Button, Card, CardBody, CardHeader, CardTitle, CodeBlock, CodeBlockCode, Content, DescriptionList, DescriptionListDescription,
  DescriptionListGroup, DescriptionListTerm, EmptyState, Flex, FlexItem, FormHelperText, HelperText, HelperTextItem, Icon, Label, List, ListItem,
  Progress, Split, SplitItem, Stack, StackItem, Title, ToggleGroup, ToggleGroupItem
} from "@patternfly/react-core";
import { InnerScrollContainer, Table, Tbody, Td, Th, Thead, Tr } from "@patternfly/react-table";
import type { ReactNode } from "react";

const STATUS = { ok: "success", warn: "warning", bad: "danger", info: "info", fail: "danger", pass: "success" } as const;
type Tone = keyof typeof STATUS;
const statusOf = (tone?: string) => STATUS[tone as Tone];

/** A status word. PatternFly carries the colour and the icon; the word is always there. */
export function Pill({ tone, children }: { tone?: string; children: ReactNode }) {
  const status = statusOf(tone);
  return status ? <Label isCompact status={status}>{children}</Label> : <Label isCompact color="grey">{children}</Label>;
}

export function Callout({ tone, title, children }: { tone?: string; title: ReactNode; children?: ReactNode }) {
  return <Alert isInline variant={statusOf(tone) ?? "info"} title={title}>{children}</Alert>;
}

export interface Check {
  s?: string;
  mark?: string;
  main: ReactNode;
  note?: ReactNode;
}

export function Checks({ items }: { items: Check[] }) {
  return (
    <List isPlain>
      {items.map((c, i) => (
        <ListItem key={i} icon={<Icon status={statusOf(c.s)}>{c.mark}</Icon>}>
          {c.main} <Small>{c.note}</Small>
        </ListItem>
      ))}
    </List>
  );
}

export function KV({ rows }: { rows: { k: ReactNode; v: ReactNode }[] }) {
  return (
    <DescriptionList isHorizontal isCompact>
      {rows.map((r, i) => (
        <DescriptionListGroup key={i}>
          <DescriptionListTerm>{r.k}</DescriptionListTerm>
          <DescriptionListDescription>{r.v}</DescriptionListDescription>
        </DescriptionListGroup>
      ))}
    </DescriptionList>
  );
}

export const Small = ({ children }: { children: ReactNode }) => <Content component="small">{children}</Content>;

export const Empty = ({ children }: { children: string }) => <EmptyState variant="xs" headingLevel="h4" titleText={children} />;

export function Head({ title, lede, pill }: { title: string; lede?: ReactNode; pill?: ReactNode }) {
  return (
    <Split hasGutter isWrappable>
      <SplitItem isFilled>
        <Title headingLevel="h1" size="2xl">{title}</Title>
        <Content component="p">{lede}</Content>
      </SplitItem>
      {pill && <SplitItem>{pill}</SplitItem>}
    </Split>
  );
}

export function Panel({ title, pill, children }: { title?: ReactNode; pill?: ReactNode; children: ReactNode }) {
  return (
    <Card isCompact>
      {title && (
        <CardHeader actions={pill ? { actions: pill, hasNoOffset: true } : undefined}>
          <CardTitle component="h2">{title}</CardTitle>
        </CardHeader>
      )}
      <CardBody><Stack hasGutter className="cp-wrap">{children}</Stack></CardBody>
    </Card>
  );
}

export const Line = ({ children }: { children: ReactNode }) => <StackItem>{children}</StackItem>;

export interface Choice {
  label: ReactNode;
  sub?: ReactNode;
  n?: ReactNode;
  on?: unknown;
  pick?: () => void;
}

/** One choice out of a few: the mockup's segmented buttons and filter chips. */
export function Choices({ label, options }: { label: string; options: Choice[] }) {
  return (
    <div className="cp-scroll">
      <ToggleGroup isCompact aria-label={label}>
        {options.map((o, i) => (
          <ToggleGroupItem
            key={i}
            buttonId={`${label}-${i}`.replace(/\W+/g, "-")}
            isSelected={String(o.on) === "true"}
            onChange={() => o.pick?.()}
            text={<>{o.label}{o.n !== undefined && <> <b>{o.n}</b></>}{o.sub ? <> <Small>{o.sub}</Small></> : null}</>}
          />
        ))}
      </ToggleGroup>
    </div>
  );
}

export function Filter({ label, options }: { label: string; options: Choice[] }) {
  return (
    <Flex alignItems={{ default: "alignItemsCenter" }} gap={{ default: "gapSm" }} flexWrap={{ default: "nowrap" }}>
      <FlexItem><Small>{label}</Small></FlexItem>
      <FlexItem style={{ minWidth: 0 }}><Choices label={label} options={options} /></FlexItem>
    </Flex>
  );
}

interface PageControls {
  range?: ReactNode;
  prev?: () => void;
  next?: () => void;
  prevDis?: unknown;
  nextDis?: unknown;
}

// Next and previous only: these lists page by cursor, and PatternFly's Pagination expects to jump to any page.
export function Pager({ range, prev, next, prevDis, nextDis }: PageControls) {
  return (
    <Flex justifyContent={{ default: "justifyContentSpaceBetween" }} alignItems={{ default: "alignItemsCenter" }}>
      <FlexItem><Small>{range}</Small></FlexItem>
      <FlexItem>
        <Flex gap={{ default: "gapSm" }}>
          <Button variant="secondary" size="sm" isAriaDisabled={String(prevDis) === "true"} onClick={prev}>‹ Previous</Button>
          <Button variant="secondary" size="sm" isAriaDisabled={String(nextDis) === "true"} onClick={next}>Next ›</Button>
        </Flex>
      </FlexItem>
    </Flex>
  );
}

const BAR = { crit: "danger", warn: "warning" } as const;

/**
 * A usage meter. PatternFly hides the label from assistive technology, so valueText carries it. Progress has no threshold
 * mark, and the KPI footnote tells people to read one, so the tick sits over the bar; the label moves above the bar to let
 * the bar span the whole width.
 */
export function Meter({ title, label, value, pct, bar, mark, ariaLabel }: { title?: ReactNode; label: ReactNode; value?: unknown; pct?: string; bar?: string; mark?: string; ariaLabel?: string }) {
  const number = typeof value === "number" ? value : parseFloat(String(value ?? pct));
  const progress = (
    <Progress
      size="sm"
      title={title}
      aria-label={title ? undefined : ariaLabel}
      value={Number.isFinite(number) ? number : 0}
      label={label}
      valueText={typeof label === "string" ? label : undefined}
      measureLocation={mark ? "top" : "outside"}
      variant={BAR[bar as keyof typeof BAR]}
    />
  );
  if (!mark) return progress;
  return (
    <div className="cp-meter">
      {progress}
      <span className="cp-mark" style={{ insetInlineStart: mark }} aria-hidden="true" />
    </div>
  );
}

export function Code({ label, text }: { label?: ReactNode; text: string }) {
  return (
    <div>
      {label && <Small>{label}</Small>}
      <CodeBlock><CodeBlockCode className="cp-pre-line">{text}</CodeBlockCode></CodeBlock>
    </div>
  );
}

export function Hint({ children }: { children: ReactNode }) {
  return <FormHelperText><HelperText><HelperTextItem>{children}</HelperTextItem></HelperText></FormHelperText>;
}

// A blank column heading stays blank on screen, as in the mockup; blank names it for a screen reader.
export function DataTable<T>({ label, cols, rows, cells, selected, blank = "Action" }: { label: string; cols: string[]; rows: T[]; cells: (row: T) => ReactNode[]; selected?: (row: T) => boolean; blank?: string }) {
  return (
    <InnerScrollContainer>
      <Table aria-label={label} variant="compact" gridBreakPoint="grid-md">
        <Thead>
          <Tr>{cols.map((c, i) => (c ? <Th key={i}>{c}</Th> : <Th key={i} screenReaderText={blank} />))}</Tr>
        </Thead>
        <Tbody>
          {rows.map((row, r) => (
            <Tr key={r} isRowSelected={selected?.(row)}>
              {cells(row).map((cell, c) => <Td key={c} dataLabel={cols[c] || undefined}>{cell}</Td>)}
            </Tr>
          ))}
        </Tbody>
      </Table>
    </InnerScrollContainer>
  );
}

export const RowButton = ({ onClick, children }: { onClick?: () => void; children: ReactNode }) => (
  <Button variant="secondary" size="sm" onClick={onClick}>{children}</Button>
);
