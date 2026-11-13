# Spike #187: the Git and cluster fakes against the providers' documents

The question of #187: do the fakes of the service suite answer as GitHub and Kubernetes answer, and what plan checks them against the providers' own documents? OB1 (Fable 5.2) did this spike on 2026-11-13, in one session. No code of the service changed.

## The decision

1. **Keep `FakeGit` and `FakeKube`.** They implement cmapi's own ports (`HostGitProvider`, `KubeClient`) in memory. They prove the logic above the port, and they are fast. They cannot prove an adapter, and no change to them can.
2. **Check each adapter against the provider's published description, with no server.** This is the plan for now: task #200. The spike measured it (below): each call of the two adapters, 0 differences, under 1 second, no container.
3. **Do not build a mock server now.** A mock from the description gives the paths and the fields, which the contract test already holds. It does not give the meaning: a pull request that is not mergeable, a status that changes later, a conflict of a server-side apply. Those need the real server.
4. **For the meaning, use the real thing where it is free.** For GitHub: the first real run on `cluster-configs-nonprod` (#61) records each answer, and the suite replays them. For Kubernetes: a real API server with no nodes, in GitHub's CI. `envtest` and `kwok` (binary runtime) both run binaries, with no container engine. Not tried on this Mac (#157 is open, and a download of a binary was refused here before).

## What was measured

The descriptions were read on 2026-11-13. They are not in this repository (14.3 MB and 3.8 MB). Task #200 keeps a small extract of each.

| Provider | Description | Calls of the adapter | Distinct operations | Differences | Time |
|---|---|---|---|---|---|
| GitHub | `github/rest-api-description` at `53fd7d2`, `descriptions/api.github.com/api.github.com.json`, OpenAPI 3.0.3, version 1.1.4, 842 paths | 23, in `core/git/github.py` at `a29e683` | 22 | 0 | 0.47 s |
| Kubernetes | `kubernetes/kubernetes` at tag `v1.35.0`, `api/openapi-spec/swagger.json`, Swagger 2.0, 537 paths | 48, in `core/clients/kube.py` at `a29e683`: list, watch, get, apply and delete for 8 kinds, `/version`, the SelfSubjectReview | 40 | 0 | 0.16 s |

What each comparison checks, for each call: the path and the method exist; each query parameter is declared; each body field is in the request schema, and each required field is sent; the content type of an apply is accepted; each status that the adapter names is documented; each answer field that the adapter reads is in the answer schema (GitHub only). The scripts are `github_calls.py` and `kube_calls.py` in this folder, and their outputs are `github-calls.txt` and `kube-calls.txt`.

Each comparison can fail. A copy of each script with three wrong values found them: 5 differences for GitHub (a wrong answer field, a wrong body field and its missing required field, a wrong status, a wrong query parameter) and 24 for Kubernetes (a wrong query parameter, content type and status, for each of 8 kinds).

Not covered by a description: OpenShift's `GET /apis/user.openshift.io/v1/users/~` (it is not in the Kubernetes description), and the meaning of each answer.

## What the comparison did not see, and reading found

GitHub's text for `GET /repos/{owner}/{repo}/compare/{basehead}`: "The list of changed files is only shown on the first page of results, and it includes up to 300 changed files for the entire comparison." `GitHubProvider.changed_paths` reads that list as complete. This is #199 (BUG-52). The shape of the call is right, so no schema check finds it: the limit is in the text.

`github-calls.txt` also lists, for each call, the documented statuses that the adapter does not name. They reach the adapter's general error path. None is a defect by itself. Task #200 reads them again with the recorded answers of #61.

## The options, with the measurement that #187 asked for

| Option | Operations covered | Runs with no container | Time added to the suite | Kept or not |
|---|---|---|---|---|
| A contract test of the adapter's requests and the test answers against the description, with no server | 22 of 22 (GitHub), 40 of 41 (Kubernetes; not `users/~`) | Yes | Under 1 s (measured: 0.63 s for both) | **Kept**: #200 |
| A mock of GitHub made from the description (Prism, or a mock in Python) | The same 22 | Prism: yes, it is a Node CLI (Node.js 18.20.1 or later). In Python: yes | Not measured | Not now. It adds a server and no check that the contract test does not have. Prism's validation proxy is useful with a real upstream, which #61 gives |
| A real Kubernetes API server with no nodes (`envtest`: kube-apiserver and etcd binaries; `kwok` with its binary runtime) | Each call, with its meaning | Yes: binaries, no container engine. `envtest` has limits: "no built-in controllers run", and "EnvTest does not support namespace deletion" | Not measured: not tried on this Mac | Later, in GitHub's CI: it is the only option that proves server-side apply and a 409 |
| Recorded answers from one real run against GitHub (#61), replayed | The operations of that run | Yes, after the run | Small | Kept, with #61 |

## A plan for a mock app (`/mock-app`)

The `/mock-app` skill of diagram-kit plans a mock for a provider that has no sandbox. GitHub has the real thing for free: a test repository (`cluster-configs-nonprod`, #61). Kubernetes has `envtest` and `kwok`. So cmapi needs no mock app for these two providers today. If #61 shows that a test repository is not enough (rate limits, or a state that a test cannot make, for example a merge that GitHub refuses with 405), the plan is:

1. A mock in Python, the language of the service, on `httpx.MockTransport`, as `test_github_check_runs.py` has it today. It needs no port and no process.
2. Its answers come from the recorded run of #61, and the contract test of #200 holds each one to the description.
3. Scenarios: each status in `github-calls.txt` that the adapter does not name, a `Link` header with a next page, a secondary rate limit (403 with `retry-after`), and a merge that is refused.
4. Authentication: the mock refuses a request with no `Authorization: Bearer` header with 401, as GitHub documents. Test values only.

## Sources

Each was read on 2026-11-13.

- GitHub's REST API description: <https://github.com/github/rest-api-description>. "Each OpenAPI document is available in two formats: bundled and dereferenced." "As of the 1.1.4 release, this description is considered stable and generally available." MIT licence. The 3.1 description "is subject to breaking changes on the main branch", so the spike used 3.0.
- The Kubernetes API description: <https://github.com/kubernetes/kubernetes/blob/v1.35.0/api/openapi-spec/swagger.json>.
- envtest: <https://book.kubebuilder.io/reference/envtest.html>. It starts "an instance of etcd and the Kubernetes API server", "without kubelet, controller-manager or other components".
- KWOK: <https://kwok.sigs.k8s.io/>. Its support table has a binary runtime, tested on linux/amd64, darwin/amd64 and darwin/arm64.
- Prism: <https://github.com/stoplightio/prism>. A mock server and a validation proxy for "OpenAPI v3.1, OpenAPI v3.0, OpenAPI v2.0 (formerly Swagger) and Postman Collections".
- openapi-core, a Python library for "Validation and Unmarshalling of request and response data", BSD 3-Clause: <https://openapi-core.readthedocs.io/en/latest/>. Task #200 chooses between it and the small checks of this spike.
- diagram-kit's skill `/mock-app` (`skill/mock-app/SKILL.md`), read in full. `skill/app-architect/CONTRACTS.md`, which #187 names, is not in the local diagram-kit checkout (it is in diagram-kit PR 64, not merged), so it was not read.

## The issues that build it

- #200: the contract test of the two adapters in the service suite, with a pinned extract of each description and a check for drift.
- #199 (BUG-52): the 300 files of a comparison.
- #61 (open before this spike): the first real run against GitHub. It records the answers that the suite replays.

## Not done

No request went to GitHub or to a cluster. No tool was installed. `envtest`, `kwok` and Prism were read about and not run.
