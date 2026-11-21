// The Namespaces tab's target picker (#484, design of #481, section 6 T1): the cluster first, then that cluster's namespaces.
// Choosing a cluster reads its mnemonic chips with their counts (the facets of GET .../namespaces, section 4.4). The
// lookup is a PatternFly typeahead (a TextInputGroup with a Menu listbox, the combobox keyboard of the ARIA APG): 2 or more
// characters, LOOKUP_DELAY_MS after the last key, with q, the chosen chip and limit. A first word that is one of the
// cluster's chips turns that chip on ("abc pay": abc's namespaces that contain pay). Only an option of the list, a recent
// one or the address opens a namespace: typed text never makes a target.
import {
  Button, Flex, FormGroup, FormSelect, FormSelectOption, Grid, GridItem, Menu, MenuContent, MenuFooter, MenuItem, MenuList, TextInputGroup,
  TextInputGroupMain
} from "@patternfly/react-core";
import { useEffect, useState } from "react";
import type { KeyboardEvent } from "react";
import { SUGGEST_MIN, useNamespaceList } from "../api/hooks";
import type { Cluster, NamespaceView } from "../api/hooks";
import { Choices, Hint, Small } from "../components/ui";

/** How long the lookup waits after the last key before it asks (design T1). */
export const LOOKUP_DELAY_MS = 250;
/** The most namespaces that one answer lists (design T1: limit=10). */
const LOOKUP_LIMIT = 10;
/** How many recent namespaces the tab remembers for each cluster, in this browser only. */
const RECENT_MAX = 3;
const RECENT_KEY = "cmapi.namespaces.recent";

/** The recent namespaces of each cluster. Storage can be off or full (a private window): the tab then works without them. */
function readRecent(): Record<string, string[]> {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(RECENT_KEY) ?? "{}");
    return typeof value === "object" && value !== null ? value as Record<string, string[]> : {};
  } catch {
    return {};
  }
}

/** Puts a namespace first in its cluster's recent list. */
export function rememberRecent(clusterId: string, name: string): void {
  const all = readRecent();
  all[clusterId] = [name, ...(all[clusterId] ?? []).filter((n) => n !== name)].slice(0, RECENT_MAX);
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(all));
  } catch {
    // No storage: the recent list is a convenience, never the only way back.
  }
}

/** The text as the API's two filters: a first word that is one of the chips is that chip, the rest is q. */
export function splitLookup(text: string, chips: string[]): { chip: string | null; q: string } {
  const typed = text.trim().toLowerCase();
  const first = typed.split(/[\s-]/)[0];
  if (first && first !== typed && chips.includes(first)) return { chip: first, q: typed.slice(first.length).replace(/^[\s-]+/, "") };
  return { chip: null, q: typed };
}

/** What an option says of the namespace's state: the list reads no Git, so it says pending with the holder, or what the API says. */
const stateWords = (n: NamespaceView): string => (n.sync.openRequest ? `pending ${n.sync.openRequest.requestId}` : n.sync.state);

export function NamespaceLookup({ clusters, clusterId, chipTitle, onCluster, onOpen }: {
  clusters: Cluster[];
  clusterId: string;
  /** The title of the key that starts the namespace name (namespacePrefix), which names the chips; null for none. */
  chipTitle: string | null;
  onCluster: (clusterId: string) => void;
  onOpen: (name: string) => void;
}) {
  const [picked, setPicked] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [asked, setAsked] = useState("");
  const [openList, setOpenList] = useState(false);
  const [active, setActive] = useState(-1);
  const [recent, setRecent] = useState(readRecent);
  // A new cluster starts a new lookup.
  useEffect(() => { setPicked(null); setText(""); setAsked(""); setOpenList(false); }, [clusterId]);
  useEffect(() => {
    const timer = setTimeout(() => setAsked(text), LOOKUP_DELAY_MS);
    return () => clearTimeout(timer);
  }, [text]);
  // The cluster's namespaces with no text: the count and the chips, which stay as they are while the person types.
  const whole = useNamespaceList(clusterId, { limit: LOOKUP_LIMIT });
  const facets = whole.state === "ok" ? whole.data.facets.mnemonics : {};
  const chips = Object.keys(facets).sort((a, b) => facets[b] - facets[a] || (a < b ? -1 : 1));
  const shownSplit = splitLookup(text, chips);
  const chip = shownSplit.chip ?? picked;
  const listed = openList && text.trim().length >= SUGGEST_MIN;
  const askedSplit = splitLookup(asked, chips);
  const askedChip = askedSplit.chip ?? picked;
  const lookup = useNamespaceList(clusterId, { ...(askedSplit.q ? { q: askedSplit.q } : {}), ...(askedChip ? { mnemonic: askedChip } : {}), limit: LOOKUP_LIMIT },
    listed && asked === text);
  // Only the answer of the text as it is now is shown (design T1): an answer for older text is never listed.
  const settled = asked === text && lookup.state === "ok";
  const items = settled && lookup.state === "ok" ? lookup.data.items : [];
  const idx = Math.min(active, items.length - 1);

  const choose = (name: string) => {
    setText(name);
    setOpenList(false);
    setActive(-1);
    rememberRecent(clusterId, name);
    setRecent(readRecent());
    onOpen(name);
  };
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "ArrowDown" && items.length) { e.preventDefault(); setOpenList(true); setActive(Math.min(items.length - 1, idx + 1)); }
    else if (e.key === "ArrowUp" && items.length) { e.preventDefault(); setActive(Math.max(0, idx - 1)); }
    else if (e.key === "Enter" && idx >= 0 && items.length) { e.preventDefault(); choose(items[idx].name); }
    else if (e.key === "Escape") { setOpenList(false); setActive(-1); }
  };
  const mine = recent[clusterId] ?? [];
  const total = whole.state === "ok" ? whole.data.total : null;
  const title = chipTitle ?? "";

  return (
    <Grid hasGutter>
      <GridItem md={4}>
        <FormGroup label="Cluster" fieldId="nsx-cluster">
          <FormSelect id="nsx-cluster" value={clusterId} aria-describedby="nsx-cluster-help" onChange={(_, v) => onCluster(v)}>
            <FormSelectOption value="" label="Choose a cluster…" />
            {clusters.map((c) => <FormSelectOption key={c.clusterId} value={c.clusterId} label={`${c.clusterId} (${c.environment})`} />)}
          </FormSelect>
          <Hint id="nsx-cluster-help">Every cluster cmapi manages.</Hint>
        </FormGroup>
      </GridItem>
      <GridItem md={8}>
        {chipTitle && (
          <FormGroup label={title} role="group" fieldId="nsx-chips">
            {clusterId && chips.length > 0
              ? <Choices label={title} options={[{ label: "All", n: total ?? "", on: chip === null, pick: () => setPicked(null) },
                ...chips.map((m) => ({ label: m, n: facets[m], on: chip === m, pick: () => setPicked(m) }))]} />
              : <Hint>{clusterId ? whole.state === "ok" ? "None on this cluster." : "Loading…" : "Choose a cluster first."}</Hint>}
          </FormGroup>
        )}
        <FormGroup label="Namespace" fieldId="nsx-ns">
          <div className="cp-combo">
            <TextInputGroup isDisabled={!clusterId}>
              <TextInputGroupMain
                inputId="nsx-ns"
                role="combobox"
                // TextInputGroupMain names its input "Type to filter" unless told: the field's own label names it here.
                aria-label="Namespace"
                aria-controls="nsx-list"
                isExpanded={listed}
                placeholder="Type 2+ letters"
                value={text}
                onChange={(_, v) => { setText(v); setOpenList(true); setActive(-1); }}
                inputProps={{ autoComplete: "off", "aria-autocomplete": "list", "aria-describedby": "nsx-ns-help",
                  "aria-activedescendant": idx >= 0 ? `nsx-opt-${idx}` : undefined, onKeyDown: onKey }}
              />
            </TextInputGroup>
            {listed && (
              <div className="cp-combo-menu">
                <Menu role="listbox">
                  <MenuContent>
                    <MenuList id="nsx-list" aria-label="Matching namespaces">
                      {items.map((n, k) => (
                        <MenuItem key={n.name} id={`nsx-opt-${k}`} itemId={n.name} isFocused={k === idx} isSelected={k === idx}
                          description={`team ${n.team ?? "—"} · ${stateWords(n)}`} onClick={() => choose(n.name)}>{n.name}</MenuItem>
                      ))}
                      {settled && items.length === 0 && <MenuItem isDisabled>{`No namespace matches${chip ? ` in ${chip}` : ""}.`}</MenuItem>}
                      {!settled && lookup.state !== "error" && lookup.state !== "forbidden" && <MenuItem isDisabled>Searching…</MenuItem>}
                      {(lookup.state === "error" || lookup.state === "forbidden") && <MenuItem isDisabled>The matches did not load.</MenuItem>}
                    </MenuList>
                  </MenuContent>
                  {settled && lookup.state === "ok" && (
                    <MenuFooter><Small>{`${items.length} of ${lookup.data.total} in ${clusterId}${chip ? ` · ${title} ${chip}` : ""} · ↑↓ Enter`}</Small></MenuFooter>
                  )}
                </Menu>
              </div>
            )}
          </div>
          <Hint id="nsx-ns-help">{!clusterId ? "Choose a cluster first."
            : total === null ? "Loading the cluster's namespaces…"
              : `${total} managed namespaces in ${clusterId}. Type 2+ letters${chipTitle ? `, or start with a ${title.toLowerCase()}` : ""}.`}</Hint>
        </FormGroup>
        {clusterId && mine.length > 0 && (
          <Flex gap={{ default: "gapSm" }} alignItems={{ default: "alignItemsCenter" }}>
            <Small>{`Recent in ${clusterId}:`}</Small>
            {mine.map((name) => <Button key={name} variant="link" isInline onClick={() => choose(name)}>{name}</Button>)}
          </Flex>
        )}
      </GridItem>
    </Grid>
  );
}
