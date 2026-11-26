// One typed hook for each endpoint that the portal reads. Server data lives in TanStack Query, not in component state.
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useRef } from "react";
import type { Api } from "./client";
import { fieldsOf, RulesUnreadable } from "../portal/metadataForm";
import type { MetaForm } from "../portal/metadataForm";
import { ApiProblem, problemOf } from "./problem";
import type { ProblemItem } from "./problem";
import type { components, operations } from "./schema.generated";

export type Me = components["schemas"]["Me"];
export type RequestPage = components["schemas"]["RequestPage"];
export type ChangeRequest = components["schemas"]["ChangeRequest"];
export type RequestsQuery = NonNullable<operations["requests_list_requests"]["parameters"]["query"]>;
export type TierCatalog = components["schemas"]["TierCatalogView"];
export type ClusterList = components["schemas"]["ClusterList"];
export type Cluster = components["schemas"]["ClusterView"];
export type Plan = components["schemas"]["PlanView"];
export type NamespaceCreate = components["schemas"]["NamespaceCreate"];
/**
 * A create as the New namespace form builds it. Its labels and annotations are the instance's keys, read from
 * GET /api/v1/metadata-keys (#336); the committed contract types the reference file's keys (cmapi.net/team required), so a
 * body of another instance's keys is not a NamespaceCreate to the compiler. contractBody is the one place that says so.
 */
export type CreateBody = Omit<NamespaceCreate, "labels" | "annotations"> & { labels: Record<string, string>; annotations: Record<string, string> };
const contractBody = (body: CreateBody): NamespaceCreate => body as NamespaceCreate;
export type RequestEvents = components["schemas"]["RequestEvents"];
export type RequestEvent = components["schemas"]["RequestEvent"];
export type QuotaPage = components["schemas"]["QuotaPage"];
export type QuotaRow = components["schemas"]["QuotaRow"];
export type QuotasQuery = NonNullable<operations["quotas_quotas"]["parameters"]["query"]>;
export type ExportQuery = NonNullable<operations["quotas_export"]["parameters"]["query"]>;
export type Suggestion = components["schemas"]["Suggestion"];
export type NamespaceView = components["schemas"]["NamespaceView"];
export type NamespaceList = components["schemas"]["NamespaceList"];
export type NamespaceListQuery = NonNullable<operations["namespaces_list_namespaces"]["parameters"]["query"]>;
export type NamespacePatch = components["schemas"]["NamespacePatch"];
export type KpiView = components["schemas"]["KpiView"];
export type ExpirationPage = components["schemas"]["ExpirationPage"];
export type ExpirationRow = components["schemas"]["ExpirationRow"];
export type ExpirationsQuery = NonNullable<operations["expiration_expirations"]["parameters"]["query"]>;
export type PolicyResultPage = components["schemas"]["PolicyResultPage"];
export type PolicyCluster = components["schemas"]["PolicyCluster"];
export type PolicySummary = components["schemas"]["PolicySummary"];
export type PolicyResultRow = components["schemas"]["PolicyResultRow"];
export type PolicyResultsQuery = NonNullable<operations["policies_results"]["parameters"]["query"]>;
export type RejectionPage = components["schemas"]["RejectionPage"];
export type Rejection = components["schemas"]["Rejection"];
export type RejectionsQuery = NonNullable<operations["policies_rejections"]["parameters"]["query"]>;
export type CapacityPage = components["schemas"]["CapacityPage"];
export type CapacityCluster = components["schemas"]["CapacityCluster"];
export type CapacityGroup = components["schemas"]["CapacityGroup"];
export type CapacityResource = components["schemas"]["CapacityResource"];
export type PlacementRequest = components["schemas"]["PlacementRequest"];
export type PlacementResult = components["schemas"]["PlacementResult"];
export type PlacementRanked = components["schemas"]["PlacementRanked"];
export type PlacementExcluded = components["schemas"]["PlacementExcluded"];

/** What a section shows for one read. A 401 is not here: the client signs in again and the section never sees it. */
export type Result<T> =
  | { state: "loading" }
  | { state: "error"; cause: string; code: string }
  | { state: "forbidden"; detail: string }
  | { state: "ok"; data: T; refreshing: boolean };

/**
 * What a section shows for one write, or for a dry run: not sent, sent, refused by the API with its problem, no answer
 * from the network, or done. A refusal (a 4xx) is the API's decision and is shown with its code; it is not retried.
 */
export type Outcome<T> =
  | { state: "idle" }
  | { state: "sending" }
  | { state: "refused"; status: number; code: string; detail: string; errors: ProblemItem[] }
  | { state: "error"; cause: string; code: string }
  | { state: "ok"; data: T };

const ApiContext = createContext<Api | null>(null);
export const ApiProvider = ApiContext.Provider;

function useApi(): Api {
  const api = useContext(ApiContext);
  if (!api) throw new Error("No API client: the component is outside ApiProvider.");
  return api;
}

function resultOf<T>(query: { data: T | undefined; error: unknown; isPlaceholderData: boolean }): Result<T> {
  const { error } = query;
  if (error instanceof ApiProblem) {
    return error.status === 403 ? { state: "forbidden", detail: error.detail } : { state: "error", cause: error.detail, code: error.code };
  }
  if (error) return { state: "error", cause: "The network did not answer.", code: "network" };
  if (query.data === undefined) return { state: "loading" };
  // A paused fetch also retains the old page and its cursors until the new answer arrives.
  return { state: "ok", data: query.data, refreshing: query.isPlaceholderData };
}

function outcomeOf<T>(run: { isPending: boolean; isIdle: boolean; error: unknown; data: T | undefined }): Outcome<T> {
  const { error } = run;
  if (error instanceof ApiProblem) {
    // A 5xx says that the API could not answer, not that it refused: the person may send the same call again.
    return error.status >= 500 ? { state: "error", cause: error.detail, code: error.code } : { state: "refused", status: error.status, code: error.code, detail: error.detail, errors: error.errors };
  }
  if (error) return { state: "error", cause: "The network did not answer.", code: "network" };
  if (run.data !== undefined) return { state: "ok", data: run.data };
  return run.isIdle ? { state: "idle" } : run.isPending ? { state: "sending" } : { state: "idle" };
}

/** The states in which a request is not finished: the list contract's `state=open` (GET /api/v1/requests). */
export const OPEN_STATES: ReadonlySet<ChangeRequest["status"]> = new Set([
  "pending_approval", "approved", "pr_open", "applied", "merge_failed", "merged", "awaiting_prune", "sync_failed"
]);
/** How often an open request is read again, so that the Workflow tab follows it to its end. */
const FOLLOW_MS = 5000;

/**
 * One write at a time: a second call while the first is in flight gets the first one's promise and sends nothing. The
 * hook's "sending" state reaches React only a task after the call (TanStack Query notifies on a timer), so a double click
 * would otherwise send two writes before any button is disabled.
 */
function useOneAtATime<A, T>(run: (args: A) => Promise<T>): (args: A) => Promise<T> {
  const inFlight = useRef<Promise<T> | null>(null);
  return (args) => inFlight.current ?? (inFlight.current = run(args).finally(() => { inFlight.current = null; }));
}

/** GET /api/v1/me: who the caller is and what the roles permit. The portal takes each permission from here. */
export function useMe(): Result<Me> & { reload: () => void } {
  const api = useApi();
  const query = useQuery({
    queryKey: ["me"],
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/api/v1/me", { signal });
      if (!data) throw problemOf(response, error);
      return data;
    }
  });
  return { ...resultOf(query), reload: () => void query.refetch() };
}

/** GET /api/v1/requests: one query for each page, with its filters and its cursor as the key. */
export function useRequests(params: RequestsQuery): Result<RequestPage> & { reload: () => void } {
  const api = useApi();
  const query = useQuery({
    queryKey: ["requests", params],
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/api/v1/requests", { params: { query: params }, signal });
      if (!data) throw problemOf(response, error);
      return data;
    },
    // The rows of the last page stay while the next page loads.
    placeholderData: keepPreviousData
  });
  return { ...resultOf(query), reload: () => void query.refetch() };
}

/** GET /api/v1/tiers for one environment: the tiers that the New namespace tab offers. */
export function useTiers(environment: string): Result<TierCatalog> & { reload: () => void } {
  const api = useApi();
  const query = useQuery({
    queryKey: ["tiers", environment],
    enabled: environment !== "",
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/api/v1/tiers", { params: { query: { environment } }, signal });
      if (!data) throw problemOf(response, error);
      return data;
    }
  });
  return { ...resultOf(query), reload: () => void query.refetch() };
}

/** GET /api/v1/clusters: the clusters of this instance, with their environment and whether they take writes. */
export function useClusters(): Result<ClusterList> & { reload: () => void } {
  const api = useApi();
  const query = useQuery({
    queryKey: ["clusters"],
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/api/v1/clusters", { signal });
      if (!data) throw problemOf(response, error);
      return data;
    }
  });
  return { ...resultOf(query), reload: () => void query.refetch() };
}

/** The rules of the New namespace form's labels and annotations, as the form reads them, and the answer they came from. */
export interface MetadataRules {
  form: MetaForm;
  /** The answer as text: two answers with the same text are the same rules. */
  fingerprint: string;
}

/**
 * GET /api/v1/metadata-keys (#336): this instance's metadata-keys.yaml as the schema of a new namespace's labels and
 * annotations. The API sends a strong ETag with `private, no-cache`, so each read is a revalidation that answers 304 when
 * nothing changed: read again at each opening of the tab and when the window has the focus again, so rules that changed
 * while the form was open (a config change restarts the pods) reach it. An answer of another shape is the error state.
 */
export function useMetadataKeys(): Result<MetadataRules> & { reload: () => void } {
  const api = useApi();
  const query = useQuery({
    queryKey: ["metadata-keys"],
    staleTime: 0,
    refetchOnWindowFocus: true,
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/api/v1/metadata-keys", { signal });
      if (!data) throw problemOf(response, error);
      try {
        return { form: fieldsOf(data), fingerprint: JSON.stringify(data) };
      } catch (e) {
        if (e instanceof RulesUnreadable) throw new ApiProblem({ status: response.status, code: "metadata-rules-unreadable", detail: e.message });
        throw e;
      }
    }
  });
  return { ...resultOf(query), reload: () => void query.refetch() };
}

/**
 * POST /api/v1/clusters/{cluster_id}/namespaces?dryRun=true: the plan, the capacity check and the approval that would
 * apply. It writes nothing, so it is a read for Query, keyed on the body: the same form asks once. `body` null asks nothing.
 */
export function usePlan(clusterId: string, body: CreateBody | null): Outcome<Plan> & { reload: () => void } {
  const api = useApi();
  const query = useQuery({
    queryKey: ["plan", clusterId, body],
    // Every dry run must ask the server again, even when returning to a previously checked draft.
    staleTime: 0,
    gcTime: 0,
    enabled: body !== null,
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.POST("/api/v1/clusters/{cluster_id}/namespaces", {
        params: { path: { cluster_id: clusterId }, query: { dryRun: true } }, body: contractBody(body!), signal
      });
      if (!data) throw problemOf(response, error);
      // The dry run answers 200 with a plan. A 202 here would be a written request: the API broke its contract.
      if (response.status !== 200) throw new ApiProblem({ status: 500, code: "not-a-plan", detail: `The dry run answered ${response.status}, not 200.` });
      return data as Plan;
    }
  });
  if (body === null) return { state: "idle", reload: () => undefined };
  return { ...outcomeOf({ isPending: query.isFetching, isIdle: false, error: query.error, data: query.data }), reload: () => void query.refetch() };
}

/**
 * POST /api/v1/clusters/{cluster_id}/namespaces: submits the request. The caller gives the Idempotency-Key, one for each
 * opening of the form (#282): sending again after a refusal or a lost answer reuses it, so the API never makes two requests.
 */
export function useSubmitNamespace(): Outcome<ChangeRequest> & { submit: (clusterId: string, body: CreateBody, key: string) => Promise<ChangeRequest> } {
  const api = useApi();
  const client = useQueryClient();
  const mutation = useMutation({
    mutationFn: async ({ clusterId, body, key }: { clusterId: string; body: CreateBody; key: string }) => {
      const { data, error, response } = await api.POST("/api/v1/clusters/{cluster_id}/namespaces", {
        params: { path: { cluster_id: clusterId }, header: { "Idempotency-Key": key } }, body: contractBody(body)
      });
      if (!data) throw problemOf(response, error);
      return data as ChangeRequest;
    },
    // The new request belongs in each list of requests, so each is read again when it is next shown.
    onSuccess: () => client.invalidateQueries({ queryKey: ["requests"] })
  });
  const send = useOneAtATime(mutation.mutateAsync);
  return { ...outcomeOf(mutation), submit: (clusterId, body, key) => send({ clusterId, body, key }) };
}

/** GET /api/v1/requests/{request_id}: the request, its approval ledger and its PR. An open request is read again until it ends. */
export function useRequest(requestId: string | undefined): Result<ChangeRequest> & { reload: () => void } {
  const api = useApi();
  const query = useQuery({
    queryKey: ["request", requestId],
    enabled: requestId !== undefined,
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/api/v1/requests/{request_id}", { params: { path: { request_id: requestId! } }, signal });
      if (!data) throw problemOf(response, error);
      return data;
    },
    refetchInterval: (q) => (q.state.data && OPEN_STATES.has(q.state.data.status) ? FOLLOW_MS : false)
  });
  return { ...resultOf(query), reload: () => void query.refetch() };
}

/** GET /api/v1/requests/{request_id}/events: every state change, oldest first. The Workflow tab's steps. */
export function useEvents(requestId: string | undefined): Result<RequestEvents> & { reload: () => void } {
  const api = useApi();
  const query = useQuery({
    queryKey: ["events", requestId],
    enabled: requestId !== undefined,
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/api/v1/requests/{request_id}/events", { params: { path: { request_id: requestId! } }, signal });
      if (!data) throw problemOf(response, error);
      return data;
    },
    refetchInterval: (q) => (q.state.data && OPEN_STATES.has(q.state.data.status) ? FOLLOW_MS : false)
  });
  return { ...resultOf(query), reload: () => void query.refetch() };
}

/** After a decision: the request and the lists are stale. They are read again when shown next, not now, so the card stays. */
function useDecided() {
  const client = useQueryClient();
  return (requestId: string) => {
    void client.invalidateQueries({ queryKey: ["requests"], refetchType: "none" });
    void client.invalidateQueries({ queryKey: ["request", requestId] });
    void client.invalidateQueries({ queryKey: ["events", requestId] });
  };
}

/** POST /api/v1/requests/{request_id}:approve. The API decides who may approve; a refusal comes back with its code. */
export function useApprove(): Outcome<ChangeRequest> & { approve: (requestId: string) => Promise<ChangeRequest> } {
  const api = useApi();
  const decided = useDecided();
  const mutation = useMutation({
    mutationFn: async (requestId: string) => {
      const { data, error, response } = await api.POST("/api/v1/requests/{request_id}:approve", { params: { path: { request_id: requestId } }, body: { comment: "" } });
      if (!data) throw problemOf(response, error);
      return data;
    },
    onSuccess: (_, requestId) => decided(requestId)
  });
  const send = useOneAtATime(mutation.mutateAsync);
  return { ...outcomeOf(mutation), approve: (requestId) => send(requestId) };
}

/** POST /api/v1/requests/{request_id}:reject, with the reason that the requester sees. */
export function useReject(): Outcome<ChangeRequest> & { reject: (requestId: string, comment: string) => Promise<ChangeRequest> } {
  const api = useApi();
  const decided = useDecided();
  const mutation = useMutation({
    mutationFn: async ({ requestId, comment }: { requestId: string; comment: string }) => {
      const { data, error, response } = await api.POST("/api/v1/requests/{request_id}:reject", { params: { path: { request_id: requestId } }, body: { comment } });
      if (!data) throw problemOf(response, error);
      return data;
    },
    onSuccess: (_, { requestId }) => decided(requestId)
  });
  const send = useOneAtATime(mutation.mutateAsync);
  return { ...outcomeOf(mutation), reject: (requestId, comment) => send({ requestId, comment }) };
}

/**
 * A page of GET /api/v1/quotas with the query that asked for it. The API's page does not say its sort, and while the next
 * page loads Query shows this one in its place (keepPreviousData), so what the page says of its rows comes from `asked`,
 * never from the query just sent (#392).
 */
export type AskedQuotaPage = QuotaPage & { asked: QuotasQuery };

/** GET /api/v1/quotas: one query for each page, with its filters, its sort and its cursor as the key. */
export function useQuotas(params: QuotasQuery): Result<AskedQuotaPage> & { reload: () => void } {
  const api = useApi();
  const query = useQuery({
    queryKey: ["quotas", params],
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/api/v1/quotas", { params: { query: params }, signal });
      if (!data) throw problemOf(response, error);
      return { ...data, asked: params };
    },
    // The rows of the last page stay while the next page loads.
    placeholderData: keepPreviousData
  });
  return { ...resultOf(query), reload: () => void query.refetch() };
}

/** The API answers fewer than two characters with no match (GET /api/v1/quotas:suggest), so the portal does not ask. */
export const SUGGEST_MIN = 2;

/**
 * GET /api/v1/quotas:suggest: the type-ahead's matches for one text. A new text is a new query; Query cancels the call that
 * it replaces through the signal, so a slow answer for an old text never shows.
 */
export function useSuggest(text: string): Result<Suggestion[]> {
  const api = useApi();
  const q = text.trim();
  const query = useQuery({
    queryKey: ["quotas:suggest", q],
    enabled: q.length >= SUGGEST_MIN,
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/api/v1/quotas:suggest", { params: { query: { q } }, signal });
      if (!data) throw problemOf(response, error);
      return data.items;
    }
  });
  if (q.length < SUGGEST_MIN) return { state: "ok", data: [], refreshing: false };
  return resultOf(query);
}

/** A problem from a body that was read as text: the export answers text/csv, and a refusal application/problem+json. */
function problemOfText(response: Response, text: unknown): ApiProblem {
  try {
    return problemOf(response, typeof text === "string" ? JSON.parse(text) : text);
  } catch {
    return problemOf(response, null);
  }
}

/**
 * GET /api/v1/quotas:export: every row of the filters, as CSV. The API records each export in the audit log, so it is an
 * action of the person, sent once for each click, not a read that Query caches and sends again by itself.
 */
export function useExport(): Outcome<string> & { run: (params: ExportQuery) => Promise<string>; reset: () => void } {
  const api = useApi();
  const mutation = useMutation({
    mutationFn: async (params: ExportQuery) => {
      const { data, error, response } = await api.GET("/api/v1/quotas:export", { params: { query: params }, parseAs: "text" });
      if (!response.ok || typeof data !== "string") throw problemOfText(response, error);
      return data;
    }
  });
  const send = useOneAtATime(mutation.mutateAsync);
  return { ...outcomeOf(mutation), run: (params) => send(params), reset: mutation.reset };
}

/** GET /api/v1/clusters/{cluster_id}/namespaces/{ns}: the namespace and its etag, the If-Match of a change. */
export function useNamespace(clusterId: string, ns: string): Result<NamespaceView> & { reload: () => void } {
  const api = useApi();
  const query = useQuery({
    queryKey: ["namespace", clusterId, ns],
    enabled: clusterId !== "" && ns !== "",
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/api/v1/clusters/{cluster_id}/namespaces/{ns}", { params: { path: { cluster_id: clusterId, ns } }, signal });
      if (!data) throw problemOf(response, error);
      return data;
    }
  });
  return { ...resultOf(query), reload: () => void query.refetch() };
}

/**
 * GET /api/v1/clusters/{cluster_id}/namespaces with the lookup's parameters (#481 design section 4.4): the Namespaces tab's
 * mnemonic chips and its type-ahead. A new text is a new query; Query cancels the call that it replaces through the signal,
 * so a slow answer for an old text never shows. An empty cluster asks nothing.
 */
export function useNamespaceList(clusterId: string, params: NamespaceListQuery, enabled = true): Result<NamespaceList> & { reload: () => void } {
  const api = useApi();
  const query = useQuery({
    queryKey: ["namespaces", clusterId, params],
    enabled: enabled && clusterId !== "",
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/api/v1/clusters/{cluster_id}/namespaces", { params: { path: { cluster_id: clusterId }, query: params }, signal });
      if (!data) throw problemOf(response, error);
      return data;
    }
  });
  return { ...resultOf(query), reload: () => void query.refetch() };
}

/** One change of a namespace as the person planned it: where, the etag it was read at, and the body. */
export interface PlannedChange {
  clusterId: string;
  ns: string;
  etag: string;
  body: NamespacePatch;
}

/** An etag as If-Match sends it: a quoted entity tag (RFC 9110, section 8.8.3). The API gives it unquoted in the body. */
const ifMatchOf = (etag: string): string => (etag.startsWith("\"") ? etag : `"${etag}"`);

/**
 * PATCH /api/v1/clusters/{cluster_id}/namespaces/{ns}?dryRun=true: the plan of a change, its capacity check and the
 * approval that would apply. It writes nothing and needs no Idempotency-Key, so it is a read for Query, keyed on the change.
 */
export function usePatchPlan(change: PlannedChange | null): Outcome<Plan> & { reload: () => void } {
  const api = useApi();
  const query = useQuery({
    queryKey: ["patch-plan", change],
    // Every dry run asks the server again, also for a change that was checked before (#527): Git, capacity and the lock move.
    staleTime: 0,
    gcTime: 0,
    enabled: change !== null,
    queryFn: async ({ signal }) => {
      const { clusterId, ns, etag, body } = change!;
      const { data, error, response } = await api.PATCH("/api/v1/clusters/{cluster_id}/namespaces/{ns}", {
        params: { path: { cluster_id: clusterId, ns }, query: { dryRun: true }, header: { "If-Match": ifMatchOf(etag) } }, body, signal
      });
      if (!data) throw problemOf(response, error);
      // The dry run answers 200 with a plan. A 202 here would be a written request: the API broke its contract.
      if (response.status !== 200) throw new ApiProblem({ status: 500, code: "not-a-plan", detail: `The dry run answered ${response.status}, not 200.` });
      return data as Plan;
    }
  });
  if (change === null) return { state: "idle", reload: () => undefined };
  // A check in flight is not a pass: Query keeps the last answer in `data` while it asks again.
  if (query.isFetching) return { state: "sending", reload: () => void query.refetch() };
  return { ...outcomeOf({ isPending: query.isFetching, isIdle: false, error: query.error, data: query.data }), reload: () => void query.refetch() };
}

/**
 * PATCH /api/v1/clusters/{cluster_id}/namespaces/{ns}: submits the change that was planned, with the etag that it was planned
 * at as If-Match and the caller's Idempotency-Key. The namespace and the quota list are stale after it.
 */
export function useSubmitPatch(): Outcome<ChangeRequest> & { submit: (change: PlannedChange, key: string) => Promise<ChangeRequest> } {
  const api = useApi();
  const client = useQueryClient();
  const mutation = useMutation({
    mutationFn: async ({ change, key }: { change: PlannedChange; key: string }) => {
      const { clusterId, ns, etag, body } = change;
      const { data, error, response } = await api.PATCH("/api/v1/clusters/{cluster_id}/namespaces/{ns}", {
        params: { path: { cluster_id: clusterId, ns }, header: { "Idempotency-Key": key, "If-Match": ifMatchOf(etag) } }, body
      });
      if (!data) throw problemOf(response, error);
      return data as ChangeRequest;
    },
    // Read again when shown next, not now: the form keeps its answer on the page, as the mockup's does.
    onSuccess: (_, { change }) => {
      void client.invalidateQueries({ queryKey: ["requests"], refetchType: "none" });
      void client.invalidateQueries({ queryKey: ["quotas"], refetchType: "none" });
      void client.invalidateQueries({ queryKey: ["namespace", change.clusterId, change.ns], refetchType: "none" });
    }
  });
  const send = useOneAtATime(mutation.mutateAsync);
  return { ...outcomeOf(mutation), submit: (change, key) => send({ change, key }) };
}

/** GET /api/v1/tiers with no environment: the catalog of each environment that the instance serves. */
export function useCatalog(): Result<TierCatalog> & { reload: () => void } {
  const api = useApi();
  const query = useQuery({
    queryKey: ["tiers", ""],
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/api/v1/tiers", { signal });
      if (!data) throw problemOf(response, error);
      return data;
    }
  });
  return { ...resultOf(query), reload: () => void query.refetch() };
}

/** GET /api/v1/admin/kpi: the answering process's cgroup figures, the database and the live KPIs (docs/17-kpis.md). */
export function useKpi(): Result<KpiView> & { reload: () => void } {
  const api = useApi();
  const query = useQuery({
    queryKey: ["kpi"],
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/api/v1/admin/kpi", { signal });
      if (!data) throw problemOf(response, error);
      return data;
    }
  });
  return { ...resultOf(query), reload: () => void query.refetch() };
}

/** GET /api/v1/policies/results: the clusters, the policies and one page of results, each page keyed on its filters and cursor. */
export function usePolicyResults(params: PolicyResultsQuery): Result<PolicyResultPage> & { reload: () => void } {
  const api = useApi();
  const query = useQuery({
    queryKey: ["policy-results", params],
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/api/v1/policies/results", { params: { query: params }, signal });
      if (!data) throw problemOf(response, error);
      return data;
    },
    // The rows of the last page stay while the next page loads.
    placeholderData: keepPreviousData
  });
  return { ...resultOf(query), reload: () => void query.refetch() };
}

/** GET /api/v1/policies/rejections: what cmapi refused before Git, one query for each page. */
export function usePolicyRejections(params: RejectionsQuery): Result<RejectionPage> & { reload: () => void } {
  const api = useApi();
  const query = useQuery({
    queryKey: ["policy-rejections", params],
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/api/v1/policies/rejections", { params: { query: params }, signal });
      if (!data) throw problemOf(response, error);
      return data;
    },
    placeholderData: keepPreviousData
  });
  return { ...resultOf(query), reload: () => void query.refetch() };
}

/** How often the Capacity tab reads GET /api/v1/capacity again while it is open (the arbitration of #302: on focus, and 60 s). */
export const CAPACITY_REFRESH_MS = 60_000;
/** How long a Placement preview answer is reused for the same ask before it is ranked again. */
export const PLACEMENT_FRESH_MS = 60_000;

/**
 * GET /api/v1/capacity: each cluster's commitment and the groups (#302). The answer carries a strong ETag and
 * `Cache-Control: private, no-cache`, so the browser's own cache sends If-None-Match on each read again and turns a 304 into
 * the stored answer: a read with nothing new costs the API a hash and moves no byte. So the query is never fresh (staleTime 0)
 * and is read again on focus and every CAPACITY_REFRESH_MS.
 */
export function useCapacity(): Result<CapacityPage> & { reload: () => void } {
  const api = useApi();
  const query = useQuery({
    queryKey: ["capacity"],
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/api/v1/capacity", { signal });
      if (!data) throw problemOf(response, error);
      return data;
    },
    refetchOnWindowFocus: true,
    staleTime: 0,
    refetchInterval: CAPACITY_REFRESH_MS
  });
  return { ...resultOf(query), reload: () => void query.refetch() };
}

/**
 * POST /api/v1/capacity:place?dryRun=true: the New namespace tab's Placement preview (#303). It ranks the clusters and holds
 * nothing. Each ask (environment, team, tier, region) is asked once a minute at most: the API's :place bucket allows 10 a
 * minute per caller (core/ratelimit.py), so moving between tiers reuses each answer instead of spending it.
 */
export function usePlacementPreview(ask: PlacementRequest | null): (Result<PlacementResult> | { state: "idle" }) & { rank: (now: PlacementRequest) => Promise<PlacementResult> } {
  const api = useApi();
  const client = useQueryClient();
  const options = (a: PlacementRequest | null) => ({
    queryKey: ["placement", a],
    staleTime: PLACEMENT_FRESH_MS,
    queryFn: async ({ signal }: { signal: AbortSignal }) => {
      const { data, error, response } = await api.POST("/api/v1/capacity:place", { params: { query: { dryRun: true } }, body: a!, signal });
      if (!data) throw problemOf(response, error);
      return data;
    }
  });
  // The last ranking stays while a changed ask is ranked, so the planned cluster does not blink away.
  const query = useQuery({ ...options(ask), enabled: ask !== null, placeholderData: keepPreviousData });
  // The ranking of an ask now, from the cache when it is fresh: Check asks it, so a Check right after typing the team waits for
  // its ranking instead of finding none.
  const rank = (now: PlacementRequest) => client.fetchQuery(options(now));
  return { ...(ask === null ? { state: "idle" as const } : resultOf(query)), rank };
}

/**
 * POST /api/v1/capacity:place: holds the first cluster that still fits for 15 minutes and returns its `placementId`, which
 * the create sends (docs/02, "Placement"). The preview is not ranked again at once: the hold is this form's own, and a ranking
 * that counted it could move the first cluster away from the plan that Submit is sending.
 */
export function usePlace(): Outcome<PlacementResult> & { place: (ask: PlacementRequest) => Promise<PlacementResult> } {
  const api = useApi();
  const mutation = useMutation({
    mutationFn: async (ask: PlacementRequest) => {
      const { data, error, response } = await api.POST("/api/v1/capacity:place", { body: ask });
      if (!data) throw problemOf(response, error);
      return data;
    }
  });
  const send = useOneAtATime(mutation.mutateAsync);
  return { ...outcomeOf(mutation), place: (ask) => send(ask) };
}

/** GET /api/v1/expirations: one query for each page, with its filters and its cursor as the key. */
export function useExpirations(params: ExpirationsQuery): Result<ExpirationPage> & { reload: () => void } {
  const api = useApi();
  const query = useQuery({
    queryKey: ["expirations", params],
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/api/v1/expirations", { params: { query: params }, signal });
      if (!data) throw problemOf(response, error);
      return data;
    },
    // The rows of the last page stay while the next page loads.
    placeholderData: keepPreviousData
  });
  return { ...resultOf(query), reload: () => void query.refetch() };
}

/** The three expiry writes of the namespaces plugin, each a POST with its own body. */
export type ExpiryChange =
  | { route: "extend"; body: { days: number } }
  | { route: "set"; body: { until: string } }
  | { route: "makePermanent"; body: Record<string, never> };

/** One expiry change as the person planned it: where, the etag it was read at, the route and the body. */
export type PlannedExpiry = { clusterId: string; ns: string; etag: string } & ExpiryChange;

/** The call of one expiry change, as a dry run or as the write: If-Match always, the Idempotency-Key on the write only. */
async function postExpiry(api: Api, change: PlannedExpiry, opts: { dryRun?: true; key?: string; signal?: AbortSignal }) {
  const path = { cluster_id: change.clusterId, ns: change.ns };
  const header = { "If-Match": ifMatchOf(change.etag), ...(opts.key ? { "Idempotency-Key": opts.key } : {}) };
  const query = opts.dryRun ? { dryRun: true } : undefined;
  const init = { params: { path, query, header }, signal: opts.signal };
  switch (change.route) {
    case "extend": return api.POST("/api/v1/clusters/{cluster_id}/namespaces/{ns}/expiration:extend", { ...init, body: change.body });
    case "set": return api.POST("/api/v1/clusters/{cluster_id}/namespaces/{ns}/expiration:set", { ...init, body: change.body });
    case "makePermanent": return api.POST("/api/v1/clusters/{cluster_id}/namespaces/{ns}/expiration:makePermanent", { ...init, body: change.body });
  }
}

/**
 * The dry run of an expiry change (`?dryRun=true`): the plan and the approval that would apply. It writes nothing and needs
 * no Idempotency-Key, so it is a read for Query, keyed on the change. `change` null asks nothing.
 */
export function useExpiryPlan(change: PlannedExpiry | null): Outcome<Plan> & { reload: () => void } {
  const api = useApi();
  const query = useQuery({
    queryKey: ["expiry-plan", change],
    enabled: change !== null,
    queryFn: async ({ signal }) => {
      const { data, error, response } = await postExpiry(api, change!, { dryRun: true, signal });
      if (!data) throw problemOf(response, error);
      // The dry run answers 200 with a plan. A 202 here would be a written request: the API broke its contract.
      if (response.status !== 200) throw new ApiProblem({ status: 500, code: "not-a-plan", detail: `The dry run answered ${response.status}, not 200.` });
      return data as Plan;
    }
  });
  if (change === null) return { state: "idle", reload: () => undefined };
  return { ...outcomeOf({ isPending: query.isFetching, isIdle: false, error: query.error, data: query.data }), reload: () => void query.refetch() };
}

/**
 * Submits the expiry change that was planned, with the etag that it was planned at as If-Match and the caller's
 * Idempotency-Key. One write at a time. The namespace and the lists are stale after it.
 */
export function useSubmitExpiry(): Outcome<ChangeRequest> & { submit: (change: PlannedExpiry, key: string) => Promise<ChangeRequest> } {
  const api = useApi();
  const client = useQueryClient();
  const mutation = useMutation({
    mutationFn: async ({ change, key }: { change: PlannedExpiry; key: string }) => {
      const { data, error, response } = await postExpiry(api, change, { key });
      if (!data) throw problemOf(response, error);
      return data as ChangeRequest;
    },
    // Read again when shown next, not now: the form keeps its answer on the page, as the mockup's does.
    onSuccess: (_, { change }) => {
      void client.invalidateQueries({ queryKey: ["requests"], refetchType: "none" });
      void client.invalidateQueries({ queryKey: ["expirations"], refetchType: "none" });
      void client.invalidateQueries({ queryKey: ["namespace", change.clusterId, change.ns], refetchType: "none" });
    }
  });
  const send = useOneAtATime(mutation.mutateAsync);
  return { ...outcomeOf(mutation), submit: (planned, key) => send({ change: planned, key }) };
}
