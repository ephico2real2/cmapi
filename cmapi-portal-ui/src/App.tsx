import { Badge, Content, Flex, FlexItem, Masthead, MastheadBrand, MastheadContent, MastheadMain, Page, PageSection, Tab, Tabs, TabTitleText, Title, Stack } from "@patternfly/react-core";
import { Choices, Small } from "./components/ui";
import { usePortal } from "./model/usePortal";
import { Approvals } from "./tabs/Approvals";
import { Capacity } from "./tabs/Capacity";
import { Expiration } from "./tabs/Expiration";
import { Kpis } from "./tabs/Kpis";
import { NewNamespace } from "./tabs/NewNamespace";
import { Policies } from "./tabs/Policies";
import { Quotas } from "./tabs/Quotas";
import { Requests } from "./tabs/Requests";
import { Workflow } from "./tabs/Workflow";

const PANELS = [Workflow, NewNamespace, Quotas, Expiration, Requests, Approvals, Policies, Capacity, Kpis];

export function App() {
  const { v, session } = usePortal();
  const active = v.tabs.findIndex((t) => t.current === "page");

  const masthead = (
    <Masthead>
      <MastheadMain>
        <MastheadBrand>
          <Title headingLevel="h2" size="lg">cmapi <Small>Cluster Management Portal</Small></Title>
        </MastheadBrand>
      </MastheadMain>
      <MastheadContent>
        <Flex alignItems={{ default: "alignItemsCenter" }} justifyContent={{ default: "justifyContentSpaceBetween" }} style={{ width: "100%" }}>
          <FlexItem><Small>{v.inst.label} · {v.inst.envs}</Small></FlexItem>
          <Flex alignItems={{ default: "alignItemsCenter" }}>
            <a href={`${v.inst.api}/docs`}>Swagger</a>
            <a href={`${v.inst.api}/redoc`}>ReDoc</a>
            <Stack><b>ola</b><Small>cmapi-requester · cmapi-approver (Keycloak roles)</Small></Stack>
          </Flex>
        </Flex>
      </MastheadContent>
    </Masthead>
  );

  return (
    <Page masthead={masthead}>
      <PageSection variant="secondary" padding={{ default: "padding" }}>
        <Flex alignItems={{ default: "alignItemsCenter" }} justifyContent={{ default: "justifyContentSpaceBetween" }}>
          <FlexItem><Small>Mockup only: each instance is a separate deployment at its own URL. Switch to see what each one serves.</Small></FlexItem>
          <FlexItem style={{ minWidth: 0 }}><Choices label="Instance" options={v.instOpts} /></FlexItem>
        </Flex>
      </PageSection>
      <PageSection>
        <Tabs key={session} activeKey={active} onSelect={(_, key) => v.tabs[Number(key)].pick()} aria-label="Portal sections" mountOnEnter unmountOnExit>
          {v.tabs.map((t, i) => {
            const Panel = PANELS[i];
            return (
              <Tab
                key={i}
                eventKey={i}
                title={<TabTitleText>{t.label}{t.hasCount && <> <Badge isRead>{t.count}</Badge></>}</TabTitleText>}
              >
                <div style={{ paddingBlockStart: "var(--pf-t--global--spacer--md)" }}><Panel v={v} /></div>
              </Tab>
            );
          })}
        </Tabs>
        <Content component="small">
          Mockup with example data: cluster IDs, users, commits, scores and timings are illustrative. Times are UTC. This is the {v.inst.display} instance: API {v.inst.api}, portal {v.inst.portal}.
        </Content>
      </PageSection>
    </Page>
  );
}
