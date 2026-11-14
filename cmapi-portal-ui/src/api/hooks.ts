// One typed hook for each endpoint that the portal reads. Server data lives in TanStack Query, not in component state.
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { createContext, useContext } from "react";
import type { Api } from "./client";
import { ApiProblem, problemOf } from "./problem";
import type { components, operations } from "./schema.generated";

export type Me = components["schemas"]["Me"];
export type RequestPage = components["schemas"]["RequestPage"];
export type ChangeRequest = components["schemas"]["ChangeRequest"];
export type RequestsQuery = NonNullable<operations["requests_list_requests"]["parameters"]["query"]>;

/** What a section shows for one read. A 401 is not here: the client signs in again and the section never sees it. */
export type Result<T> =
  | { state: "loading" }
  | { state: "error"; cause: string; code: string }
  | { state: "forbidden"; detail: string }
  | { state: "ok"; data: T; refreshing: boolean };

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
