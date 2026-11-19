# #417: remove the unreachable cluster status

**Decision:** remove `environment-not-served` from the cluster `STATUSES`. The metric loop iterates that tuple, so it also stops emitting the dead label. Keep the HTTP 422 problem code, its handlers, OpenAPI examples and portal scenarios.

The import contract says: **“Connection comes from the import; policy comes from the configuration.”** An import supplies `apiUrl`, `token`, `caData`, `tlsServerName` and `insecure`, not a policy environment. `ClusterState.environment` uses its `ClusterPolicy`; `_check` also uses that policy for TLS permission. `_secret` can decode arbitrary keys, but `_check` never consumes a Secret's `environment` key.

`load_policies` rejects an environment outside `allowed_environments` with `ValueError`. `build_context` calls it before constructing the import source and registry. There is therefore no reachable import refusal to label with this status. An import without a policy can connect and stays read-only (`writable` returns 422 `cluster-not-writable`). The baseline remains responsible for putting an import on the right hub.

**Rejected alternative:** adding a setter would require accepting environment policy from a Secret or allowing an invalid policy past startup. Either would change the documented contract and existing behavior without a requirement to do so. No such change is needed for this issue.

## Claim evidence

Baseline: `main` / `4419a7f2472ec8d3877b2819147ed7893d0608f7`, equal to initial HEAD.

1. **CONFIRMED — READ FROM CODE.** `git grep -n -E 'STATUSES|not_connected|environment-not-served|self\._set\(' main -- cmapi/src/cmapi/core/registry.py` finds the status only in the tuple at line 53. Reading every call at lines 309, 324, 325, 330, 331, 460 and 469, including the complete `_probe` feeding line 330, finds no producer for it. `not-imported` comes from initialization or Secret retirement. The new test exercises each of the other nine statuses.
2. **REFUTED — READ FROM CODE.** `sed -n '267,309p' cmapi/src/cmapi/core/registry.py` shows `env = st.policy.environment if st.policy else None`. `sed -n '685p' docs/02-technical-design-v2.md` names only the five connection fields above. A Secret cannot provide an authoritative environment. Tests cover both a registered import and an import without policy.
3. **NOT REACHED — MEASURED.** `curl --silent --show-error --connect-timeout 5 --max-time 10 -i https://cmapi.apps-crc.testing/api/v1/clusters` returned exit 7: `Failed to connect to cmapi.apps-crc.testing port 443`. No HTTP response or live cluster statuses were observed. The coordinator must perform an authenticated GET with approved access.

The consumer audit covers `cmapi/src`, `cmapi-portal-ui/src`, `cmapi/contract/openapi.json` and docs. `not_connected` is generic; remaining portal and OpenAPI occurrences describe HTTP 422. Historical review excerpts remain historical. `examples/src/cmapi` links to the runtime package. Corrected docs/01's import refusal promise and docs/02's import and diagnostics descriptions; docs/18 now states explicitly that policy validation precedes imports.

## Validation

Using the existing `/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python`, with `PYTHONPATH=src:tests/service` in `cmapi/`:

- Before removal: new test with `-q -W ignore -x`: **1 failed in 0.40s**, specifically the extra `environment-not-served` in `STATUSES`.
- After removal: new test plus `test_registry_survives_419.py`: **29 passed in 0.56s**, no skips. Includes exact metric labels, unchanged policy rejection, read-only imports and the HTTP 422 problem code and routing URLs.
- Full requested three-file command: **13 failed, 51 passed in 2.09s**. Every failure is in `test_cluster_trust_434.py` at localhost `socket.bind`: `PermissionError: [Errno 1] Operation not permitted`. Coordinator rerun required with socket permission; no tests were weakened or skipped.
- `python3 scripts/doc-citations.py --check`: **doc-citations: 0 problems**. `git diff --check`: clean.

Full commands, outputs and failing node IDs are retained in the coordinator job folder `mayday/i417-r1/tests.md` and `logs/`; claim evidence is in `research.md` and `verdicts.md`. No browser, credentials, `.env`, installation, lockfile change or push was used.
