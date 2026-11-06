# Adversarial review of PR #89 at `d6c063e`, reviewer 2 (Opus 5.5)

Every source I cite is under `logs/sources/`; every run is under `logs/`. "Measured" means I ran it, "read" means a primary source or
the code, "inferred" means neither.

The most important result: **Codex's restore fix (finding 5) would have made a documented target impossible.** On PostgreSQL 16,
which `docs/12:14` lists, `pg_restore --single-transaction` fails before the first object every time. The shipped command is broken
on 16 too, in a different way, and Codex did not run a database. Both are fixed by patch 05, and that fix is proven on real 16 and 17.

## Job 1: Codex's six findings

| # | Finding | Verdict | Codex's severity | Final | Why, with the source |
|---|---|---|---|---|---|
| 1 | render-atomic | **AMEND** | Medium | Low | Reproduced. Its `mktemp -d` stage becomes the out dir, so the render goes from mode 755 to **700** (measured, `logs/attack-render-codex.txt`). The tree is derived and the failed run exits non-zero, so nothing is lost that a re-render cannot restore |
| 2 | secrets-preflight | **ACCEPT the code, AMEND the tests** | Medium | Low | Reproduced. The code holds rulings 2 and 6, and cases 2g and 5a. Its cases only prove the App Secret's check: a write put back ahead of the keys, LDAP or key-file check survives them. Severity: the next run reads the same values (`secrets-test.sh` 5a, 5b), so nothing diverges |
| 3 | router selector | **ACCEPT the selector, AMEND the test** | Medium | Low | Not broken on CRC (the coordinator's measurement) or on any cluster I could read: the ingress operator writes both labels on purpose (`ingress-namespace.yaml`: "old and new forms"). The documented label is the right single selector; a peer adds no cluster and some reach |
| 4 | kind partial cleanup | **AMEND** | Medium | Low | The premise is narrower than claimed: kind deletes what it made on a failed step itself (`create.go`, v0.33.0). And the fix **deletes another run's cluster** in the race the brief asked about (measured) |
| 5 | doc12 restore | **AMEND: diagnosis right, fix replaced** | Medium | Medium | Measured on real PostgreSQL: the partial target is real, but `--single-transaction` on a 16 target restores nothing, ever |
| 6 | image guard | **AMEND** | High | Low | The mutant survives (reproduced), but this is a guard against a mistake, not a boundary: whoever can edit the manifests can edit the guard in the same pull request, and review is what stops them. The count is right; the Python guard misses other kinds and `.yml` |

## Why each was amended

### Finding 1, render-atomic

Reproduced on `d6c063e`: a failed render deletes the last good tree (`logs/attack-render-codex.txt`, section 6).

The guards hold in Codex's patch: refusal of a foreign directory, the marker, and the check runs before anything is touched. The temp
is removed on every path I attacked, and the EXIT trap ran on a SIGTERM (rc 143, last good tree intact). What had to change:

- **Mode.** `mktemp -d` makes 0700, and Codex renames that directory into place. Measured with umask 022: `first render: 700`, against
  755 at `d6c063e`. That is a behaviour change the fix did not claim, and it breaks any reader under another user or in a container. The
  amended fix makes a `mkdir` tree inside the temp directory, so the mode is the umask's again (755, measured on BSD and GNU).
- **Simpler.** One working directory holds `new` and `old`, so there is no `mktemp; rmdir; mv` of a name, and one `cleanup`.
- **A failed put-back says where the data is.** Codex's `mv "$OLD" "$OUT" || true` leaves it in a hidden directory without a word. Mine prints
  the path and exits without removing it.
- **`link/`.** `mv` on a trailing-slash symlink moves what it points at. `OUT=${OUT%/}` makes it the link, as without the slash. This
  also fixes new finding N9.

Codex's refusal of a dangling symlink is kept: it is a small change, it matches "deletes only what it wrote", and the rename would
otherwise fail after the render.

Severity: Low. `deploy/rendered/` is derived from the tree, the failed run exits non-zero, and no release script consumes it yet.

BSD and GNU: `deploy/render-test.sh` passes on macOS and on Debian 11's GNU coreutils 8.32, sed 4.7 and bash 5.1 (`logs/01-gnu-render-test.txt`).

### Finding 2, secrets-preflight

Reproduced: three Secrets written before an empty `cmapi-github-app` stops the run.

Checked against the brief:

- **Stale read (2g) and create-not-apply:** both pass. Every write is still `create`, so a Secret that appears in the wider window stops
  the run with `AlreadyExists` rather than being overwritten. Mutant Q still dies.
- **The realm verdict:** cases 2c to 8a pass unchanged. `realm_import_exists` stays in the `generate` branch, ahead of its first write.
- **Rulings 2 and 6:** 7a passes, and 10c passes on the exact `ERROR:` line.
- **Mutants:** the 17 existing ones all die. **Codex's own cases only cover the App Secret**, so I added 0c to 0f (partial keys, missing
  bind user, a readable key file, a key file with no ids) and mutants R to V, which put a write back ahead of each check. All 22 die
  (`logs/02-mutants.txt`). Each new case is the one that kills its mutant, so they are not redundant.

The code is Codex's, unchanged. Patch 02 applies its `secrets.sh` hunks as written and replaces its test hunk.

Severity: Low. Nothing diverges: the values a stopped run wrote are the ones the next run keeps.

### Finding 3, the router selector

**The decision: the documented label as the single selector. Not both.**

| Choice | Breaks on | Reach added |
|---|---|---|
| As shipped, `network.openshift.io/policy-group: ingress` | Nothing measured or read today; a future operator that drops the label the docs call legacy | None |
| **Documented, `policy-group.network.openshift.io/ingress: ""`** | A cluster whose `openshift-ingress` lacks it. None I could read: CRC (measured), `release-4.16`, `release-4.20`, `master` (read) | None |
| Both as peers | Nothing | Any namespace carrying only the legacy label, for no cluster gained |

Sources, all read: `openshift-docs` main says the new label is "the preferred namespace selector label for OVN-Kubernetes"; its
`enterprise-4.12` and `4.16` branches call the old one "a legacy label"; the operator's `namespace.yaml` writes both with the comment
"old and new forms of the label". Requests for `release-4.12` and earlier returned no such lines, and I do not take that as evidence:
the path may differ there. docs.redhat.com returned 403 to every fetch here, so I read the same text from the docs' source repository.

So Codex's "a cluster carrying only the documented OVN label" is not a cluster I can find, and neither is its inverse. That is why this
is Low: it aligns with the documented contract, and nothing is broken today. I accept the change because the old form is named legacy.

**A limit no label choice fixes (inferred, not measured).** The operator's comment says `HostNetwork` is the default publishing strategy
on on-premise platforms, and a host-network router is not a pod of that namespace. CRC has one node, and Kubernetes says traffic from a
pod's own node is always allowed, so I expect the Route to work there whichever label is used. On a multi-node cluster with that strategy,
a router on another node would need a peer for `policy-group.network.openshift.io/host-network`. I did not add one: CRC does not need it,
and it would open 8080 to every host-network pod. The comment in the manifest records this. To settle it for CRC, read-only:
`oc get ingresscontroller default -n openshift-ingress-operator -o jsonpath='{.status.endpointPublishingStrategy.type}'`. The Route
screenshot in the first CRC walk is the proof.

The chart keeps the old label (`deploy/helm/cmapi/templates/monitoring.yaml:25`). It leaves in Wave 4, so I left it.

Amended test: see new finding N4.

### Finding 4, kind partial cleanup

Reproduced on stubs. Attacks on Codex's fix:

- **The race is real.** Both runs pass `kind get clusters`, the second's `kind create` fails with `node(s) already exist`, `created` is
  already true, and `finish` runs `kind delete cluster --name cmapi-test` on the winner's cluster. Measured with Codex's script under the
  final harness: `WRONG the other run's cluster is not deleted: expected no, got yes`. `CLAUDE.md` forbids deleting what you did not create.
  Codex's stub could not show this: it removed the `create` failure that signals a taken name.
- **`kind get clusters` failing:** safe in Codex's and in mine. The assignment stops the run before `created` is set.
- **The name exists:** safe in both.
- **The premise.** `create.go` v0.33.0 deletes the nodes itself when `Provision` or any action fails. What is left for this code is an
  interrupt, or the final kubeconfig export failing. Also `--wait` timing out returns 0 (`waitforready.go:90-91`), which is not this bug:
  the operator's rollout then fails. So Low: at worst a leftover throwaway cluster, and the next run refuses the name.

The amended fix keeps ownership from before the call, as Codex did, and hands it back when kind's own message says the name was taken.
It also replaces `printf | grep -Fxq` under `if` with a `case`: that shape is what the script's line 69 comment warns about. A residual
I cannot close: two runs inside kind's own check-then-provision window can collide inside kind, and the loser's kind may delete nodes by
name. That is upstream behaviour and needs two runs in the same seconds.

### Finding 5, doc12 restore

The diagnosis holds, now measured rather than inferred. As shipped, with `request_events` already on the target: `rc=1`, `errors ignored
on restore: 7`, `tables=10 rows=7`. So a real failure leaves a mixture **in which the two row counts match** (`logs/doc12-real-restore-1.txt`).

Codex's fix, on real PostgreSQL, restoring cmapi's real migrated schema and a dump from the CNPG image's `pg_dump` 17.11:

| Target | Command | Result |
|---|---|---|
| 17.11 | Codex's | rc 0, 10 tables, 7 rows: correct |
| **16.15** | **Codex's** | **rc 1, `unrecognized configuration parameter "transaction_timeout"`, 0 tables, every time** |
| 16.15 | As shipped | rc 1, `errors ignored on restore: 1`, 10 tables, 7 rows: complete, but `set -e` stops the block (N1) |

The cause is in `pg_backup_archiver.c` on `REL_17_STABLE`, line 3298: pg_restore 17 emits `SET transaction_timeout = 0` unconditionally.
`--single-transaction` implies `--exit-on-error`, so it is fatal, before `BEGIN`.

The replacement: `pg_restore -f -`, an `awk` that removes the first exact match of that line (first only, so a table row with the same
text survives), then `psql -v ON_ERROR_STOP=1 --single-transaction`, under `pipefail`. Section 5's block itself, run on real servers:

| Target | Case | rc | Tables | Rows |
|---|---|---|---|---|
| 16.15 | clean | 0 | 10 | 7 |
| 16.15 | failure on the last table | 3 | only the one that was already there | none |
| 17.11 | clean | 0 | 10 | 7 |
| 17.11 | failure on the last table | 3 | only the one that was already there | none |

`alembic_version` reads `0003` and `cmapi` owns the tables, so `--role` and `--no-owner` work (`logs/05-final-block-real-postgres.txt`).
`--role=cmapi` connected as `cmapi` works: it is a `SET ROLE` to itself.

### Finding 6, the image guard

**Severity: Low, not High.** Codex's mutant does survive. But the guard does not protect from a person: anyone who can edit the manifests does
so in a pull request, can edit `render-test.sh` and the service test in the same diff, and is stopped only by review. So the guard catches
mistakes: a digest pinned while debugging, a tag left behind. The Python docstring now says that.

**The count.** `grep -r` finds exactly 4 in `components` and `environments/kind`, so `[ "$n" = 4 ]` holds. It touches only the test: `render.sh`, `--allow-tag`
and `environments/` are unaffected, and the mockup and database images still pass (measured). The realm-sync Job that D4 puts in
`components/cmapi/` will need this number changed; I added a comment saying a new one is a decision.

**What I changed**, because Codex's guard still lets through (measured, `logs/06-codex-guard-gaps.txt`):

- A `Job` with `image: ghcr.io/evil/x:latest`: it looks only at Deployments.
- The same in a `.yml` file: `docs()` reads `*.yaml`, while `kubectl apply -R` and Argo CD take both.
- `ghcr.io/evil/x@sha256:<64 hex>` on the mockup: it passes the Python guard, where any repository does. `render-test.sh:22` happens to catch this one, because it greps for the nginx name.

The amended guard walks every `image` and `imageName` of every object, and allows other images by repository. `test_the_image_guard_can_fail` proves it can
fail, in seven cases, in CI, rather than in a script outside the repository. Codex's mutant script stays out of the repo for that reason.

## Job 2: what Codex missed

| # | Severity | Where | The failure | Evidence |
|---|---|---|---|---|
| N1 | **Medium** | `docs/12:103`, `:14` | On a PostgreSQL 16 target, which section 1 lists, the shipped restore completes, exits 1 on `transaction_timeout`, and `set -eu` stops the block before the counts. An operator sees a failure, and a re-run hits duplicates | Measured: `logs/05-shipped-block-real-postgres.txt`. Fixed in patch 05 |
| N2 | **Medium** | `docs/12:95-97` | `oc scale` returns at once, and the worker has 60 s of grace (`30-worker.yaml`), so `pg_dump` can snapshot while it still writes. Where Argo CD syncs cmapi, self-heal restores `replicas: 1` (measured 40 s on an image, D3), so the workloads return during the dump. Updates do not change a row count, and the counts are only printed. The next step destroys the source | No wait in the block: read. Self-heal on replicas: **inferred** from D3; no Argo CD deploys cmapi yet. The new checks: run on stubs. `kubectl wait --for=delete` with no pods returning 0: read (`kubectl-wait.go:370-380`). Patch 05 |
| N3 | Low | `kind-test.sh:24` | `finish` runs `rm -f "$KC"`. With `KIND_TEST_KUBECONFIG=~/.kube/config`, the variable the header documents, a passing test deletes that whole file, CRC's context included | Measured on stubs: `WRONG: a kubeconfig this run did not create was deleted` before, none after. Patch 04 |
| N4 | Low | `test_plain_manifests.py:57-58` | `test_api_port_is_not_open_to_every_namespace` passes with `- namespaceSelector: {}` added, which opens 8080 to every namespace: `{}` is already in its list | Measured: mutant passes at `d6c063e`, fails after. Patch 03 |
| N5 | Low | `test_plain_manifests.py:19,100-104` | The image guard reads only Deployments in `*.yaml` | Measured: a `.yml` Job on `:latest` passes before, fails after. Patch 06 |
| N6 | Low | `render-test.sh:18-21,35` | Four render mutants survive: the database dropped from the render, a file dropped from the rendered environment, another GHCR repository accepted, a short digest accepted. `grep '^[<>]'` cannot see `Only in` lines | Measured: `logs/proof/07-*`. Patch 07 |
| N7 | Low | `docs/12:65` | `psql "$(cat /run/db/uri)"` puts the password on psql's argument list in the pod. `CLAUDE.md` forbids it, and `docs/12:47-48` promises otherwise. No privilege is gained: whoever can read that process can read the Secret | Read. The fix is measured against a real scram server, with a password holding `@ % / : # & ?`, and a wrong one refused. Patch 08 |
| N8 | Low | `manifests/README.md:31` | "apply both the environment and the components" gives no order. Components first: pods restart on the old ConfigMap, carrying the new checksum, and nothing restarts them again | **Inferred** from how `envFrom` works; `kind-test.sh:139-140` has the right order. Argo CD's waves also have it right. Patch 08 |
| N9 | Low | `render.sh:49` | With `OUT=link/`, `rm -rf "$OUT"` empties what the link points at, then `mkdir` fails: rc 1 and the target render is gone | Measured: `logs/attack-render-codex.txt`, section 4. Patch 01 |

### Checked and found sound

- **`checksum/config`.** The pods read `cmapi-env`, `cmapi-config` and `cmapi-trust`, and all three are covered. The Secrets are read at start and not covered, but ruling 3 names
  three files, the script never rotates, and `docs/12:78-80` covers the database password. The policies are in the image. The mockup's ConfigMap is a volume the kubelet updates.
- **`secrets.sh` material.** No value reaches an argument list: `printf` is a builtin, documents go on stdin, and there is no temp file and no `set -x`. Values are in `OURS` and `THEIRS` in the
  environment of a child `python3`, readable by the same user, who can already read the kubeconfig. Tracebacks print no value.
- **Security context and RBAC.** They match the chart, and `restricted-v2`'s requirements as read. `readOnlyRootFilesystem` is false in the chart as well.
  The imports Role is the chart's. CNPG's 5432 and the mockup's 8080 are not selected by the policy, as in the chart.
- **`kind-test.sh`, other failures read as success.** Every check I traced stops under `set -e` or an explicit `exit 1`. Only the DNS path exits 0 having changed something, and it prints that it did; the brief puts that failure outside this review. After the second rollout there is no restart check, which is a coverage limit, not a false pass: the same test's first rollout has one.
- **`|| true`.** `secrets-test.sh:12` and `finish` only. `hs` reads a failed read as `none`, which would pass a negative check, but the same failure fails the positive cases around it.
- **docs/12 sections 2 and 3:** nothing else would destroy data or fail as written, as far as I could read or run.

## What I measured, inferred and did not test

**Measured here (macOS, Darwin 24.6):** every before and after below; section 5's block on PostgreSQL 16.15 and 17.11 with cmapi's real migrations; section 3 step 4 on a scram server;
the render attacks; `render-test.sh` on Debian's GNU userland.

**Inferred:** N2's self-heal on `replicas`, N8, and the host-network limit in finding 3.

**Not tested:**
- `kubeconform` (refused earlier on this PR, per the review README; I did not try it), `np-reach-test.sh`, and the real `deploy/kind-test.sh`. Nothing here ran on a cluster, and no kind cluster was created.
- `secrets-test.sh` on GNU userland: the Debian image has no PyYAML. CI covers it.
- TLS in section 5's restore: `sslmode=disable` there. Sections 2 and 3's TLS is in the record.
- A dump from a real CNPG **operator** cluster: mine came from the CNPG image's PostgreSQL, with no `ACL`, `EXTENSION` or `SCHEMA` entries. If a real one holds a `GRANT` to a role the target lacks, the restore now stops and leaves the target empty; that is loud, and `--no-privileges` would be the next step.
- Turning Argo CD's automated sync off around section 5.
- `test_plain_manifests.py` under the suite's conftest: I ran it with `--noconftest`, because the conftest defaults to port 55432, `cmapi-test-pg`, which this review must not touch. Job `service` runs it for real.

**Sources not reached:** docs.redhat.com answered 403, so Codex's 4.22 citation is unread by me. I read the same module's source in `openshift/openshift-docs`.

**A refusal, recorded.** Claude Code's safety check refused one setup command early on, because its `rm -rf` was inside a `bash -c` it could not inspect. The directories did not exist yet, so nothing was needed; I used new directory names from then on. No other command was refused. The command, with its long inline edit script elided:

```
bash -c 'S=<scratchpad>; R=$S/pr89-review2-opus/repo; O=$S/pr89-review2-opus/output; cd $O/work; rm -rf t prev; cp -pR $R t; cp -pR $R prev; python3 - <<PY ... PY; ...'
```

## Proof

All eight patches applied in order to a fresh copy of `repo/` with `patch -p1` (`logs/proof/apply.txt`): 8 of 8 returned 0, with no `.orig` or `.rej`, and the result equals the tree they were generated from. Before and after for each test, on that copy:

```text
01-before rc=1 render cases failed: 5
01-after rc=0 render cases failed: 0
02-before rc=1 secrets cases failed: 18
02-after rc=0 secrets cases failed: 0
03-before rc=1 1 failed, 12 deselected in 0.17s
03-after rc=0 1 passed, 12 deselected in 0.12s
04-before rc=1 wrong: 4
04-after rc=0 wrong: 0
05-before rc=1 doc cases failed: 9
05-after rc=0 doc cases failed: 0
06-before-pytest-on-mutant rc=0 1 passed, 12 deselected in 0.28s
06-before-render-test-on-mutant rc=0 render cases failed: 0
06-after-pytest-on-mutant rc=1 8 failed, 12 deselected in 1.95s
06-after-render-test-on-mutant rc=1 render cases failed: 1
06-after-clean rc=0 8 passed, 12 deselected in 1.83s
06-after-clean-render rc=0 render cases failed: 0
06-before-yml-job-mutant rc=0 1 passed, 12 deselected in 0.30s
06-after-yml-job-mutant rc=1 1 failed, 19 deselected in 0.30s
08-before rc=1 doc cases failed: 3
08-after rc=0 doc cases failed: 0
08-before-readme rc=1 1 failed, 20 deselected in 0.12s
08-after-readme rc=0 1 passed, 20 deselected in 0.07s
07, render mutants, before: 4 SURVIVED (logs/proof/07-before.txt)
07, render mutants, after:  4 killed (logs/proof/07-after.txt)
```

For 06, `before` is the old guard on a mutant (it passes, which is the finding) and `after` is the new one on the same mutant. `06-after-pytest-on-mutant` shows 8 failures because each of the seven can-fail cases first asserts the real manifests are clean.

The whole suite on the fully patched copy (`logs/proof/final-*.txt`):

```text
render-test        rc=0  render cases failed: 0
secrets-test       rc=0  secrets cases failed: 0
ci-guard           rc=0  ci cases failed: 0
doc12              rc=0  doc cases failed: 0
kind-stubbed       rc=0  wrong: 0
mutate-secrets     rc=0  mutants: 22, wrong: 0
mockup-check       rc=0  mockup ConfigMap is current
plain-manifests    rc=0  21 passed in 3.21s
shellcheck         rc=0  
```

For comparison, `logs/baseline-summary.txt` is the same suite on `d6c063e`: all green, 17 mutants, 13 manifest tests.

## The final code, every changed block

These are the patches themselves, complete and in order. Lines with `+` are as the code should read, in `final/`. Patch 02's `secrets.sh` hunks are Codex's, unchanged.

### 01-render-atomic.patch

````diff
--- a/deploy/render-test.sh
+++ b/deploy/render-test.sh
@@ -76,9 +76,31 @@
 # An image change alone restarts through the image, not through this value.
 "$R" kind "ghcr.io/ephico2real2/cmapi@sha256:$(printf 'd%.0s' {1..64})" "$W/s6" >/dev/null; want "another image keeps the value" "another image changed the checksum" [ "$(sums "$W/s6")" = "$A0" ]
 # A placeholder left fails the render, and a ConfigMap no file declares stops it before the last render is touched.
+"$R" kind "$GOOD" "$W/s7" >/dev/null; echo keep >"$W/s7/keep"
 printf 'x: CMAPI_CONFIG_CHECKSUM\n' >"$D/manifests/components/cmapi/97-odd.yml"
 if quiet "$R" kind "$GOOD" "$W/s7"; then bad "a checksum placeholder in a .yml passed"; else ok "a checksum placeholder the render cannot fill fails"; fi
 rm -f "$D/manifests/components/cmapi/97-odd.yml"
+want "a failed render leaves the last good one" "a failed render replaced the last good one" [ -e "$W/s7/keep" ]
+want "and its IMAGE" "a failed render removed IMAGE" [ -f "$W/s7/IMAGE" ]
+left=$(find "$W" -maxdepth 1 -name '.s7.*'); want "and nothing beside it" "a failed render left $left beside the out dir" [ -z "$left" ]
+# The swap itself failing puts the last good render back.
+REAL_MV=$(command -v mv); mkdir "$W/bin"
+cat >"$W/bin/mv" <<STUB
+#!/usr/bin/env bash
+case "\$1" in */new) echo "mv: refused by the test" >&2; exit 1;; esac
+exec "$REAL_MV" "\$@"
+STUB
+chmod +x "$W/bin/mv"
+"$R" kind "$GOOD" "$W/s9" >/dev/null; echo keep >"$W/s9/keep"
+if PATH="$W/bin:$PATH" quiet "$R" kind "$GOOD" "$W/s9"; then bad "a failed swap passed"; else want "a failed swap puts the last good render back" "a failed swap lost the last good render" [ -e "$W/s9/keep" ]; fi
+# The out dir is what mkdir makes, not mktemp's 0700: a render other users or a container read must stay readable.
+( umask 022; "$R" kind "$GOOD" "$W/s10" >/dev/null ); m=$(stat -c '%a' "$W/s10" 2>/dev/null || stat -f '%Lp' "$W/s10")
+want "the out dir has the umask's mode" "the out dir is mode $m, not 755" [ "$m" = 755 ]
+# A trailing slash, and "link/": the link is what is replaced, and what it pointed at stays.
+"$R" kind "$GOOD" "$W/s11/" >/dev/null; "$R" kind "$GOOD" "$W/s11/" >/dev/null; want "a trailing slash renders" "a trailing slash did not render" [ -f "$W/s11/IMAGE" ]
+"$R" kind "$GOOD" "$W/s12" >/dev/null; ln -s "$W/s12" "$W/s12link"
+want "a link/ to a render renders" "a link/ to a render failed" quiet "$R" kind "$GOOD" "$W/s12link/"
+want "and what it pointed at stays" "a link/ deleted what it pointed at" [ -f "$W/s12/IMAGE" ]
 for f in 10-env 20-config 30-trust; do
   mv "$D/manifests/environments/kind/$f.yaml" "$W/keep.yaml"
   if quiet "$R" kind "$GOOD" "$W/o2"; then bad "a render without $f passed"; else want "no $f stops the render and the last render stays" "the failure without $f deleted the last render" [ -e "$W/o2/keep" ]; fi
--- a/deploy/render.sh
+++ b/deploy/render.sh
@@ -6,7 +6,8 @@
 # process reads its configuration once, at start, so that checksum in the api's and the worker's pod templates is what makes
 # a changed ConfigMap restart them. The image must be by digest, from GHCR or CRC's internal registry (Wave 1); anything else
 # is accepted only with --allow-tag, for a locally built image, on environment kind only. The out dir is replaced whole, and
-# only when it is empty or an earlier render (the marker .cmapi-render). The last step fails if any placeholder is left.
+# only when it is empty or an earlier render (the marker .cmapi-render). It is built beside the out dir and renamed into place
+# only once every check has passed, so a failed render leaves the last good one untouched.
 set -euo pipefail
 ALLOW_TAG=false; ARGS=()
 for a in "$@"; do if [ "$a" = --allow-tag ]; then ALLOW_TAG=true; else ARGS+=("$a"); fi; done
@@ -42,19 +43,36 @@
 fi
 [ -d "$HERE/manifests/environments/$ENV_NAME" ] || { echo "ERROR: no environment $ENV_NAME under deploy/manifests/environments" >&2; exit 1; }
 CHECKSUM=$(config_checksum "$HERE/manifests/environments/$ENV_NAME")
-# It deletes what it replaces, so only what it wrote: a mistyped out dir must not take a directory with it.
-if [ -e "$OUT" ] && { [ ! -d "$OUT" ] || { [ -n "$(ls -A "$OUT")" ] && [ ! -e "$OUT/.cmapi-render" ]; }; }; then
+# It deletes what it replaces, so only what it wrote: a mistyped out dir must not take a directory with it. A dangling symlink
+# is refused too: it is not an empty place to write, and the rename below could not replace it.
+if { [ -e "$OUT" ] || [ -L "$OUT" ]; } && { [ ! -d "$OUT" ] || { [ -n "$(ls -A "$OUT")" ] && [ ! -e "$OUT/.cmapi-render" ]; }; }; then
   echo "ERROR: $OUT exists and is not an earlier render (no .cmapi-render); not replacing it" >&2; exit 1
 fi
-rm -rf "$OUT"; mkdir -p "$OUT"; : >"$OUT/.cmapi-render"
-cp -R "$HERE/manifests/components" "$OUT/components"
-cp -R "$HERE/manifests/environments/$ENV_NAME" "$OUT/environment"
+OUT=${OUT%/}   # mv on "link/" moves what the link points at, not the link
+OUT_PARENT=$(dirname "$OUT"); mkdir -p "$OUT_PARENT"
+# Beside the out dir: a rename is only a rename on one file system. mktemp's directory is 0700, so the tree is a mkdir inside it
+# and the out dir keeps the umask's mode.
+WORK=$(mktemp -d "$OUT_PARENT/.$(basename "$OUT").render.XXXXXX")
+# On every way out: the last good render back in place if the swap stopped half way, and the working directory gone.
+cleanup() {
+  rc=$?
+  if [ -e "$WORK/old" ] && [ ! -e "$OUT" ]; then
+    mv "$WORK/old" "$OUT" || { echo "ERROR: could not put the last render back; it is in $WORK/old" >&2; exit 1; }
+  fi
+  rm -rf "$WORK"; exit "$rc"
+}
+trap cleanup EXIT
+NEW=$WORK/new; mkdir "$NEW"; : >"$NEW/.cmapi-render"
+cp -R "$HERE/manifests/components" "$NEW/components"
+cp -R "$HERE/manifests/environments/$ENV_NAME" "$NEW/environment"
 # sed on YAML, on purpose: no templating language in the path. Each placeholder is a whole value.
-find "$OUT" -name '*.yaml' -print0 | while IFS= read -r -d '' f; do
+find "$NEW" -name '*.yaml' -print0 | while IFS= read -r -d '' f; do
   sed -i.bak -e "s|${PLACEHOLDER}|${IMAGE}|g" -e "s|${CHECKSUM_PLACEHOLDER}|${CHECKSUM}|g" "$f" && rm -f "$f.bak"
 done
-if grep -rnE "sha256:DIGEST|${CHECKSUM_PLACEHOLDER}" "$OUT" >/dev/null; then
-  echo "ERROR: a placeholder was not filled:" >&2; grep -rnE "sha256:DIGEST|${CHECKSUM_PLACEHOLDER}" "$OUT" >&2; exit 1
+if grep -rnE "sha256:DIGEST|${CHECKSUM_PLACEHOLDER}" "$NEW" >/dev/null; then
+  echo "ERROR: a placeholder was not filled:" >&2; grep -rnE "sha256:DIGEST|${CHECKSUM_PLACEHOLDER}" "$NEW" >&2; exit 1
 fi
-printf '%s\n' "$IMAGE" > "$OUT/IMAGE"
+printf '%s\n' "$IMAGE" > "$NEW/IMAGE"
+if [ -e "$OUT" ]; then mv "$OUT" "$WORK/old"; fi
+mv "$NEW" "$OUT"
 echo "rendered: ${OUT} for ${ENV_NAME} with ${IMAGE}"
````

### 02-secrets-preflight.patch

````diff
--- a/deploy/secrets-test.sh
+++ b/deploy/secrets-test.sh
@@ -62,6 +62,21 @@
   grep -qF -- "$2" "$T" || { echo "  FAIL $1: the output does not say: $2"; fails=$((fails+1)); }; }
 expect() { # label, expected rc, actual line
   case "$3" in "rc=$2 "*) echo "  ok   $1: $3";; *) echo "  FAIL $1 (expected rc=$2): $3"; fails=$((fails+1));; esac; }
+# 0: every check that can stop a run comes before the first write, so a stop leaves nothing half done: the existing Secrets of a
+# late check, a late read, the bind user and the key file, each on an otherwise fresh install.
+none_written() { same "$1 no realm Secret was written" none "$(hs sect2 cmapi-realm-secrets)"; same "$1 no client Secret was written" none "$(h)"; same "$1 no keys Secret was written" none "$(hs sect1 cmapi-keys)"; }
+k create secret generic cmapi-github-app -n sect1 >/dev/null
+r=$(run); expect "0a an empty app Secret stops" 1 "$r"; none_written 0a
+k delete secret cmapi-github-app -n sect1 >/dev/null
+r=$(runf "get secret cmapi-github-app"); expect "0b a failed late read stops" 1 "$r"; none_written 0b; said "0b it stops at the read" "an error on the server"
+k create secret generic cmapi-keys -n sect1 >/dev/null
+r=$(run); expect "0c an empty cmapi-keys stops" 1 "$r"; same "0c no realm Secret was written" none "$(hs sect2 cmapi-realm-secrets)"; same "0c no client Secret was written" none "$(h)"
+k delete secret cmapi-keys -n sect1 >/dev/null
+r=$(runb); expect "0d a missing cmapi-ldap-bind stops" 1 "$r"; none_written 0d
+printf 'not a key\n' >"$W/key0"; chmod 644 "$W/key0"
+r=$(run --github-app-key "$W/key0" --github-app-id 1 --github-installation-id 2); expect "0e a key file others can read stops" 2 "$r"; none_written 0e
+chmod 600 "$W/key0"
+r=$(run --github-app-key "$W/key0"); expect "0f a key file with no ids stops" 2 "$r"; none_written 0f
 r=$(run); expect "1 fresh" 0 "$r"; H1=$(h); R1=$(hs sect2 cmapi-realm-secrets); K1=$(hs sect1 cmapi-keys); collect
 r=$(run); expect "2 second run" 0 "$r"; [ "$(h)" = "$H1" ] || { echo "  FAIL 2: the hash changed"; fails=$((fails+1)); }
 same "2 the realm copy" "$R1" "$(hs sect2 cmapi-realm-secrets)"; same "2 cmapi-keys is written once" "$K1" "$(hs sect1 cmapi-keys)"
--- a/deploy/secrets.sh
+++ b/deploy/secrets.sh
@@ -50,7 +50,14 @@
 # keys_of JSON: the data keys whose value is non-empty, one per line
 keys_of() { printf '%s' "$1" | python3 -c 'import json,sys; d=sys.stdin.read(); print("\n".join(k for k,v in ((json.loads(d) if d else {}).get("data") or {}).items() if v))'; }
 
+# Read and validate every existing object before the first create. A late read error or partial Secret must not leave an
+# otherwise unrelated Secret created by this run.
 ours=$(get "$NS" cmapi-keycloak); theirs=$(get "$REALM_NS" cmapi-realm-secrets)
+keys_existing=$(get "$NS" cmapi-keys)
+if [ "$LDAP_BIND" = true ]; then
+  lb_ours=$(get "$NS" cmapi-ldap-bind); lb_theirs=$(get "$REALM_NS" cmapi-ldap-bind)
+fi
+gh_existing=$(get "$NS" cmapi-github-app)
 verdict=$(OURS="$ours" THEIRS="$theirs" PAIRS="$PAIRS" python3 - <<'PY'
 import json,os
 pairs=[p.split(":") for p in os.environ["PAIRS"].split()]
@@ -71,6 +78,36 @@
 PY
 )
 case "$verdict" in
+  generate|from-realm|from-ours|same) ;;
+  *) echo "ERROR: $verdict. A realm keeps the values it first imported, so nothing is generated. Fix it by hand from the realm's own client secrets." >&2; exit 1 ;;
+esac
+if [ -n "$keys_existing" ]; then
+  for k in cursorKey linkKey; do
+    keys_of "$keys_existing" | grep -qx "$k" || { echo "ERROR: Secret $NS/cmapi-keys exists but lacks $k; it is never replaced automatically: fix or delete it by hand" >&2; exit 1; }
+  done
+fi
+if [ "$LDAP_BIND" = true ]; then
+  for pair in "$NS:$lb_ours" "$REALM_NS:$lb_theirs"; do
+    n=${pair%%:*}; j=${pair#*:}
+    [ -n "$j" ] || { echo "ERROR: Secret $n/cmapi-ldap-bind is missing; the owner creates it (docs/11), this script never does" >&2; exit 1; }
+    for k in bindDN password; do keys_of "$j" | grep -qx "$k" || { echo "ERROR: Secret $n/cmapi-ldap-bind lacks $k" >&2; exit 1; }; done
+  done
+  OURS="$lb_ours" THEIRS="$lb_theirs" python3 -c 'import json,os
+o=json.loads(os.environ["OURS"])["data"]; t=json.loads(os.environ["THEIRS"])["data"]
+d=[k for k in ("bindDN","password") if o[k]!=t[k]]
+raise SystemExit("ERROR: cmapi-ldap-bind differs between the namespaces on "+",".join(d)+"; make them equal by hand, nothing is written" if d else 0)' || exit 1
+fi
+if [ -n "$gh_existing" ]; then
+  for k in appId installationId privateKey; do
+    keys_of "$gh_existing" | grep -qx "$k" || { echo "ERROR: Secret $NS/cmapi-github-app exists but lacks $k; it is never replaced automatically: fix or delete it by hand" >&2; exit 1; }
+  done
+elif [ -n "$KEY" ]; then
+  if [ -z "$APP_ID" ] || [ -z "$INST_ID" ]; then echo "ERROR: --github-app-key needs --github-app-id and --github-installation-id" >&2; exit 2; fi
+  [ -r "$KEY" ] || { echo "ERROR: cannot read $KEY" >&2; exit 2; }
+  # The GNU form first: GNU's -f reports the file system on stdout before failing on %Lp, while BSD's stat refuses -c with nothing on stdout (#90).
+  mode=$(stat -c '%a' "$KEY" 2>/dev/null || stat -f '%Lp' "$KEY"); case "$mode" in *[1-7][0-7]|*[0-7][1-7]) echo "ERROR: $KEY is mode $mode; make it 0600" >&2; exit 2;; esac
+fi
+case "$verdict" in
   generate)
     # No Secret anywhere, but the realm was imported: its clients hold values nobody here knows any more.
     if realm_import_exists; then
@@ -90,47 +127,24 @@
 for p in os.environ["PAIRS"].split():
     a,b=p.split(":"); print(b,o[a])' | apply_secret "$REALM_NS" cmapi-realm-secrets ;;
   same) echo "realm secrets: both copies present and equal, nothing to do" ;;
-  *) echo "ERROR: $verdict. A realm keeps the values it first imported, so nothing is generated. Fix it by hand from the realm's own client secrets." >&2; exit 1 ;;
 esac
 
-keys_existing=$(get "$NS" cmapi-keys)
 if [ -z "$keys_existing" ]; then
   printf 'linkKey %s\ncursorKey %s\n' "$(b64 "$(rnd)")" "$(b64 "$(rnd)")" | apply_secret "$NS" cmapi-keys
 else
-  for k in cursorKey linkKey; do
-    keys_of "$keys_existing" | grep -qx "$k" || { echo "ERROR: Secret $NS/cmapi-keys exists but lacks $k; it is never replaced automatically: fix or delete it by hand" >&2; exit 1; }
-  done
   echo "cmapi-keys: present, kept"
 fi
 
 # The LDAP bind user is the owner's (docs/11, #34): checked, never generated. Both copies must exist, carry bindDN and
 # password, and be equal, or Keycloak's federation and the realm sync would disagree.
 if [ "$LDAP_BIND" = true ]; then
-  lb_ours=$(get "$NS" cmapi-ldap-bind); lb_theirs=$(get "$REALM_NS" cmapi-ldap-bind)
-  for pair in "$NS:$lb_ours" "$REALM_NS:$lb_theirs"; do
-    n=${pair%%:*}; j=${pair#*:}
-    [ -n "$j" ] || { echo "ERROR: Secret $n/cmapi-ldap-bind is missing; the owner creates it (docs/11), this script never does" >&2; exit 1; }
-    for k in bindDN password; do keys_of "$j" | grep -qx "$k" || { echo "ERROR: Secret $n/cmapi-ldap-bind lacks $k" >&2; exit 1; }; done
-  done
-  OURS="$lb_ours" THEIRS="$lb_theirs" python3 -c 'import json,os
-o=json.loads(os.environ["OURS"])["data"]; t=json.loads(os.environ["THEIRS"])["data"]
-d=[k for k in ("bindDN","password") if o[k]!=t[k]]
-raise SystemExit("ERROR: cmapi-ldap-bind differs between the namespaces on "+",".join(d)+"; make them equal by hand, nothing is written" if d else 0)' || exit 1
   echo "cmapi-ldap-bind: present in both namespaces with bindDN and password, equal"
 fi
 
 # The GitHub App credential: validated when present (never replaced), written only when absent and a key file is given.
-gh_existing=$(get "$NS" cmapi-github-app)
 if [ -n "$gh_existing" ]; then
-  for k in appId installationId privateKey; do
-    keys_of "$gh_existing" | grep -qx "$k" || { echo "ERROR: Secret $NS/cmapi-github-app exists but lacks $k; it is never replaced automatically: fix or delete it by hand" >&2; exit 1; }
-  done
   echo "cmapi-github-app: present with appId, installationId and privateKey, kept"
   [ -z "$KEY" ] || echo "note    : --github-app-key ignored, the Secret exists"
 elif [ -n "$KEY" ]; then
-  if [ -z "$APP_ID" ] || [ -z "$INST_ID" ]; then echo "ERROR: --github-app-key needs --github-app-id and --github-installation-id" >&2; exit 2; fi
-  [ -r "$KEY" ] || { echo "ERROR: cannot read $KEY" >&2; exit 2; }
-  # The GNU form first: GNU's -f reports the file system on stdout before failing on %Lp, while BSD's stat refuses -c with nothing on stdout (#90).
-  mode=$(stat -c '%a' "$KEY" 2>/dev/null || stat -f '%Lp' "$KEY"); case "$mode" in *[1-7][0-7]|*[0-7][1-7]) echo "ERROR: $KEY is mode $mode; make it 0600" >&2; exit 2;; esac
   printf 'appId %s\ninstallationId %s\nprivateKey %s\n' "$(b64 "$APP_ID")" "$(b64 "$INST_ID")" "$(base64 <"$KEY" | tr -d '\n')" | apply_secret "$NS" cmapi-github-app
 fi
--- a/deploy/tests/mutate-secrets.py
+++ b/deploy/tests/mutate-secrets.py
@@ -14,6 +14,12 @@
 SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(HERE)
 GEN = '    printf \'%s\' "$lines" | apply_secret "$NS" cmapi-keycloak ;;'
 IMPORT_GUARD = "    if realm_import_exists; then"
+# A write ahead of one check: the case that names that check must see it.
+EARLY_WRITE = '  printf \'CMAPI_REALM_ADMIN_SECRET %s\\n\' "$(b64 "$(rnd)")" | apply_secret "$REALM_NS" cmapi-realm-secrets >/dev/null\n'
+KEYS_CHECK = 'if [ -n "$keys_existing" ]; then\n'
+LDAP_CHECK = '  for pair in "$NS:$lb_ours" "$REALM_NS:$lb_theirs"; do\n'
+APP_CHECK = 'if [ -n "$gh_existing" ]; then\n  for k in appId'
+KEY_FILE_CHECK = 'elif [ -n "$KEY" ]; then\n  if [ -z "$APP_ID" ]'
 MUTANTS = {
     "base (no mutation)": [],
     "A prints every generated value to the terminal": [(GEN, '    printf \'%s\' "$lines"; printf \'%s\' "$lines" | apply_secret "$NS" cmapi-keycloak ;;')],
@@ -51,6 +57,13 @@
     "P an existing Secret with no data counts as absent again": [('if not oe and not te: print("generate")', 'if not o and not t: print("generate")')],
     "Q apply again instead of create: a stale read can overwrite": [(
         'kc create -f - >/dev/null; echo "wrote Secret $1/$2"; }', 'kc apply --server-side --field-manager=cmapi-secrets -f - >/dev/null; echo "wrote Secret $1/$2"; }')],
+    "R a Secret written before the check of an existing cmapi-keys": [(KEYS_CHECK, KEYS_CHECK + EARLY_WRITE)],
+    "S a Secret written before the cmapi-ldap-bind check": [(LDAP_CHECK, EARLY_WRITE + LDAP_CHECK)],
+    "T a Secret written before the check of an existing app Secret": [(APP_CHECK, APP_CHECK.replace("then\n", "then\n" + EARLY_WRITE))],
+    "U a Secret written before the key file's checks": [(KEY_FILE_CHECK, KEY_FILE_CHECK.replace("then\n", "then\n" + EARLY_WRITE))],
+    "V the app Secret read after the writes again": [
+        ('gh_existing=$(get "$NS" cmapi-github-app)\n', "gh_existing=\n"),
+        ("# The GitHub App credential: validated", 'gh_existing=$(get "$NS" cmapi-github-app)\n# The GitHub App credential: validated')],
 }
 
 
````

### 03-router-selector.patch

````diff
--- a/cmapi/tests/service/test_plain_manifests.py
+++ b/cmapi/tests/service/test_plain_manifests.py
@@ -54,8 +54,12 @@
     policy = next(d for d in docs() if d["kind"] == "NetworkPolicy" and d["metadata"]["name"] == "cmapi-metrics")
     api = next(r for r in policy["spec"]["ingress"] if any(p["port"] == 8080 for p in r["ports"]))
     assert api.get("from"), "a rule with no from: any pod on the shared cluster reaches 8080"
-    labels = [p.get("namespaceSelector", {}).get("matchLabels", {}) for p in api["from"]]
-    assert {"network.openshift.io/policy-group": "ingress"} in labels, "the router's namespace"
+    # Whole, not "the router's label is among them": an added peer with an empty namespaceSelector would match every namespace
+    # and still hold that label's peer.
+    assert api["from"] == [
+        {"namespaceSelector": {"matchLabels": {"policy-group.network.openshift.io/ingress": ""}}},
+        {"podSelector": {}},
+    ]
 
 
 @pytest.mark.parametrize("name", ["cmapi-api", "cmapi-worker"])
--- a/deploy/manifests/components/cmapi/40-networkpolicy.yaml
+++ b/deploy/manifests/components/cmapi/40-networkpolicy.yaml
@@ -17,12 +17,15 @@
             matchLabels: {kubernetes.io/metadata.name: openshift-user-workload-monitoring}
       ports:
         - {port: 9090, protocol: TCP}
-    # OpenShift's router namespace carries policy-group: ingress; the second peer is this namespace. A rule with no from
-    # would open 8080 to every pod of every project on a shared cluster. On a cluster with no such label only this
-    # namespace matches, and kubectl port-forward does not pass through the policy.
+    # OpenShift's router namespace carries policy-group.network.openshift.io/ingress, the label its documentation prefers; the
+    # older network.openshift.io/policy-group is the one it calls legacy. CRC's openshift-ingress carries both (oc get ns, measured).
+    # The second peer is this namespace. A rule with no from would open 8080 to every pod of every project on a shared cluster.
+    # On a cluster with no such label only this namespace matches, and kubectl port-forward does not pass through the policy.
+    # A router on the host network is not this namespace's pod: from its own node the traffic is always allowed (CRC has one
+    # node); from another node it would need a peer for policy-group.network.openshift.io/host-network as well.
     - from:
         - namespaceSelector:
-            matchLabels: {network.openshift.io/policy-group: ingress}
+            matchLabels: {policy-group.network.openshift.io/ingress: ""}
         - podSelector: {}
       ports:
         - {port: 8080, protocol: TCP}
````

### 04-kind-ownership.patch

````diff
--- a/deploy/kind-test.sh
+++ b/deploy/kind-test.sh
@@ -17,21 +17,32 @@
 export KIND_EXPERIMENTAL_PROVIDER=podman
 t0=$(date +%s); say() { echo "[$(( $(date +%s) - t0 ))s] $*"; }
 k() { kubectl --kubeconfig="$KC" "$@"; }
-# Only a cluster this run created: "kind create" fails when the name is taken, and that cluster is somebody else's.
+# Only a cluster this run created, and only a kubeconfig it created: KIND_TEST_KUBECONFIG may name a file with other clusters in it.
 created=false
+kc_existed=false; [ ! -e "$KC" ] || kc_existed=true
 # A port-forward left behind holds its port and would answer a later run's curl from this run's cluster.
 PF=
-finish() { rc=$?; [ -z "$PF" ] || kill "$PF" 2>/dev/null || true; [ -z "${T:-}" ] || rm -rf "$T"; if [ "$created" = true ] && [ "${KIND_TEST_KEEP:-false}" != true ]; then say "deleting kind cluster cmapi-test"; kind delete cluster --name cmapi-test --kubeconfig "$KC" >/dev/null 2>&1 || true; rm -f "$KC"; fi; exit $rc; }
+finish() { rc=$?; [ -z "$PF" ] || kill "$PF" 2>/dev/null || true; [ -z "${T:-}" ] || rm -rf "$T"; if [ "$created" = true ] && [ "${KIND_TEST_KEEP:-false}" != true ]; then say "deleting kind cluster cmapi-test"; kind delete cluster --name cmapi-test --kubeconfig "$KC" >/dev/null 2>&1 || true; [ "$kc_existed" = true ] || rm -f "$KC"; fi; exit $rc; }
 trap finish EXIT
 
+T=$(mktemp -d)
+# A name already taken is somebody else's cluster. Not "| grep -q" in an if: under pipefail an early match can read as none.
+clusters=$(kind get clusters)
+case $'\n'"$clusters"$'\n' in *$'\n'cmapi-test$'\n'*) echo "ERROR: kind cluster cmapi-test already exists; this run neither uses nor deletes a cluster it did not create" >&2; exit 1;; esac
 say "kind create cluster cmapi-test ($NODE_IMAGE)"
-kind create cluster --name cmapi-test --image "$NODE_IMAGE" --kubeconfig "$KC" --wait 120s >/dev/null
+# kind removes what it made when a step fails, but not when it is interrupted or when its last step, the kubeconfig export,
+# fails (pkg/cluster/internal/create/create.go, v0.33.0), so this run owns the name from here. The exception is another run
+# taking the name after the check above: kind then stops before creating anything, and that cluster is the other run's.
 created=true
+if ! { kind create cluster --name cmapi-test --image "$NODE_IMAGE" --kubeconfig "$KC" --wait 120s >/dev/null; } 2>&1 | tee "$T/kind-create.err" >&2; then
+  case "$(cat "$T/kind-create.err")" in *"node(s) already exist for a cluster"*) created=false;; esac
+  echo "ERROR: kind create cluster failed" >&2; exit 1
+fi
 [ "$(k config current-context)" = kind-cmapi-test ] || { echo "ERROR: the kubeconfig's context is not kind-cmapi-test" >&2; exit 1; }
 say "node: $(k get nodes -o jsonpath='{.items[0].metadata.name} {.items[0].status.nodeInfo.kubeletVersion}')"
 
 say "CloudNativePG operator 1.30.1"
-T=$(mktemp -d); curl -fsSL "$CNPG_URL" -o "$T/cnpg.yaml"
+curl -fsSL "$CNPG_URL" -o "$T/cnpg.yaml"
 echo "$CNPG_SHA  $T/cnpg.yaml" | shasum -a 256 -c - >/dev/null || { echo "ERROR: cnpg-1.30.1.yaml checksum mismatch" >&2; exit 1; }
 k apply --server-side -f "$T/cnpg.yaml" >/dev/null
 k -n cnpg-system rollout status deploy/cnpg-controller-manager --timeout=180s >/dev/null; say "cnpg operator ready"
--- a/deploy/tests/kind-test-stubbed.sh
+++ b/deploy/tests/kind-test-stubbed.sh
@@ -56,6 +56,20 @@
 one "the worker has crash-looped since its rollout"    nonzero KT_WORKER_RESTARTS=4
 one "a cluster named cmapi-test already exists"        nonzero KT_CLUSTER_EXISTS=true
 want_field "somebody else's cluster is not deleted" no "$LAST_KILLED"
+one "the existing-cluster read fails"                  nonzero KT_CLUSTER_READ_FAIL=true
+want_field "a failed ownership read deletes nothing" no "$LAST_KILLED"
+one "a cluster whose name only contains cmapi-test"    0       KT_CLUSTER_OTHER=true
+one "kind fails after making part of this run's cluster" nonzero KT_CREATE_PARTIAL=true
+want_field "this run's partial cluster is deleted" yes "$LAST_KILLED"
+one "another run took the name after the check"        nonzero KT_CREATE_RACE=true
+want_field "the other run's cluster is not deleted" no "$LAST_KILLED"
+# KIND_TEST_KUBECONFIG may name a file with other clusters in it: only a file this run created goes.
+one "a kubeconfig this run created"                    0
+[ ! -e "$W/kc" ] || { echo "WRONG: a kubeconfig this run created was left behind"; fails=$((fails+1)); rm -f "$W/kc"; }
+echo other-clusters >"$W/kc"
+one "a kubeconfig that was already there"              0
+[ "$(cat "$W/kc" 2>/dev/null)" = other-clusters ] || { echo "WRONG: a kubeconfig this run did not create was deleted"; fails=$((fails+1)); }
+rm -f "$W/kc"
 one "probe resolves now, old previous log says failed" 0       KT_API_SLOW=true 'KT_PREVIOUS=failed to resolve host cmapi-db-rw.wrong'
 want_field "the policy stays: the container resolves the Service now" no "$LAST_DELETED"
 one "the probe could not run, the previous log says it"  0       KT_API_SLOW=true 'KT_PROBE=error: container not running' 'KT_PREVIOUS=failed to resolve host cmapi-db-rw.cmapi'
--- a/deploy/tests/kind-test-stubs/kind
+++ b/deploy/tests/kind-test-stubs/kind
@@ -1,6 +1,14 @@
 #!/usr/bin/env bash
 echo "kind $*" >>"$KT_LOG"
 case "$1" in
-  create) if [ "${KT_CLUSTER_EXISTS:-false}" = true ]; then echo 'ERROR: failed to create cluster: node(s) already exist for a cluster with the name "cmapi-test"' >&2; exit 1; fi;;
+  get)
+    [ "${KT_CLUSTER_READ_FAIL:-false}" != true ] || exit 2
+    [ "${KT_CLUSTER_EXISTS:-false}" != true ] || echo cmapi-test
+    [ "${KT_CLUSTER_OTHER:-false}" != true ] || { echo cmapi-test-2; echo not-cmapi-test; };;
+  create)
+    # The exact text of pkg/cluster/internal/create/create.go, v0.33.0.
+    if [ "${KT_CREATE_RACE:-false}" = true ] || [ "${KT_CLUSTER_EXISTS:-false}" = true ]; then echo 'ERROR: failed to create cluster: node(s) already exist for a cluster with the name "cmapi-test"' >&2; exit 1; fi
+    if [ "${KT_CREATE_PARTIAL:-false}" = true ]; then echo 'ERROR: failed to create cluster: could not export kubeconfig' >&2; exit 1; fi
+    prev=; for a in "$@"; do if [ "$prev" = --kubeconfig ] && [ ! -e "$a" ]; then : >"$a"; fi; prev=$a; done;;
 esac
 exit 0
````

### 05-doc12-restore.patch

````diff
--- a/deploy/tests/doc12-test.py
+++ b/deploy/tests/doc12-test.py
@@ -56,6 +56,57 @@
 # section 5
 check(not re.search(r"pg_dump[^\n]*-U cmapi", move), "section 5: pg_dump is not -U cmapi on the socket (measured: Peer authentication failed)")
 check("PGSSLROOTCERT" in move or "sslrootcert" in move.split("pg_restore")[1].split("\n")[0], "section 5: pg_restore has a root certificate for verify-full")
+# The block itself, on stubs of oc, pg_restore and psql: what reaches psql, in what order, and what stops it.
+RESTORE_STUB = '''#!/bin/sh
+echo "pg_restore $*" >> "$STUB_OUT/calls"
+printf 'SET statement_timeout = 0;\nSET transaction_timeout = 0;\nCREATE TABLE t(x text);\nCOPY t (x) FROM stdin;\nSET transaction_timeout = 0;\n\\.\n'
+exit ${STUB_RESTORE_RC:-0}
+'''
+PSQL_STUB = '''#!/bin/sh
+echo "psql $*" >> "$STUB_OUT/calls"
+case " $* " in
+  *" -f - "*) cat > "$STUB_OUT/psql.stdin"; exit ${STUB_PSQL_RC:-0};;
+esac
+echo "${STUB_TARGET_ROWS:-7}"
+'''
+OC_STUB = '''#!/bin/sh
+echo "oc $*" >> "$STUB_OUT/calls"
+case " $* " in
+  *" pg_dump "*) echo dump;;
+  *" psql "*) echo 7;;
+  *" wait "*) exit ${STUB_WAIT_RC:-0};;
+  *" get pod "*) [ -z "${STUB_PODS:-}" ] || echo "$STUB_PODS";;
+esac
+'''
+def run_move(**env):
+    t = tempfile.mkdtemp(); bindir = os.path.join(t, "bin"); os.mkdir(bindir); out = os.path.join(t, "out"); os.mkdir(out)
+    for name, body in (("oc", OC_STUB), ("pg_restore", RESTORE_STUB), ("psql", PSQL_STUB)):
+        p = os.path.join(bindir, name); open(p, "w").write(body); os.chmod(p, 0o755)
+    r = subprocess.run(["bash", "-c", move], cwd=t, env=dict(os.environ, PATH=bindir + ":" + os.environ["PATH"], STUB_OUT=out, **env), capture_output=True, text=True)
+    def read(n):
+        f = os.path.join(out, n)
+        return open(f).read() if os.path.exists(f) else ""
+    res = (r.returncode, read("calls"), read("psql.stdin"), r.stdout + r.stderr)
+    shutil.rmtree(t)
+    return res
+rc, calls, into_psql, printed = run_move()
+check(rc == 0, f"section 5: the block runs through on a good copy (rc {rc}: {printed[-200:]})")
+check("-d " not in next((c for c in calls.splitlines() if c.startswith("pg_restore")), "-d "), "section 5: pg_restore writes a script, so PostgreSQL 16's error on SET transaction_timeout is not fatal")
+atomic = next((c for c in calls.splitlines() if c.startswith("psql") and c.endswith(" -f -")), "")
+check("--single-transaction" in atomic and "ON_ERROR_STOP=1" in atomic, "section 5: the restore is one transaction that stops at the first error")
+check(into_psql.count("SET transaction_timeout = 0;") == 1 and into_psql.index("COPY") < into_psql.index("SET transaction_timeout = 0;"), "section 5: the header's SET transaction_timeout is gone, and a table row with the same text stays")
+check("SET statement_timeout = 0;" in into_psql and "CREATE TABLE" in into_psql, "section 5: nothing else is removed from the script")
+order = [c.split()[3] if c.startswith("oc") else c.split()[0] for c in calls.splitlines()]
+check(order[:3] == ["scale", "wait", "exec"], f"section 5: the dump waits for the old pods to go: {order[:3]}")
+rc, calls, _, _ = run_move(STUB_WAIT_RC="1")
+check(rc != 0 and "pg_dump" not in calls, "section 5: pods that do not go stop it before the dump")
+for label, env in (("pg_restore failing", {"STUB_RESTORE_RC": "1"}), ("psql failing", {"STUB_PSQL_RC": "3"})):
+    rc, calls, _, _ = run_move(**env)
+    check(rc != 0 and "count(*)" not in calls, f"section 5: {label} stops it before the counts (pipefail)")
+rc, _, _, _ = run_move(STUB_TARGET_ROWS="6")
+check(rc != 0, "section 5: counts that differ stop it")
+rc, _, _, _ = run_move(STUB_PODS="pod/cmapi-api-1")
+check(rc != 0, "section 5: a workload that came back stops it")
 check("Then replace `cmapi-db-app`" not in doc, "section 5: does not say to replace the Secret while the Cluster exists (measured: immutable type)")
 tail = doc[doc.index("## 5."):]
 check("delete cluster cmapi-db" in tail and "create the Secret (section 3" in tail and tail.find("delete cluster cmapi-db") < tail.find("create the Secret (section 3"), "section 5: the Cluster is deleted before the Secret is created")
--- a/docs/12-existing-postgresql.md
+++ b/docs/12-existing-postgresql.md
@@ -90,30 +90,50 @@
 back at once; deleting the `Cluster` garbage-collects it, and removes the PVC too (measured, CNPG 1.30.1 on kind). So prove
 the copy first, with the workloads at 0, and only then delete the `Cluster` and create the Secret.
 
+Where Argo CD syncs cmapi, turn its automated sync off first and put it back at the end: the Deployments say `replicas: 1`,
+and self-heal undoes a hand edit (measured at 40 s on an image, the deployment design, D3), so the workloads would come back
+during the dump. The block below stops if they did.
+
 ```bash
-( set -eu   # a subshell: set -e in a terminal's own shell would close it on the first failure
+( set -euo pipefail   # a subshell: set -e in a terminal's own shell would close it on the first failure
   oc -n cmapi scale deploy cmapi-api cmapi-worker --replicas=0
+  # scale returns at once, and a worker finishes the job in hand for up to 60 s: what it writes after the dump's snapshot is lost.
+  oc -n cmapi wait --for=delete pod -l 'app.kubernetes.io/component in (api,worker)' --timeout=120s
   # On the pod's socket only the database user postgres may connect (peer, CNPG's ident map); -U cmapi is refused there.
   oc -n cmapi exec cmapi-db-1 -c postgres -- pg_dump -Fc -U postgres cmapi > cmapi.dump
   test -s cmapi.dump
-  # ca-bundle.crt is the server's CA on this machine: verify-full with no root certificate is an error. pg_restore must be
-  # 17 or later (CNPG's pg_dump is 17; a 16 client refuses the archive: "unsupported version (1.16) in file header").
+  # ca-bundle.crt is the server's CA on this machine: verify-full with no root certificate is an error. pg_restore and psql must
+  # be 17 or later (CNPG's pg_dump is 17; a 16 client refuses the archive: "unsupported version (1.16) in file header").
   export PGSSLROOTCERT=$PWD/ca-bundle.crt
   TARGET="postgresql://cmapi@db.example.internal:5432/cmapi?sslmode=verify-full"
-  pg_restore -d "$TARGET" --no-owner --role=cmapi cmapi.dump
+  # All or nothing, on 16 and 17, through psql and not pg_restore -d. pg_restore 17 always opens with SET transaction_timeout,
+  # which PostgreSQL 16 does not have (measured): plain pg_restore -d restores everything and then exits 1, which stops this
+  # block, and pg_restore --single-transaction fails on it before the first object. The awk removes that one line, the first
+  # match only, so table data cannot be touched. A failed restore leaves the target as it was, so it can simply be run again.
+  pg_restore -f - --no-owner --role=cmapi cmapi.dump \
+    | LC_ALL=C awk '!done && $0 == "SET transaction_timeout = 0;" { done = 1; next } { print }' \
+    | psql -X -q -v ON_ERROR_STOP=1 --single-transaction -d "$TARGET" -f - >/dev/null
   # These two counts must match. Keep cmapi.dump: the next step destroys the source.
-  oc -n cmapi exec cmapi-db-1 -c postgres -- psql -U postgres -d cmapi -Atc 'select count(*) from change_requests'
-  psql "$TARGET" -Atc 'select count(*) from change_requests'
+  source_rows=$(oc -n cmapi exec cmapi-db-1 -c postgres -- psql -U postgres -d cmapi -Atc 'select count(*) from change_requests')
+  target_rows=$(psql "$TARGET" -Atc 'select count(*) from change_requests')
+  echo "change_requests: source $source_rows, target $target_rows"
+  [ "$source_rows" = "$target_rows" ]
+  # And nothing came back while it ran, or the dump is not the last word.
+  [ -z "$(oc -n cmapi get pod -l 'app.kubernetes.io/component in (api,worker)' -o name)" ]
 )
 ```
 
 Then, in this order: take `components/database-cnpg/` out of what is applied (the `Cluster` carries
 `Prune=false,Delete=false`, so removing its file from Git does not delete it, and leaving the file in would recreate it);
-`oc -n cmapi delete cluster cmapi-db`; create the Secret (section 3, step 3); scale back up; confirm `/readyz` is 200.
+`oc -n cmapi delete cluster cmapi-db`; create the Secret (section 3, step 3); scale back up, or turn Argo CD's automated sync
+back on; confirm `/readyz` is 200.
 
 ## 6. Not measured
 
 Run against a PostgreSQL 16 with TLS in a container (sections 2 and 3: the real migrator, `verify-full`, a wrong CA and a
-wrong name refused, `pg_stat_ssl` true) and against CNPG 1.30.1 on kind (section 5's dump and the Secret's ownership). No
+wrong name refused, `pg_stat_ssl` true) and against CNPG 1.30.1 on kind (section 5's dump and the Secret's ownership).
+Section 5's restore ran from the CNPG image's pg_restore and psql 17.11, without TLS, on the real migrations' schema and on
+PostgreSQL 16.15 and 17.11 targets: a complete copy, and a failure on the last table leaving the target as it was. Not run:
+that restore of a dump from a real CNPG cluster, or Argo CD's automated sync being turned off around it. No
 run against a real external server on a cluster exists yet: the first site that does one records `pg_stat_ssl`, the
 migration time and the connection count here.
````

### 06-image-guard.patch

````diff
--- a/cmapi/tests/service/test_plain_manifests.py
+++ b/cmapi/tests/service/test_plain_manifests.py
@@ -3,6 +3,7 @@
 the charts. Static: no cluster, no database."""
 from __future__ import annotations
 
+import re
 from pathlib import Path
 
 import pytest
@@ -13,10 +14,13 @@
 PLACEHOLDER = "ghcr.io/ephico2real2/cmapi@sha256:DIGEST"
 TRUST = "/etc/cmapi/ca/ca-bundle.crt"
 CHECKSUM_PLACEHOLDER = "CMAPI_CONFIG_CHECKSUM"
+# The only images here that are not cmapi's, by repository. A digest bump changes nothing; a new repository is a decision.
+OTHER_IMAGES = {"docker.io/nginxinc/nginx-unprivileged", "ghcr.io/cloudnative-pg/postgresql:17"}
 
 
 def docs():
-    for f in sorted(COMPONENTS.rglob("*.yaml")):
+    # .yml too: kubectl apply -R and Argo CD take it, and render.sh only refuses one that holds a placeholder.
+    for f in sorted([*COMPONENTS.rglob("*.yaml"), *COMPONENTS.rglob("*.yml")]):
         for d in yaml.safe_load_all(f.read_text()):
             if d:
                 yield d
@@ -101,11 +105,63 @@
             assert sc["allowPrivilegeEscalation"] is False and sc["capabilities"]["drop"] == ["ALL"] and "runAsUser" not in sc
 
 
-def test_every_image_is_the_placeholder_or_a_digest():
-    for d in deployments():
-        pod = d["spec"]["template"]["spec"]
-        for c in pod.get("initContainers", []) + pod["containers"]:
-            assert c["image"] == PLACEHOLDER or "@sha256:" in c["image"], c["image"]
+def images(node):
+    """Every image and imageName under an object, whatever its kind: a Job or a sidecar runs an image as well."""
+    if isinstance(node, dict):
+        for key, value in node.items():
+            if key in ("image", "imageName") and isinstance(value, str):
+                yield value
+            else:
+                yield from images(value)
+    elif isinstance(node, list):
+        for value in node:
+            yield from images(value)
+
+
+def image_problems(objects):
+    """The api and the worker run the placeholder and nothing else, so render.sh decides what they run. Anything else is the
+    placeholder or a known repository pinned by a whole digest. Against a mistake (a digest pinned while debugging, a forgotten
+    tag), not an attacker: whoever can edit the manifests in a pull request can edit this too, and review is what stops them."""
+    problems = []
+    for d in objects:
+        name = d["metadata"]["name"]
+        for image in images(d):
+            repository, _, digest = image.partition("@sha256:")
+            pinned = repository in OTHER_IMAGES and re.fullmatch(r"[0-9a-f]{64}", digest)
+            ours = d["kind"] == "Deployment" and name in ("cmapi-api", "cmapi-worker")
+            if image != PLACEHOLDER and (ours or not pinned):
+                problems.append(f"{d['kind']}/{name}: {image}")
+    return problems
+
+
+def test_every_image_is_the_placeholder_or_a_known_digest():
+    objects = list(docs())
+    assert image_problems(objects) == []
+    assert sum(1 for d in objects for image in images(d) if image == PLACEHOLDER) == 4, "two Deployments, each a migrate and a main container"
+
+
+EVIL = "ghcr.io/evil/cmapi@sha256:" + "e" * 64
+
+
+def _containers(objects, name):
+    pod = next(d for d in objects if d["kind"] == "Deployment" and d["metadata"]["name"] == name)["spec"]["template"]["spec"]
+    return pod.get("initContainers", []) + pod["containers"]
+
+
+@pytest.mark.parametrize("change", [
+    pytest.param(lambda o: _containers(o, "cmapi-api")[0].update(image=EVIL), id="the api's migrate container"),
+    pytest.param(lambda o: _containers(o, "cmapi-worker")[1].update(image=EVIL), id="the worker's main container"),
+    pytest.param(lambda o: _containers(o, "cmapi-mockup")[0].update(image=EVIL), id="the mockup, another repository"),
+    pytest.param(lambda o: _containers(o, "cmapi-mockup")[0].update(image="docker.io/nginxinc/nginx-unprivileged:latest"), id="the mockup, a tag"),
+    pytest.param(lambda o: _containers(o, "cmapi-mockup")[0].update(image="docker.io/nginxinc/nginx-unprivileged@sha256:abc"), id="the mockup, a short digest"),
+    pytest.param(lambda o: next(d for d in o if d["kind"] == "Cluster")["spec"].update(imageName="ghcr.io/cloudnative-pg/postgresql:17"), id="the database, a tag"),
+    pytest.param(lambda o: o.append({"kind": "Job", "metadata": {"name": "x"}, "spec": {"template": {"spec": {"containers": [{"name": "x", "image": EVIL}]}}}}), id="a Job"),
+])
+def test_the_image_guard_can_fail(change):
+    objects = list(docs())
+    assert image_problems(objects) == []
+    change(objects)
+    assert image_problems(objects), "the guard let this through"
 
 
 def test_the_database_keeps_itself_and_names_no_storage_class():
--- a/deploy/render-test.sh
+++ b/deploy/render-test.sh
@@ -13,7 +13,9 @@
 # Fills exactly the placeholder: every other byte of every file is the source's.
 "$R" kind "$GOOD" "$W/o1" >/dev/null || bad "a digest was refused"
 n=$(grep -r "sha256:DIGEST" "$D/manifests/components" "$D/manifests/environments/kind" | wc -l | tr -d ' ')
-[ "$n" -gt 0 ] || bad "the source holds no placeholder: this case proves nothing"
+# Exactly four: two Deployments, each a migrate and a main container. One replaced by a pinned image would otherwise pass as
+# "3 placeholders, 3 filled"; a Job or a sidecar on this image is a decision, and changes this number with it.
+[ "$n" = 4 ] || bad "the source must hold the four cmapi image placeholders, got $n"
 m=$(grep -rF "$GOOD" "$W/o1/components" "$W/o1/environment" | wc -l | tr -d ' ')
 want "$n placeholders, $m filled" "$n placeholders, $m filled with the image" [ "$m" = "$n" ]
 # Into a variable, not "| grep -q" in an if: under pipefail diff's own rc 1 made that pipeline false whatever it found.
````

### 07-render-test-gaps.patch

````diff
--- a/deploy/render-test.sh
+++ b/deploy/render-test.sh
@@ -21,6 +21,10 @@
 # Into a variable, not "| grep -q" in an if: under pipefail diff's own rc 1 made that pipeline false whatever it found.
 extra=$(diff -r "$D/manifests/components" "$W/o1/components" | grep '^[<>]' | grep -vE 'image: |checksum/config: ')
 if [ -n "$extra" ]; then bad "a line other than an image or the checksum changed: $extra"; else ok "only image and checksum lines changed"; fi
+# And the same files: the line diff above cannot see a file the render dropped or added. The environment has no placeholder.
+only=$(diff -r "$D/manifests/components" "$W/o1/components" | grep '^Only in')
+if [ -n "$only" ]; then bad "the render's files are not the source's: $only"; else ok "the render holds every file of components, and no other"; fi
+want "the environment is the source's, every byte" "the rendered environment differs" diff -r "$D/manifests/environments/kind" "$W/o1/environment"
 want "the mockup's own image is untouched" "the mockup's image changed" grep -q 'nginx-unprivileged@sha256:' "$W/o1/components/portal/10-mockup.yaml"
 want "IMAGE names it" "IMAGE does not name it" [ "$(cat "$W/o1/IMAGE")" = "$GOOD" ]
 if grep -rq 'sha256:DIGEST' "$W/o1"; then bad "a placeholder is left"; fi
@@ -35,6 +39,8 @@
 # The internal registry's digest is what Wave 1 deploys, by digest; no flag that says "never a deployment".
 want "the internal registry by digest" "the internal registry's digest needs --allow-tag" quiet "$R" crc "$INTERNAL" "$W/o5"
 if "$R" crc "registry.example.com/x@sha256:$(printf 'c%.0s' {1..64})" "$W/o6" >/dev/null 2>&1; then bad "another registry was accepted"; else ok "another registry is refused"; fi
+if "$R" crc "ghcr.io/evil/cmapi@sha256:$(printf 'c%.0s' {1..64})" "$W/o6" >/dev/null 2>&1; then bad "another GHCR repository was accepted"; else ok "another GHCR repository is refused"; fi
+if "$R" crc "ghcr.io/ephico2real2/cmapi@sha256:$(printf 'c%.0s' {1..63})" "$W/o6" >/dev/null 2>&1; then bad "a short digest was accepted"; else ok "a short digest is refused"; fi
 # The flag anywhere; the out dir is the out dir.
 "$R" kind localhost/cmapi:dev --allow-tag "$W/o7" >/dev/null 2>&1
 want "--allow-tag before the out dir" "--allow-tag before the out dir: the out dir was ignored" [ -f "$W/o7/IMAGE" ]
````

### 08-doc12-argv-and-apply-order.patch

````diff
--- a/cmapi/tests/service/test_plain_manifests.py
+++ b/cmapi/tests/service/test_plain_manifests.py
@@ -50,6 +50,12 @@
     assert pod_annotations(name)["checksum/config"] == CHECKSUM_PLACEHOLDER
 
 
+def test_the_readme_says_the_configuration_goes_first():
+    """The checksum makes a restart, it does not order one: pods restarted before the ConfigMap changes keep the old values."""
+    text = " ".join((ROOT / "deploy/manifests/README.md").read_text().split())
+    assert "apply the environment, then the components, in that order" in text
+
+
 def test_the_mockup_reads_none_of_that_configuration():
     assert "checksum/config" not in pod_annotations("cmapi-mockup")
 
--- a/deploy/manifests/README.md
+++ b/deploy/manifests/README.md
@@ -28,8 +28,9 @@
 
 - **A changed `cmapi-config`, `cmapi-env` or `cmapi-trust` restarts the api and the worker only through a render.** The
   process reads its config once, at start. `deploy/render.sh` puts a SHA-256 over those three files into the pod templates
-  (as the chart's `checksum/config` did), so render again and apply both the environment and the components. Applying a
-  changed ConfigMap alone restarts nothing.
+  (as the chart's `checksum/config` did), so render again and apply the environment, then the components, in that order:
+  pods restarted by the components before the ConfigMap changes read the old values, carry the new checksum, and nothing
+  restarts them again. Applying a changed ConfigMap alone restarts nothing.
 - **`cmapi-env` on CRC carries `CMAPI_OIDC_JWKS_URL` and `CMAPI_KEYCLOAK_ADMIN_URL`** (the Keycloak Service, as
   `deploy/environments/crc.yaml` sets them), or the pods go through the issuer's Route.
 - **Namespace `cmapi-imports` must exist first** (it does not on CRC, measured 2026-11-05; the chart created it): the
--- a/deploy/tests/doc12-test.py
+++ b/deploy/tests/doc12-test.py
@@ -53,6 +53,19 @@
 c = ov["spec"]["containers"][0]
 check("@sha256:" in c["image"], f"step 4: the pod's image is pinned ({c['image'][:60]})")
 check(not any(a.startswith("--env") for a in argv) or c.get("env"), "step 4: no --env that the overrides silently drop")
+# The password stays off psql's argument list, decoded right for scram: the pod's command, run with a stub psql.
+def run_pgcheck(pw):
+    t = tempfile.mkdtemp(); bindir = os.path.join(t, "bin"); os.mkdir(bindir)
+    uri = os.path.join(t, "uri"); open(uri, "w").write("postgresql://cmapi:" + urllib.parse.quote(pw, safe="") + "@db.example.internal:5432/cmapi?sslmode=verify-full&sslrootcert=/etc/cmapi/ca/ca-bundle.crt\n")
+    p = os.path.join(bindir, "psql"); open(p, "w").write('#!/bin/sh\nprintf "%s\\n" "$PGPASSWORD" > "$STUB_OUT/password"\nfor a in "$@"; do printf "%s\\n" "$a"; done > "$STUB_OUT/argv"\n'); os.chmod(p, 0o755)
+    r = subprocess.run([c["command"][0], "-c", c["command"][2].replace("/run/db/uri", uri)], env=dict(os.environ, PATH=bindir + ":" + os.environ["PATH"], STUB_OUT=t), capture_output=True, text=True)
+    res = r.returncode, open(os.path.join(t, "password")).read().rstrip("\n"), open(os.path.join(t, "argv")).read()
+    shutil.rmtree(t)
+    return res
+rc, password, argv_seen = run_pgcheck(PW)
+check(rc == 0 and password == PW, "step 4: psql gets the password, decoded, in PGPASSWORD")
+check(urllib.parse.quote(PW, safe="") not in argv_seen and PW not in argv_seen, "step 4: no password on psql's argument list")
+check("postgresql://cmapi@db.example.internal:5432/cmapi?sslmode=verify-full&sslrootcert=/etc/cmapi/ca/ca-bundle.crt" in argv_seen, "step 4: the rest of the URI reaches psql whole")
 # section 5
 check(not re.search(r"pg_dump[^\n]*-U cmapi", move), "section 5: pg_dump is not -U cmapi on the socket (measured: Peer authentication failed)")
 check("PGSSLROOTCERT" in move or "sslrootcert" in move.split("pg_restore")[1].split("\n")[0], "section 5: pg_restore has a root certificate for verify-full")
--- a/docs/12-existing-postgresql.md
+++ b/docs/12-existing-postgresql.md
@@ -60,9 +60,10 @@
 4. Check connectivity and the certificate name from inside the cluster, read-only, before the first migration:
 
    ```bash
-   # --overrides replaces the whole containers list, so the digest is repeated there and nothing else may rely on --image or --env
+   # --overrides replaces the whole containers list, so the digest is repeated there and nothing else may rely on --image or --env.
+   # The URI's password goes to psql decoded, in PGPASSWORD, and the rest of the URI as its argument: an argument list is readable.
    oc run -n cmapi pg-check --rm -it --restart=Never --image=ghcr.io/cloudnative-pg/postgresql:17@sha256:70664ebcfa1100361b5bdc28bbf06fdbe08db2dc4ad7bd14de33c5e05fe8ea8e \
-     --overrides='{"spec":{"containers":[{"name":"pg-check","image":"ghcr.io/cloudnative-pg/postgresql:17@sha256:70664ebcfa1100361b5bdc28bbf06fdbe08db2dc4ad7bd14de33c5e05fe8ea8e","command":["sh","-c","psql \"$(cat /run/db/uri)\" -c \"select version(), current_user, ssl.ssl from pg_stat_ssl ssl where pid = pg_backend_pid()\""],"volumeMounts":[{"name":"db","mountPath":"/run/db"},{"name":"ca","mountPath":"/etc/cmapi/ca"}]}],"volumes":[{"name":"db","secret":{"secretName":"cmapi-db-app"}},{"name":"ca","configMap":{"name":"cmapi-trust"}}]}}'
+     --overrides='{"spec":{"containers":[{"name":"pg-check","image":"ghcr.io/cloudnative-pg/postgresql:17@sha256:70664ebcfa1100361b5bdc28bbf06fdbe08db2dc4ad7bd14de33c5e05fe8ea8e","command":["bash","-c","uri=$(cat /run/db/uri); pw=${uri#*://*:}; pw=${pw%%@*}; export PGPASSWORD=$(printf %b \"${pw//%/\\\\x}\"); exec psql \"${uri/\":$pw@\"/@}\" -c \"select version(), current_user, ssl.ssl from pg_stat_ssl ssl where pid = pg_backend_pid()\""],"volumeMounts":[{"name":"db","mountPath":"/run/db"},{"name":"ca","mountPath":"/etc/cmapi/ca"}]}],"volumes":[{"name":"db","secret":{"secretName":"cmapi-db-app"}},{"name":"ca","configMap":{"name":"cmapi-trust"}}]}}'
    ```
 
    It must print the version, `cmapi` and `ssl = t`. A wrong CA or name fails here with the same message the
````
