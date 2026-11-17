// RFC 9457 problem details: the one shape of each refusal of the API (ProblemDetail in the OpenAPI document).
import type { components } from "./schema.generated";

export type ProblemDetail = components["schemas"]["ProblemDetail"];

/**
 * One item of a problem's `errors` (RFC 9457 allows extension members): what cmapi refused, and where. A refusal of
 * labels and annotations names the key and, for a missing one, its kind (core/metadata.py, validate).
 */
export interface ProblemItem {
  code: string;
  key?: string;
  kind?: string;
  detail?: string;
}

/** A refusal of the API, with the problem that it sent. */
export class ApiProblem extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: string;
  /** The problem's `errors`, each item that has a code; the form puts each one that names a key under its field. */
  readonly errors: ProblemItem[];

  constructor(problem: Pick<ProblemDetail, "status" | "code" | "detail"> & { errors?: ProblemItem[] }) {
    super(`${problem.status} ${problem.code}`);
    this.name = "ApiProblem";
    this.status = problem.status;
    this.code = problem.code;
    this.detail = problem.detail;
    this.errors = problem.errors ?? [];
  }
}

const isProblem = (body: unknown): body is ProblemDetail =>
  typeof body === "object" && body !== null && typeof (body as ProblemDetail).code === "string" && typeof (body as ProblemDetail).detail === "string";

const text = (value: unknown): string | undefined => (typeof value === "string" ? value : undefined);

/** The items of a problem's `errors` that are objects with a text code. Any other item, and any other field, is dropped. */
export function itemsOf(errors: unknown): ProblemItem[] {
  if (!Array.isArray(errors)) return [];
  return errors.flatMap((raw): ProblemItem[] => {
    if (typeof raw !== "object" || raw === null) return [];
    const item = raw as Record<string, unknown>;
    const code = text(item.code);
    if (code === undefined) return [];
    const out: ProblemItem = { code };
    for (const field of ["key", "kind", "detail"] as const) {
      const value = text(item[field]);
      if (value !== undefined) out[field] = value;
    }
    return [out];
  });
}

/**
 * The problem of an answer that is not 2xx. `body` is the answer's body as the client parsed it. A body that is not a
 * problem (a proxy's error page) still gives one, from the status alone.
 */
export function problemOf(response: Response, body: unknown): ApiProblem {
  if (isProblem(body)) return new ApiProblem({ status: response.status, code: body.code, detail: body.detail, errors: itemsOf(body.errors) });
  return new ApiProblem({ status: response.status, code: `http-${response.status}`, detail: `The API answered ${response.status} with no problem details.` });
}
