// One typed hook for each endpoint that the portal reads. Server data lives in TanStack Query, not in component state.
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext } from "react";
import type { Api } from "./client";
import { ApiProblem, problemOf } from "./problem";
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
export type RequestEvents = components["schemas"]["RequestEvents"];
export type RequestEvent = components["schemas"]["RequestEvent"];

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
  | { state: "refused"; status: number; code: string; detail: string }
  | { state: "error"; cause: string; code: string }
  | { state: "ok"; data: T };

const ApiContext = createContext<Api | null>(null);
export const ApiProvider = ApiContext.Provider;

function useApi(): Api {
  const api = useContext(ApiContext);
  if (!api) throw new Error("No API client: the component is outside ApiProvider.");
  return api;
}

function resultOf<T>(query: { data: T | undefined; error: unknown; isPlaceholderData: boolean; isFetching: boolean }): Result<T> {
  const { error } = query;
  if (error instanceof ApiProblem) {
    return error.status === 403 ? { state: "forbidden", detail: error.detail } : { state: "error", cause: error.detail, code: error.code };
  }
  if (error) return { state: "error", cause: "The network did not answer.", code: "network" };
  if (query.data === undefined) return { state: "loading" };
  return { state: "ok", data: query.data, refreshing: query.isPlaceholderData && query.isFetching };
}

function outcomeOf<T>(run: { isPending: boolean; isIdle: boolean; error: unknown; data: T | undefined }): Outcome<T> {
  const { error } = run;
  if (error instanceof ApiProblem) {
    // A 5xx says that the API could not answer, not that it refused: the person may send the same call again.
    return error.status >= 500 ? { state: "error", cause: error.detail, code: error.code } : { state: "refused", status: error.status, code: error.code, detail: error.detail };
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

/**
 * POST /api/v1/clusters/{cluster_id}/namespaces?dryRun=true: the plan, the capacity check and the approval that would
 * apply. It writes nothing, so it is a read for Query, keyed on the body: the same form asks once. `body` null asks nothing.
 */
export function usePlan(clusterId: string, body: NamespaceCreate | null): Outcome<Plan> & { reload: () => void } {
  const api = useApi();
  const query = useQuery({
    queryKey: ["plan", clusterId, body],
    enabled: body !== null,
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.POST("/api/v1/clusters/{cluster_id}/namespaces", {
        params: { path: { cluster_id: clusterId }, query: { dryRun: true } }, body: body!, signal
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
export function useSubmitNamespace(): Outcome<ChangeRequest> & { submit: (clusterId: string, body: NamespaceCreate, key: string) => Promise<ChangeRequest> } {
  const api = useApi();
  const client = useQueryClient();
  const mutation = useMutation({
    mutationFn: async ({ clusterId, body, key }: { clusterId: string; body: NamespaceCreate; key: string }) => {
      const { data, error, response } = await api.POST("/api/v1/clusters/{cluster_id}/namespaces", {
        params: { path: { cluster_id: clusterId }, header: { "Idempotency-Key": key } }, body
      });
      if (!data) throw problemOf(response, error);
      return data as ChangeRequest;
    },
    // The new request belongs in each list of requests, so each is read again when it is next shown.
    onSuccess: () => client.invalidateQueries({ queryKey: ["requests"] })
  });
  return { ...outcomeOf(mutation), submit: (clusterId, body, key) => mutation.mutateAsync({ clusterId, body, key }) };
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
  return { ...outcomeOf(mutation), approve: (requestId) => mutation.mutateAsync(requestId) };
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
  return { ...outcomeOf(mutation), reject: (requestId, comment) => mutation.mutateAsync({ requestId, comment }) };
}
