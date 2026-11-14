// The view in the address: "#requests?q=pay&state=open". A person can share it, and a reload keeps it.
import { useCallback, useEffect, useState } from "react";
import type { PortalConfig } from "./config";

/** The mockup's tabs, in its order. */
export const TAB_IDS = ["workflow", "new", "quotas", "expiration", "requests", "approvals", "policies", "capacity", "kpis"] as const;
export type TabId = (typeof TAB_IDS)[number];

export interface Route {
  /** The tab of the address, if it names one. */
  tab: TabId | null;
  params: URLSearchParams;
}

export interface TabProps {
  config: PortalConfig;
  params: URLSearchParams;
  /** Writes the tab's own parameters. An empty value removes the parameter. */
  setParams: (values: Record<string, string>) => void;
}

function read(): Route {
  const [name, query = ""] = location.hash.slice(1).split("?");
  return { tab: (TAB_IDS as readonly string[]).includes(name) ? (name as TabId) : null, params: new URLSearchParams(query) };
}

export function useRoute(): { route: Route; go: (tab: TabId, values?: Record<string, string>) => void } {
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const onHash = () => setRoute(read());
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, []);
  const go = useCallback((tab: TabId, values: Record<string, string> = {}) => {
    const params = new URLSearchParams(Object.entries(values).filter(([, value]) => value));
    const query = params.toString();
    // replaceState: a filter change is not a page of the history.
    history.replaceState(null, "", `#${tab}${query ? `?${query}` : ""}`);
    setRoute({ tab, params });
  }, []);
  return { route, go };
}
