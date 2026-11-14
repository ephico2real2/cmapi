// RFC 9457 problem details: the one shape of each refusal of the API (ProblemDetail in the OpenAPI document).
import type { components } from "./schema.generated";

export type ProblemDetail = components["schemas"]["ProblemDetail"];

/** A refusal of the API, with the problem that it sent. */
export class ApiProblem extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: string;

  constructor(problem: Pick<ProblemDetail, "status" | "code" | "detail">) {
    super(`${problem.status} ${problem.code}`);
    this.name = "ApiProblem";
    this.status = problem.status;
    this.code = problem.code;
    this.detail = problem.detail;
  }
}

const isProblem = (body: unknown): body is ProblemDetail =>
  typeof body === "object" && body !== null && typeof (body as ProblemDetail).code === "string" && typeof (body as ProblemDetail).detail === "string";

/**
 * The problem of an answer that is not 2xx. `body` is the answer's body as the client parsed it. A body that is not a
 * problem (a proxy's error page) still gives one, from the status alone.
 */
export function problemOf(response: Response, body: unknown): ApiProblem {
  if (isProblem(body)) return new ApiProblem({ status: response.status, code: body.code, detail: body.detail });
  return new ApiProblem({ status: response.status, code: `http-${response.status}`, detail: `The API answered ${response.status} with no problem details.` });
}
