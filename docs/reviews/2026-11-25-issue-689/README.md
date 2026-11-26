# #689: the rate limits of docs/01 on every route that takes a token, 429 `rate-limited` with `Retry-After`

The implementer's record: Opus 5.5 at `high`, 2026-11-25, on `fix/689-rate-limits` from main `cf1c0f4`. The fix is a security
control (OWASP API4), so it gets two reviewers; their records go beside this one. Found with it and fixed in the same pull
request: #694 (Low), the 503s that carry `retryAfter` sent no `Retry-After` header.

## What was wrong

docs/01, "Operational safety": "**Rate limits.** Token buckets per caller and per team, separate for writes, :place, :suggest
and :export, and at most 3 active placements per team and environment". `cmapi/src/cmapi/core/ratelimit.py` held a
`RateLimiter`, and no module of `cmapi/src` imported it; no operation of `contract/openapi.json` declared 429. #683 bounds the
cost of one request (1 MiB of content, 20 errors in a 422); without a rate limit a signed-in caller could repeat it without
limit: 0.365 s of the event loop for each 769 KB body of 60,000 unknown members (#683's `measure-422.txt`).

The reference module also disagreed with the design in three places, each fixed here:

- Every route took a token from one per-caller `default` bucket (120 a minute) and its class's bucket too, so `:suggest`
  (240 a minute) could never pass 120: the buckets were not "separate". Now each call takes from exactly one of the caller's
  buckets.
- There was no bucket for writes: the per-caller write limit of docs/01 was missing.
- The placement cap was 10 per team; docs/01 says 3 per team and environment. No route uses it yet (`:place` is not built).

## Sources

Each fetched 2026-11-25; copies are in the implementer's `sources/`.

- **RFC 6585, section 4** (<https://www.rfc-editor.org/rfc/rfc6585.txt>): "The 429 status code indicates that the user has
  sent too many requests in a given amount of time ("rate limiting")." "The response representations SHOULD include details
  explaining the condition, and MAY include a Retry-After header indicating how long to wait before making a new request."
  "Note that this specification does not define how the origin server identifies the user, nor how it counts requests. [...]
  it might identify the user by its authentication credentials". "Responses with the 429 status code MUST NOT be stored by a
  cache."
- **RFC 9110, section 10.2.3** (<https://www.rfc-editor.org/rfc/rfc9110.txt>): "Servers send the "Retry-After" header field to
  indicate how long the user agent ought to wait before making a follow-up request." "Retry-After = HTTP-date /
  delay-seconds", "A delay-seconds value is a non-negative decimal integer, representing time in seconds." "When sent with a
  503 (Service Unavailable) response, Retry-After indicates how long the service is expected to be unavailable to the
  client."
- **draft-ietf-httpapi-ratelimit-headers-12** (<https://datatracker.ietf.org/doc/draft-ietf-httpapi-ratelimit-headers/>,
  last updated 2026-11-20, expires 2027-05-24; IESG state "I-D Exists", intended RFC status none): "Internet-Drafts are draft
  documents valid for a maximum of six months and may be updated, replaced, or obsoleted by other documents at any time. It is
  inappropriate to use Internet-Drafts as reference material or to cite them other than as "work in progress."" Section 9.2:
  "Servers should not disclose to untrusted parties operational capacity information that can be used to saturate its
  infrastructural resources."
- **OWASP API Security Top 10 2023, API4**
  (<https://raw.githubusercontent.com/OWASP/API-Security/master/editions/2023/en/0xa4-unrestricted-resource-consumption.md>),
  How To Prevent: "Implement a limit on how often a client can interact with the API within a defined timeframe (rate
  limiting)." "Rate limiting should be fine tuned based on the business needs. Some API Endpoints might require stricter
  policies."
- **nginx `ngx_http_limit_req_module`** (<https://nginx.org/en/docs/http/ngx_http_limit_req_module.html>): "used to limit the
  request processing rate per a defined key, in particular, the processing rate of requests coming from a single IP address";
  its example keys on `$binary_remote_addr`; "limit_req_status 503" is the default; the zone's `sync` parameter is "available
  as part of our commercial subscription".
- **Envoy, local rate limiting**
  (<https://raw.githubusercontent.com/envoyproxy/envoy/main/docs/root/intro/arch_overview/other_features/local_rate_limiting.rst>):
  "Envoy supports local (non-distributed) rate limiting [...] Local rate limiting can be used in conjunction with global rate
  limiting to reduce load on the global rate limit service." Global rate limiting (`global_rate_limiting.rst`) needs a rate
  limit service that each request asks.
- **Kubernetes, API Priority and Fairness**
  (<https://raw.githubusercontent.com/kubernetes/website/main/content/en/docs/concepts/cluster-administration/flow-control.md>):
  limits are per API server, and "horizontally scaling the number of `kube-apiserver` instances will increase the total
  concurrency per priority level across the cluster assuming there is sufficient load balancing of requests."
- **FastAPI 0.162.2 and Starlette 1.10.0** (the lock, `cmapi/requirements.txt`), installed source. FastAPI's request handler
  reads the body and decodes JSON first (`routing.py:450-499`), then calls `solve_dependencies` (`:511`). That solves each
  sub-dependency in order (`dependencies/utils.py:676`), then the path, query, header and cookie parameters, then the body
  (`request_body_to_args`, to `:768`); an exception that a dependency raises leaves at once, before any of those checks.
  FastAPI sets `scope["route"]` to the matched `APIRoute` before it handles it (`routing.py:1864`).

## The decisions

**Which routes.** Every route that takes a token: the routers that `api_app` includes with the sign-in dependency, 39
operations. The routes with no token (`/api/v1/version`, `/healthz`, `/readyz`, `/problems`, the docs and their files) have
no caller, and docs/01 limits callers. A call with no valid token is 401 and takes no token.

**Which bucket.** The design's classes, by the route's template (`core/ratelimit.py`, `rate_class`): `:place`, `:suggest`
and `:export` by name, else `write` for POST, PUT, PATCH and DELETE (a dry run too: it runs the validator), else `read`. The
template, not the URL, so a request ID that ends in ":export" does not make a read an export. The document names the class of
each operation in `x-cmapi-rate-limit`.

**Who is the caller.** The token's `sub`, as RFC 6585 allows ("by its authentication credentials"): a person's portal and CLI
tokens share a bucket, and a service that sends `onBehalfOf` spends its own, as it owns its Idempotency-Key (#592).

**The team.** docs/01 says "per team". cmapi's tokens carry no team (docs/01: "there are no team or namespace-name scopes");
a team is the namespace's `cmapi.net/team`. It is known only once the plan has read the body and Git, so the team's bucket
is taken in `_submit` of the namespaces router, after the plan and before the request is recorded: one token for each change
request opened for the team. docs/02 says the limits "Protect clusters and the Git host from bursts", and each request
becomes a branch and a pull request. A dry run, an Idempotency-Key replay and a refused plan open nothing and take nothing.
A worker job that opens a request (a revert) is not limited: it is not a caller's call. Any caller may name any team, so the
default team limit (600 a minute, 200 at once) is far above one caller's writes (60, 30): one caller alone cannot empty a
team's bucket.

**Where the caller's check runs.** A FastAPI dependency after the sign-in, on the same routers (`routers/__init__.py`,
`rate_limit`; `main.py`, `api_app`). By FastAPI's order above, it refuses before the permission, every parameter and the
body's validation, and before any work of the route; the cost left is the read and JSON decode of at most 1 MiB.
Measured below. Rejected:

- *A middleware before the routing.* It would have to verify the token itself, a second path through the security code of
  `core/auth.py`, to know the caller; the dependency reuses the one sign-in (FastAPI caches it within the request).
- *The check inside each route.* A route that forgets it would be unlimited, and its body would be validated first.

**Per replica, not shared.** Each API pod keeps its buckets in memory, as the module said since docs/02, Envoy's local rate
limit does, and Kubernetes's own limits are per API server. With N pods behind the front door, a caller reaches about N times
a limit: docs/18 says so, and to set the values for the replica count. Shared buckets in PostgreSQL would cost a round trip
on every call, the refused ones too, and put the flood on the database it protects; a store such as Redis is a new
dependency that cmapi does not run. Envoy's own docs pair a global limit with a local one to spare the global service. A
restart starts the buckets full. The memory is bounded: past 10,000 buckets the least recently used
one is dropped, as nginx's `limit_req_zone` does (the #695 review: before it, only the buckets that had refilled were dropped,
so every bucket that had not was kept).

**The configuration.** instance.yaml `http.rateLimits`, beside `http.maxRequestBodyBytes`, both API4 controls: `{class:
{perMinute, burst}}`, each optional over the defaults. A wrong class or field, a `perMinute` that is not a number more than 0,
or a `burst` that is not a whole number from 1, stops the start, with the same 2^53 − 1 maximum as the body limit. The chart
passes `instance.http` through and its schema refuses the same values. No switch turns the limits off: a site raises them.
`core/ratelimit.py` stays standard library only, so the config still loads without structlog (#693;
`test_config_import_693.py` now imports it too).

**The defaults.** read 120 a minute and 60 at once, place 10 and 5, suggest 240 and 40, export 4 and 2, team 600 and 200:
the values the module had since docs/02. write is new: 60 and 30. They are not measured against production traffic; the
metric below shows whether a site meets them.

**The answer.** 429 `rate-limited` as `application/problem+json`, with `Retry-After` in whole seconds and `retryAfter` with
the same number: the wait until the bucket holds a token, at least 1. A refused call takes no token. The detail names the
class, or the team. RFC 6585 forbids a cache to store a 429; the front door already adds `Cache-Control: no-store` to an API
answer that has none, `always`, and retries a pod only on an error, a timeout, 502, 503 or 504
(`cmapi-portal-ui/nginx/cmapi/proxy-api.conf`, `proxy.conf`). `problem_response` now sends `Retry-After` for every problem
with `retryAfter`: the 429, and the 503s `idp-unavailable`, `cluster-unreachable` and `validator-unavailable`, which docs/02
says have "Retry-After set" (#694). The document declares the header on each such response.

**No RateLimit header fields.** The draft is a work in progress that its own text says not to cite as reference material,
and its section 9.2 warns about disclosing capacity. `Retry-After` is the standard. Revisit when it is an RFC.

**Metrics and logs.** `cmapi_rate_limited_total{limit}` counts each refusal by class, never by caller (docs/01: no metric
label counts people). The log line `rate_limited` (warning) names the class, the caller's `sub`, the client, the team and the
wait, once for each run of refusals of a bucket, so a client that keeps retrying does not flood the log. The access log line
`http` already has each 429 with the caller's `sub`.

**The front door's `limit_req`: not added.** It keys on the client address. Behind the OpenShift router the front door sees
the router's address for every caller, and the template sets no `set_real_ip_from`, so one zone would be one bucket for
everyone, which lets one client stop all. Its default answer is 503, not 429, and its zones are per nginx pod unless the
commercial `sync`. docs/18 names it as an option for a site whose front door sees client addresses.

**docs/02 disagreed with itself.** Its "Missing pieces" row said "Per caller and per cluster token buckets"; docs/01 and
docs/02's own module table say per caller and per team. Built as docs/01 says, and the row corrected.

## Proof

`cmapi/tests/service/test_rate_limits_689.py` (19 tests) and `cmapi/tests/core/test_ratelimit_689.py` (16), with a clock
that the test moves; no test sleeps. The suite's other worlds get limits that no test meets (`conftest.py`, `UNLIMITED`):
one test sends hundreds of calls a second as one person.

- **Before**, `cmapi/src` stashed, on main `cf1c0f4`: the service file run with two stand-ins for what main does not have
  (`rate_class` and the counter), and main's `RateLimiter` put on the context (`outputs/before-service.txt`): 17 failed,
  2 passed. The two that pass: `rate_class` (the stand-in is the fix's copy) and the Idempotency-Key replay (a guard: a replay
  was 202 before and must stay 202). The core file cannot import (`parse_rate_limits`, `SWEEP_AT`), and the reference test
  `test_rate_limits` fails on the new interface (`outputs/before-core.txt`).
- **After**, service-suite world on this Mac (PostgreSQL 16, database `cmapi_impl_689`): 31 related files, the new one with the
  contract, standard, samples, docs, auth, CORS, authz review, body limit, problem, chart and flow suites
  (`outputs/related-suites.txt`): 846 passed, 1 failed. The one was `test_doc_citations.py`, run before the citations were
  moved; after `--relocate`, a read of each new target against its sentence, four citations corrected by hand (docs/14:131
  and :179, docs/16:247) and `--write`, it passes, with the new file again (`outputs/measure-429.txt`: 13 passed).
  `test_api_standard.py` gained `"429": ["rate-limited"]` in `CREATE_ANSWERS`, with its reason.
- **The reference suite** as CI runs it, `tests/core` in a venv built from `examples/local/requirements.txt`
  (`outputs/reference-suite.txt`): 770 passed, 113 skipped. `test_config_import_693.py` imports `core/ratelimit.py` with
  structlog and prometheus_client made unimportable.
- **The cost of a refusal**, measured (`outputs/measure-429.txt`, the probe in `probes/`): #683's 769,136-byte dry run of
  60,000 unknown members, 7 runs each, as one caller: 422 under the limit median 0.355 s, 429 over it median 0.030 s.
  `json.loads` of that body alone: median 0.029 s. So the 429 costs the decode that FastAPI does before any dependency, and
  none of the validation.
- **The contract** (`outputs/contract-checks.txt`): `openapi.json` gains 429 `rate-limited`, its required `Retry-After` header
  and `x-cmapi-rate-limit` on each of the 39 operations that take a token, and `Retry-After` on their 503s. oasdiff 1.37.0
  against main: "No breaking changes to report"; its changelog, 78 changes, 39 `response-non-success-status-added` and 39
  `response-header-added`, each level 1 (info). `lint-test.py` (37 cases), `lint.sh` (Spectral), `gate-test.sh`,
  `changelog.py --check`, `api-examples-doc.py --check` and `doc-citations.py --check` pass. `samples.json` is not recorded
  again: no operation was added. The portal's `schema.generated.ts` is written again.

Not tested: CRC and kind (no cluster was used); `:place`, which is not built (its class and its placement cap are unit-tested
only); a load test with several API pods.

## Review and the coordinator's rulings (2026-11-25)

**Reviewers.** Two, because this is security.
- **Reviewer 1** was Codex, gpt-6.2-astra xhigh (`review/reviewer-1-codex.md`, with its brief). Its sandbox could not reach PostgreSQL, so its service runs used SQLite.
- **Reviewer 2** was Opus 5.5 high, and ran everything on PostgreSQL 16 (`review/reviewer-2-opus.md`).

| Codex finding | Ruling | Reason |
|---|---|---|
| 1. The bucket store has no bound (High) | **Fixed, as amended by reviewer 2 (Medium)** | Codex's cap failed closed: with 10,000 buckets that were not full, every new caller got 429, a lockout an attacker can renew. The fix is least-recently-used eviction at 10,000, as nginx `limit_req_zone` ("the least recently used state is removed") and Envoy's local rate limit LRU do. Eviction gives a victim a fresh, full bucket, never a smaller one. |
| 2. Private docs take no token (Medium) | **Fixed** | `/openapi.json` (877 KB) was served with no limit when `docs.public: false`. |
| 3. A team transfer charges the wrong team (Medium) | **Rejected** | The team charged is the request's team, `facts["team"]`, the team after the change. The row stores it, and the auto-approvals of the day and the KPIs count it (`pipeline.py:553`). That matches docs/02 "per team". A transfer already needs approver-platform. Charging both teams would charge one pull request twice. The guard test pins today's behaviour. |
| 4. The team token is lost on a failed submit or a race (Medium) | **Fixed, as amended by reviewer 2 (Low)** | `RateLimiter.give_back`, the same as x/time/rate `Reservation.CancelAt`, inside a `team_request` context around the transaction, plus a replay on a team 429. Codex's version held a process-wide lock across the transaction, and on PostgreSQL it gave 500s under 8 concurrent creates. |
| 5. An expired-key UPDATE (Low) | **Rejected** | This is #603's design, unchanged here. Noted in #697. |
| 6. `OverflowError` for a rate near 0 (Low) | **Fixed, as amended** | The wait is clamped at 2^53−1. Codex's `Fraction` version returned a `retryAfter` with 326 digits. |
| 7. The loader and the schema disagree (Low) | **Rejected for this PR** | It follows #683's `parse_http`. The `1.0` and `1e-7` corners are in #697. |
| 8. An empty placement set is kept (Low) | **Fixed** | |

- **Found by reviewer 2, older than this PR:** **#696, pool starvation** (Medium). It gets its own pull request next, with reviewer 2's patch.
- **Concurrency proof on PostgreSQL:** 8 creates at once, with failures after the INSERT. The tokens left equalled the burst minus the rows recorded in 5 of 5 runs. Head failed it.
- **The coordinator's run** on `0ff3ea8`, database `cmapi_coord_695`: **3048 service passed**, none failed. The reference suite (`tests/core` in the venv built from `examples/local/requirements.txt`): **775 passed, 113 skipped** (`coord-suite.txt`).
