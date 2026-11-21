// The PatternFly compositions the tabs share. Each mockup pattern maps to one component here.
import {
  Alert, Badge, Button, Card, CardBody, CardExpandableContent, CardHeader, CardTitle, CodeBlock, CodeBlockCode, Content, DescriptionList, DescriptionListDescription,
  DescriptionListGroup, DescriptionListTerm, EmptyState, Flex, FlexItem, FormHelperText, HelperText, HelperTextItem, Icon, Label, List, ListItem,
  Progress, Split, SplitItem, Stack, StackItem, Title, ToggleGroup, ToggleGroupItem
} from "@patternfly/react-core";
import { InnerScrollContainer, Table, Tbody, Td, Th, Thead, Tr } from "@patternfly/react-table";
import { useId } from "react";
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

/**
 * A Panel that opens and closes, with its count beside the title: PatternFly's expandable Card (isExpanded, onExpand and
 * CardExpandableContent, which renders nothing while closed). PatternFly's card accessibility page requires toggleButtonProps
 * with aria-expanded, and an aria-labelledby that names the CardTitle; the count is in the name too (#537).
 */
export function Section({ title, count, open, onToggle, children }: { title: ReactNode; count?: ReactNode; open: boolean; onToggle: () => void; children: ReactNode }) {
  const id = useId();
  return (
    <Card isCompact isExpanded={open}>
      <CardHeader onExpand={onToggle} toggleButtonProps={{ id: `${id}-toggle`, "aria-labelledby": `${id}-title${count === undefined ? "" : ` ${id}-count`}`, "aria-expanded": open, "aria-controls": `${id}-content` }}>
        <Flex alignItems={{ default: "alignItemsCenter" }} gap={{ default: "gapSm" }} flexWrap={{ default: "nowrap" }}>
          <CardTitle id={`${id}-title`} component="h2">{title}</CardTitle>
          {count !== undefined && <Badge id={`${id}-count`} isRead>{count}</Badge>}
        </Flex>
      </CardHeader>
      <div id={`${id}-content`} role="region" aria-labelledby={`${id}-toggle`} hidden={!open}>
        <CardExpandableContent>
          <CardBody><Stack hasGutter className="cp-wrap">{children}</Stack></CardBody>
        </CardExpandableContent>
      </div>
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
  busy?: boolean;
  prevDis?: unknown;
  nextDis?: unknown;
}

// Next and previous only: these lists page by cursor, and PatternFly's Pagination expects to jump to any page.
export function Pager({ range, prev, next, prevDis, nextDis, busy = false }: PageControls) {
  // While the table shows the previous answer, both cursors belong to that answer.
  const disabled = (flag: unknown) => busy || String(flag) === "true";
  return (
    <Flex justifyContent={{ default: "justifyContentSpaceBetween" }} alignItems={{ default: "alignItemsCenter" }}>
      <FlexItem><Small>{range}</Small></FlexItem>
      <FlexItem>
        <Flex gap={{ default: "gapSm" }}>
          <Button variant="secondary" size="sm" isAriaDisabled={disabled(prevDis)} onClick={prev}>‹ Previous</Button>
          <Button variant="secondary" size="sm" isAriaDisabled={disabled(nextDis)} onClick={next}>Next ›</Button>
        </Flex>
      </FlexItem>
    </Flex>
  );
}

/**
 * The numbered pages of a list (#537): every page up to 7; past that the first and the last page always, the current page
 * with its neighbours, and 0 where pages are left out. Seven slots at most, as the U.S. Web Design System's pagination;
 * the mockup's pageSlots() is the same rule.
 */
export function pageSlots(page: number, last: number): number[] {
  const range = (a: number, b: number) => Array.from({ length: b - a + 1 }, (_, i) => a + i);
  if (last <= 7) return range(1, last);
  if (page <= 4) return [...range(1, 5), 0, last];
  if (page >= last - 3) return [1, 0, ...range(last - 4, last)];
  return [1, 0, page - 1, page, page + 1, 0, last];
}

export const PAGE_SIZES = [25, 50, 100];

interface NumberedPages {
  label: string;
  total: number;
  page: number;
  perPage: number;
  onPage: (page: number) => void;
  onPerPage: (perPage: number) => void;
}

/**
 * "1–25 of 80", 25, 50 or 100 a page, and ‹ 1 2 3 … N › for a list the browser holds whole. PatternFly 6.7's Pagination has
 * no numbered pages (first, previous, a page field, next, last) and does not export its per-page menu, so this is built from
 * its parts: a nav named by `label`, aria-current="page" on the page shown (MDN, aria-current), and the Per page chips of
 * the Quotas tab.
 */
export function NumberedPager({ label, total, page, perPage, onPage, onPerPage }: NumberedPages) {
  const last = Math.max(1, Math.ceil(total / perPage));
  const from = total ? (page - 1) * perPage + 1 : 0;
  const sizes = PAGE_SIZES.map((n) => ({ label: String(n), on: n === perPage, pick: () => onPerPage(n) }));
  return (
    <Flex justifyContent={{ default: "justifyContentSpaceBetween" }} alignItems={{ default: "alignItemsCenter" }} gap={{ default: "gapMd" }}>
      <FlexItem><Small>{`${from}–${Math.min(total, page * perPage)} of ${total}`}</Small></FlexItem>
      <FlexItem><Filter label="Per page" options={sizes} /></FlexItem>
      <FlexItem>
        <nav aria-label={label}>
          <Flex gap={{ default: "gapXs" }} alignItems={{ default: "alignItemsCenter" }}>
            <Button variant="secondary" size="sm" aria-label="Previous page" isAriaDisabled={page <= 1} onClick={() => onPage(page - 1)}>‹</Button>
            {pageSlots(page, last).map((n, i) => (n === 0
              ? <span key={`gap-${i}`} aria-hidden="true">…</span>
              : <Button key={n} variant={n === page ? "primary" : "secondary"} size="sm" aria-label={`Page ${n}`} aria-current={n === page ? "page" : undefined} onClick={() => onPage(n)}>{n}</Button>))}
            <Button variant="secondary" size="sm" aria-label="Next page" isAriaDisabled={page >= last} onClick={() => onPage(page + 1)}>›</Button>
          </Flex>
        </nav>
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

/** A field's helper text. Its `id` is what the field's aria-describedby names, so a screen reader reads it with the field. */
export function Hint({ id, children }: { id?: string; children: ReactNode }) {
  return <FormHelperText><HelperText><HelperTextItem id={id}>{children}</HelperTextItem></HelperText></FormHelperText>;
}

// A blank column heading stays blank on screen, as in the mockup; blank names it for a screen reader. busy marks rows that are
// the last answer's, kept on screen while the next answer loads (WAI-ARIA 1.2 aria-busy: the element is being updated).
export function DataTable<T>({ label, cols, rows, cells, selected, blank = "Action", busy = false }: { label: string; cols: string[]; rows: T[]; cells: (row: T) => ReactNode[]; selected?: (row: T) => boolean; blank?: string; busy?: boolean }) {
  return (
    <InnerScrollContainer>
      <Table aria-label={label} aria-busy={busy || undefined} variant="compact" gridBreakPoint="grid-md">
        <Thead>
          <Tr>{cols.map((c, i) => (c ? <Th key={i} modifier="nowrap">{c}</Th> : <Th key={i} screenReaderText={blank} />))}</Tr>
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
