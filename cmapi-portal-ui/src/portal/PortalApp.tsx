// The portal on the API: config.json, sign-in through the issuer, then the mockup's page frame and tabs.
import {
  Alert, AlertActionLink, Bullseye, Button, Content, EmptyState, EmptyStateActions, EmptyStateBody, EmptyStateFooter, Flex, FlexItem, Masthead,
  MastheadBrand, MastheadContent, MastheadMain, Page, PageSection, Stack, Tab, Tabs, TabTitleText, Title
} from "@patternfly/react-core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ComponentType, ReactNode } from "react";
import { AuthProvider, hasAuthParams, useAuth } from "react-oidc-context";
import { createApi } from "../api/client";
import type { Session } from "../api/client";
import { ApiProvider, useMe } from "../api/hooks";
import { PERMISSION } from "../api/permissions.generated";
import { Small } from "../components/ui";
import { oidcSettings } from "./auth";
import type { ReturnState } from "./auth";
import { ConfigError, loadConfig } from "./config";
import type { PortalConfig } from "./config";
import { RequestsTab } from "./RequestsTab";
import { useRoute } from "./route";
import type { TabId, TabProps } from "./route";

interface TabDef {
  id: TabId;
  label: string;
  /** The permission of the tab's first call. A tab whose calls are not built has none yet. */
  needs: string | null;
  panel?: ComponentType<TabProps>;
}

const NO_PARAMS = new URLSearchParams();

// The mockup's tabs and their order. A tab shows only when GET /api/v1/me says that the person holds its permission.
const TABS: TabDef[] = [
  { id: "workflow", label: "Workflow", needs: PERMISSION["GET /api/v1/requests/{request_id}/events"] },
  { id: "new", label: "New namespace", needs: PERMISSION["POST /api/v1/clusters/{cluster_id}/namespaces"] },
  { id: "quotas", label: "Quotas", needs: PERMISSION["GET /api/v1/quotas"] },
  { id: "expiration", label: "Expiration", needs: null },
  { id: "requests", label: "Requests", needs: PERMISSION["GET /api/v1/requests"], panel: RequestsTab },
  { id: "approvals", label: "Approvals", needs: PERMISSION["POST /api/v1/requests/{request_id}:approve"] },
  { id: "policies", label: "Policies", needs: null },
  { id: "capacity", label: "Capacity", needs: null },
  { id: "kpis", label: "KPIs", needs: PERMISSION["GET /api/v1/admin/kpi"] }
];

const Waiting = ({ children }: { children: string }) => <Bullseye><span role="status">{children}</span></Bullseye>;

function Blocked({ title, body, action }: { title: string; body: string; action?: ReactNode }) {
  return (
    <Bullseye>
      <EmptyState titleText={title} headingLevel="h1" status="danger">
        <EmptyStateBody>{body}</EmptyStateBody>
        {action && <EmptyStateFooter><EmptyStateActions>{action}</EmptyStateActions></EmptyStateFooter>}
      </EmptyState>
    </Bullseye>
  );
}

export function PortalApp() {
  const [boot, setBoot] = useState<{ config?: PortalConfig; error?: string }>({});
  useEffect(() => {
    const control = new AbortController();
    loadConfig(control.signal).then(
      (config) => setBoot({ config }),
      (error: unknown) => {
        if (!control.signal.aborted) setBoot({ error: error instanceof ConfigError ? error.message : "config.json did not load." });
      }
    );
    return () => control.abort();
  }, []);
  // With no issuer and no API there is nothing to show: this build holds no sample data.
  if (boot.error) return <Blocked title="The portal is not configured." body={boot.error} />;
  if (!boot.config) return <Waiting>Loading the portal…</Waiting>;
  return <Configured config={boot.config} />;
}

function Configured({ config }: { config: PortalConfig }) {
  const settings = useMemo(() => oidcSettings(config), [config]);
  return <AuthProvider {...settings}><SignIn config={config} /></AuthProvider>;
}

/** Sends a person with no session to the issuer, and shows the portal only to a signed-in person. */
function SignIn({ config }: { config: PortalConfig }) {
  const auth = useAuth();
  const asked = useRef(false);
  const [sessionEnded, setSessionEnded] = useState(false);
  const [callbackError] = useState(() => {
    const params = new URLSearchParams(location.search);
    return (params.has("error") || params.has("code")) && !params.get("state")
      ? "The sign-in response has no state. Sign in again to continue." : undefined;
  });
  const signIn = () => auth.signinRedirect({ state: { hash: location.hash } satisfies ReturnState });
  useEffect(() => {
    if (hasAuthParams() || auth.isAuthenticated || auth.activeNavigator || auth.isLoading || auth.error || callbackError || sessionEnded || asked.current) return;
    asked.current = true;
    void signIn();
  });
  useEffect(() => {
    if ((auth.error && hasAuthParams()) || callbackError) history.replaceState(null, "", location.pathname);
  }, [auth.error, callbackError]);
  // A session failure requires a user gesture. Redirecting automatically here can loop across page loads.
  if (sessionEnded || auth.error || callbackError) return <Blocked title="Sign-in did not complete." body={auth.error?.message ?? callbackError ?? "The API refused this session. Sign in again to continue."} action={<Button onClick={() => void signIn()}>Sign in again</Button>} />;
  if (auth.isAuthenticated) return <SignedIn config={config} onSessionEnded={() => setSessionEnded(true)} />;
  return <Waiting>Signing in…</Waiting>;
}

function SignedIn({ config, onSessionEnded }: { config: PortalConfig; onSessionEnded: () => void }) {
  const auth = useAuth();
  const [signingOut, setSigningOut] = useState(false);
  const latest = useRef(auth);
  latest.current = auth;
  const [queries] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false, staleTime: 15_000 } } }));
  const sessionEnded = useRef(onSessionEnded);
  sessionEnded.current = onSessionEnded;
  useEffect(() => () => queries.clear(), [queries]);
  const api = useMemo(() => {
    const session: Session = {
      token: () => {
        const user = latest.current.user;
        return user && !user.expired ? user.access_token : undefined;
      },
      renew: async () => (await latest.current.signinSilent())?.access_token,
      signIn: async () => { sessionEnded.current(); }
    };
    return createApi(config.apiUrl, session);
  }, [config.apiUrl]);
  const signOut = () => {
    // Nothing that the API sent stays in memory for the next person on this browser.
    setSigningOut(true);
    queries.clear();
    void auth.signoutRedirect();
  };
  if (signingOut) return <Waiting>Signing out…</Waiting>;
  return (
    <QueryClientProvider client={queries}>
      <ApiProvider value={api}><Portal config={config} onSignOut={signOut} /></ApiProvider>
    </QueryClientProvider>
  );
}

function Portal({ config, onSignOut }: { config: PortalConfig; onSignOut: () => void }) {
  const me = useMe();
  const { route, go } = useRoute();
  const held = me.state === "ok" ? new Set(me.data.access.permissions) : null;
  const tabs = held ? TABS.filter((tab) => tab.needs === null || held.has(tab.needs)) : [];
  const active = tabs.find((tab) => tab.id === route.tab) ?? tabs[0];

  const masthead = (
    <Masthead>
      <MastheadMain>
        <MastheadBrand>
          <Title headingLevel="h2" size="lg">cmapi <Small>Cluster Management Portal</Small></Title>
        </MastheadBrand>
      </MastheadMain>
      <MastheadContent>
        <Flex alignItems={{ default: "alignItemsCenter" }} justifyContent={{ default: "justifyContentSpaceBetween" }} style={{ width: "100%" }}>
          <FlexItem><Small>{config.instance} · {config.environments.join(", ")}</Small></FlexItem>
          <Flex alignItems={{ default: "alignItemsCenter" }}>
            <a href={`${config.apiUrl}/docs`}>Swagger</a>
            <a href={`${config.apiUrl}/redoc`}>ReDoc</a>
            {me.state === "ok" && <Stack><b>{me.data.username}</b><Small>{me.data.roles.join(" · ")} (Keycloak roles)</Small></Stack>}
            <Button variant="link" isInline onClick={onSignOut}>Sign out</Button>
          </Flex>
        </Flex>
      </MastheadContent>
    </Masthead>
  );

  return (
    <Page masthead={masthead}>
      <PageSection>
        {me.state === "loading" && <span role="status">Loading your access…</span>}
        {(me.state === "error" || me.state === "forbidden") && (
          <Alert variant="danger" isInline title="Your access did not load." actionLinks={<AlertActionLink onClick={me.reload}>Try again</AlertActionLink>}>
            {me.state === "error" ? me.cause : me.detail}
          </Alert>
        )}
        {active && (
          <Tabs activeKey={active.id} onSelect={(_, key) => go(key as TabId)} aria-label="Portal sections" mountOnEnter unmountOnExit>
            {tabs.map(({ id, label, panel: Panel }) => (
              <Tab key={id} eventKey={id} title={<TabTitleText>{label}</TabTitleText>}>
                <div style={{ paddingBlockStart: "var(--pf-t--global--spacer--md)" }}>
                  {Panel
                    ? <Panel config={config} params={id === route.tab ? route.params : NO_PARAMS} setParams={(values) => go(id, values)} />
                    : <EmptyState titleText="This tab is not on the API yet." headingLevel="h1"><EmptyStateBody>It shows data when its API calls are built.</EmptyStateBody></EmptyState>}
                </div>
              </Tab>
            ))}
          </Tabs>
        )}
        <Content component="small">
          Times are UTC. This is the {config.displayName} instance: API {config.apiUrl}, portal {location.origin}.
        </Content>
      </PageSection>
    </Page>
  );
}
