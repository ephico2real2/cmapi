import { ActionGroup, Button, Flex, FlexItem, Form, FormGroup, Grid, GridItem, Menu, MenuContent, MenuItem, MenuList, Stack, TextArea, TextInput, TextInputGroup, TextInputGroupMain } from "@patternfly/react-core";
import { Callout, Checks, Choices, Code, DataTable, Empty, Filter, Head, Hint, KV, Meter, Pager, Panel, Pill, RowButton, Small } from "../components/ui";
import type { TabProps } from "../model/types";

function Search({ v }: TabProps) {
  const s = v.qSug;
  return (
    <div className="cp-combo">
      <TextInputGroup>
        <TextInputGroupMain
          inputId="q-search"
          type="search"
          role="combobox"
          aria-label="Find a namespace, team or app"
          aria-controls="q-sug"
          isExpanded={s.expanded === "true"}
          placeholder="Find a namespace, team or app (type 2+ characters)"
          value={s.text}
          onChange={(e) => s.onType(e)}
          inputProps={{ autoComplete: "off", "aria-autocomplete": "list", "aria-activedescendant": s.active || undefined, onKeyDown: s.onKey }}
        />
      </TextInputGroup>
      {s.open && (
        <div className="cp-combo-menu">
          <Menu id="q-sug" role="listbox" aria-label="Matching namespaces">
            <MenuContent>
              <MenuList>
                {s.items.map((x: any) => (
                  <MenuItem key={x.id} id={x.id} itemId={x.id} isFocused={x.sel === "true"} description={<>{x.where} {x.why}</>} onClick={x.pick}>{x.ns}</MenuItem>
                ))}
                {s.none && <MenuItem isDisabled>No namespace matches "{s.text}".</MenuItem>}
              </MenuList>
            </MenuContent>
          </Menu>
        </div>
      )}
    </div>
  );
}

export function Quotas({ v }: TabProps) {
  const { qd, qc, qPage, qExp, qSug } = v;
  return (
    <Stack hasGutter>
      <Head
        title="Quotas"
        lede={<>The ResourceQuota of every namespace in the environments your roles cover on the {v.inst.label} instance, read live from cmapi's watch cache of each cluster. Used is what pods have requested, not what they consume; real usage is read from Thanos only when you plan a change.</>}
        pill={<Pill>{v.qHead}</Pill>}
      />
      <Panel>
        <Filter label="Needs attention" options={v.qAttn} />
        <form role="search" onSubmit={qSug.go}>
          <Flex alignItems={{ default: "alignItemsCenter" }} gap={{ default: "gapSm" }}>
            <Search v={v} />
            <Button variant="secondary" type="submit">Show all matches</Button>
            {qSug.applied && <Button variant="tertiary" onClick={qSug.clear}>matching "{qSug.appliedText}" ✕</Button>}
            <Button variant="secondary" onClick={qExp.go}>Export CSV</Button>
          </Flex>
        </form>
        <Flex gap={{ default: "gapMd" }}>
          <Filter label="Env" options={v.qEnvOpts} />
          <Filter label="Cluster" options={v.qClusterOpts} />
          <Filter label="Tier" options={v.qTierOpts} />
          <Filter label="Sort" options={v.qSortOpts} />
          <Filter label="Per page" options={v.qSizeOpts} />
        </Flex>
        <Flex role="group" aria-label="Jump to the first namespace starting with a letter" gap={{ default: "gapXs" }}>
          {v.qAz.map((l: any) => (
            <Button
              key={l.t}
              variant={/\bon\b/.test(l.cls) ? "primary" : "tertiary"}
              size="sm"
              isAriaDisabled={String(l.dis) === "true"}
              aria-label={l.aria}
              onClick={l.pick}
            >
              {l.t}
            </Button>
          ))}
        </Flex>
        {qExp.show && (
          <>
            <Callout tone="info" title={qExp.title}>{qExp.text}</Callout>
            <Code text={qExp.preview} />
            <div><RowButton onClick={qExp.close}>Close</RowButton></div>
          </>
        )}
      </Panel>

      <Panel>
        <Pager range={qPage.range} prev={qPage.prev} next={qPage.next} prevDis={qPage.prevDis} nextDis={qPage.nextDis} />
        <DataTable
          label="Quotas"
          cols={["Namespace", "Cluster", "Env", "Tier", "CPU requests", "Memory requests", "Pods", "Verdict", ""]}
          rows={v.quotas as any[]}
          selected={(q) => /\b(on|sel|selected)\b/.test(q.cls)}
          cells={(q) => [
            q.ns, q.cluster, q.env, q.tier,
            <Meter ariaLabel="CPU requests of quota" value={q.cpuNow} pct={q.cpuPct} bar={q.cpuBar} label={q.cpuText} />,
            <Meter ariaLabel="Memory requests of quota" value={q.memNow} pct={q.memPct} bar={q.memBar} label={q.memText} />,
            q.pods, <Pill tone={q.vTone}>{q.verdict}</Pill>, <RowButton onClick={q.pick}>{q.btn}</RowButton>
          ]}
        />
        {v.noQuotas && <Empty>{`No namespace on the ${v.inst.label} instance matches these filters.`}</Empty>}
        {qPage.stale && (
          <Callout tone="warn" title="This page link is out of date">
            <Stack hasGutter>
              <span>The filters or sort changed after it was made, so the API refused it (400 invalid-cursor) rather than show the wrong rows.</span>
              <div><RowButton onClick={qPage.first}>Back to the first page</RowButton></div>
            </Stack>
          </Callout>
        )}
        <Pager range={qPage.call} prev={qPage.prev} next={qPage.next} prevDis={qPage.prevDis} nextDis={qPage.nextDis} />
        <Small>Quota status from the watch cache, verdicts from the 02:00 usage sweep; no Thanos call. Pages follow a cursor on the sort key, so namespaces created or deleted between pages never cause a skip or a repeat. Bars turn amber at 80% and red at 95% of the hard limit.</Small>
      </Panel>

      {v.qHasDetail && (
        <Grid hasGutter>
          <GridItem md={12} lg={6}>
            <Panel title={qd.title} pill={<Pill tone={qd.vTone}>{qd.verdict}</Pill>}>
              <Small>{qd.meta}</Small>
              <DataTable
                label="ResourceQuota"
                cols={["ResourceQuota", "Used", "Hard", ""]}
                blank="Used of hard"
                rows={qd.rows as any[]}
                cells={(r) => [r.k, r.used, r.hard, <Meter ariaLabel={`${r.k} used of hard`} value={r.now} pct={r.pct} bar={r.bar} label={r.pctText} />]}
              />
              <b>Usage verdict</b>
              <Small>{qd.vNote}</Small>
              {qd.hasRec && (
                <Callout tone="info" title={<>Recommendation {qd.recId}</>}>
                  <Stack hasGutter>
                    <span>{qd.recText}</span>
                    <div><RowButton onClick={qd.useRec}>Use this size</RowButton></div>
                  </Stack>
                </Callout>
              )}
              <Small>GET /api/v1/clusters/{qd.cluster}/namespaces/{qd.ns}/quota · ETag {qd.etag} · ResourceQuota and LimitRange for tier {qd.tier} live in the namespace folder in Git.</Small>
            </Panel>
          </GridItem>
          <GridItem md={12} lg={6}>
            <Panel title={<>Change quota · {qd.ns}</>} pill={<Pill>{qd.env} · {qd.cluster}</Pill>}>
              <Form onSubmit={v.qSubmit}>
                {qc.locked && (
                  <Callout tone="warn" title={qc.lockTitle}>
                    <Stack hasGutter>
                      <span>{qc.lockText}</span>
                      <div><RowButton onClick={qc.openLock}>Open at current step</RowButton></div>
                    </Stack>
                  </Callout>
                )}
                {qc.open && (
                  <>
                    <FormGroup label="New size" role="group" fieldId="q-size">
                      <Choices label="New size" options={qc.sizes} />
                      <Hint>{"A tier changes one label and the operator re-stamps the quota (PATCH …/namespaces/{ns}). Custom sets requests.cpu and requests.memory directly (PATCH …/namespaces/{ns}/quota)."}</Hint>
                    </FormGroup>
                    {qc.custom && (
                      <Grid hasGutter>
                        <GridItem md={6}>
                          <FormGroup label="requests.cpu (cores)" fieldId="q-cpu">
                            <TextInput id="q-cpu" type="number" min="1" step="1" inputMode="numeric" value={qc.cpu} onChange={(e) => qc.onCpu(e)} />
                          </FormGroup>
                        </GridItem>
                        <GridItem md={6}>
                          <FormGroup label="requests.memory (Gi)" fieldId="q-mem">
                            <TextInput id="q-mem" type="number" min="1" step="1" value={qc.mem} onChange={(e) => qc.onMem(e)} />
                          </FormGroup>
                        </GridItem>
                      </Grid>
                    )}
                    <FormGroup label="Justification" fieldId="q-why">
                      <TextArea id="q-why" placeholder="Why this size is needed, for example the load test or launch it supports" />
                    </FormGroup>
                    <ActionGroup>
                      <Button variant="secondary" type="button" onClick={v.qPlan}>Plan change</Button>
                      <Button variant="primary" type="submit">Submit change</Button>
                    </ActionGroup>
                    {qc.nothing && <Empty>The new size equals the current quota; pick another tier or custom values.</Empty>}
                    {qc.planned && (
                      <Stack hasGutter>
                        <b>Live usage · last 14 days</b>
                        <DataTable
                          label="Live usage"
                          cols={["Resource", "Now", "7d avg", "p95", "Peak", "Quota", "New / peak"]}
                          rows={qc.usage as any[]}
                          cells={(u) => [u.k, u.now, u.avg, u.p95, u.peak, u.quota, u.ratio]}
                        />
                        <Small>Read live from {qd.cluster}'s Thanos by cmapi-capacity for this plan; cached 10 minutes and not stored. Cluster headroom comes from the 17:00 snapshot, committed quota and reservations, with no Thanos call.</Small>
                        <Checks items={qc.checks.map((c: any) => ({ s: c.s, mark: c.mark, main: c.l, note: c.n }))} />
                        <Callout tone={qc.apprTone} title={qc.apprTitle}>{qc.apprDetail}</Callout>
                      </Stack>
                    )}
                    {qc.sent && (
                      <>
                        <Callout tone={qc.sentTone} title={qc.sentTitle}>{qc.sentText}</Callout>
                        <Code text={qc.sentBody} />
                      </>
                    )}
                  </>
                )}
              </Form>
            </Panel>
          </GridItem>
        </Grid>
      )}
    </Stack>
  );
}
