# Deploying cmapi on CRC (Wave 1)

This is the runbook for the first deployment of cmapi on CRC (OpenShift Local), issue #94. Follow it from the top, in order, in one bash. It is interim: `oc apply` by hand, with the image in CRC's internal registry by digest. Argo CD adopts these objects in Wave 5. Since #157 a namespace request runs the whole way: the bot writes to the GitHub repository `ephico2real2/cmapi-cluster-configs`, and the worker delivers the merged folder by server-side apply (`delivery.mode: apply`), because CRC has no Argo CD. See [The full request flow](#the-full-request-flow).

**CRC is shared.** Other projects' realms live on the same Keycloak, which has one instance. The owner's requirement (2026-11-06): the other realms must not be affected, `inkcast` and `corp` must not be deleted, and a restart must not bleed long. So each step below has a stop. A stop means stop and report: no retry and no workaround.

**Status of this document.** It has not been run on CRC yet. Everything marked *measured* was measured elsewhere, on community Keycloak 26.6.4, PostgreSQL 16.15, an OpenLDAP stand-in and a kind cluster. See [Not proven before the run](#not-proven-before-the-run). The decisions and their reasons are in [`docs/reviews/2026-11-06-wave1-design/README.md`](reviews/2026-11-06-wave1-design/README.md).

## What this adds to CRC

| Where | What |
|---|---|
| Namespace `cmapi` (exists, holding `cmapi-ldap-bind`) | A label, the workloads, the front door, the database, Routes `cmapi` and `cmapi-mockup`, the monitoring objects, image streams `cmapi` and `cmapi-portal`, Secret `cmapi-ldap-test-users` (one password per test user). Secrets `cmapi-git-bot` and `cmapi-git-bot-ssh`, and ConfigMap `cmapi-git-bot-known-hosts`, the bot account's credentials, are the owner's: [step 3 below](#steps-only-the-owner-can-take) |
| Namespace `cmapi-imports` (new) | The imports reader Role, Secret `cmapi-cluster-crc` |
| Namespace `cmapi-system` (new) | ServiceAccount `cmapi-reader` and its token Secret |
| Cluster | ClusterRole and ClusterRoleBinding `cmapi-reader`: `get, list, watch` on namespaces, resourcequotas and limitranges, `get, list, watch` on nodes for the Capacity tab's allocatable and zones (#302; without it the tab shows "nodes not readable" and the commitment against the simulated size only), `list` on pods and persistentvolumeclaims, and `get, list, watch` on Kyverno's `policyreports`, `clusterpolicyreports` and `validatingpolicies` for the Policies tab (#302). CRC runs Kyverno v1.20.0 since 2026-11-17 (chart 3.10.0, namespace `kyverno`, its webhooks scoped to `cmapi.net/managed=true`), and until its bundle is applied ("Kyverno", below, #428) none of cmapi's policies is on it: the tab shows CRC **off the bundle**, Bundle running "31 missing", Policies ready "0 / 31", the cluster's counts 0 (Kyverno answers and has no result of the bundle), and "—" for each policy's counts, since none runs there. Without this rule the tab shows "no access to the reports". All of this holds while CRC's discovery serves `wgpolicyk8s.io/v1alpha2` (`GET /apis/wgpolicyk8s.io/v1alpha2` as `cmapi-reader`, the request of the API's own probe, which the CRC proof makes: it stops when the group or either report kind is not served, and records whether `openreports.io` is); a Kyverno that writes only `openreports.io` reports reads as "Kyverno not installed" until that group is read (deferred by the arbitration). ClusterRole and ClusterRoleBinding `cmapi-deliverer` for the worker's ServiceAccount, and ValidatingAdmissionPolicy and binding `cmapi-deliverer-managed-only`, which contain it (step 7) |
| Cluster, per request | Each namespace a request delivers, labelled `cmapi.net/managed=true`, with its ResourceQuota, its two LimitRanges `<ns>-limits-cpu` and `<ns>-limits-memory`, and RoleBinding `cmapi-token-issuer`. A delete request removes it, after an operator's `POST /api/v1/admin/prune:confirm` |
| GitHub `ephico2real2/cmapi-cluster-configs` | The bot's branches, pull requests, commit statuses `cmapi/check` and merges under `clusters/CRC/namespaces/`. The repository's own Actions report `ci/kubeconform` and `ci/kyverno` |
| Namespace `keycloak` | Secret `cmapi-realm-secrets`, and `KeycloakRealmImport cmapi`, deleted once Done |
| Keycloak | Realm `cmapi`, with guesses limited (a temporary lockout, in this realm alone) and its default `admin-cli` client off, so no client takes a person's password without a secret. Creating any realm also adds a client `cmapi-realm` to `master` (measured). That is the one known change outside realm `cmapi` |
| LDAP (namespace `ldap-testing`) | The ten `app-cmapi-rbac-*` groups and 13 `cmapi.<role>` test users. It removes the ten old `cmapi-*` groups, each by its full `dn`. No other entry changes: steps 9 and 10 fail if one does |

The realm reads LDAP through the read-only `cmapi-ldap-bind`, and only the test users. See [`docs/11`](11-existing-identity-services.md).

**One host for the instance (#226).** `https://cmapi.apps-crc.testing` is the front door: nginx in the `cmapi-portal` image serves the portal at `/` and passes `/api/v1`, `/docs`, `/redoc`, the OpenAPI document and the problem pages to the API pods. The API has no Route of its own, and only the front door's pods reach its port. The CLI, the SDK and `/docs` use the same host. The standalone mockup stays on `https://cmapi-mockup.apps-crc.testing`, served by the same front door. The decisions are in [`docs/reviews/2026-11-14-issue-226/README.md`](reviews/2026-11-14-issue-226/README.md).

## Before the run

### What must already be there

| What | How to check, read-only |
|---|---|
| `oc`, `podman`, `skopeo`, `kind`, `python3`, `curl`, `openssl`, `git` on the Mac | `command -v oc podman skopeo kind python3 curl openssl git` |
| `oc` logged in as kubeadmin on CRC. If the session has expired, `oc login -u kubeadmin https://api.crc.testing:6443` and type the password at the prompt, never with `-p` | `oc whoami --show-server; oc config current-context` |
| A clean checkout of the merged commit | `git status --porcelain` prints nothing |
| No kind cluster, and none during the run | `KIND_EXPERIMENTAL_PROVIDER=podman kind get clusters` |
| CloudNativePG 1.30.1 | `oc get crd clusters.postgresql.cnpg.io -o name` |
| Namespace `cmapi`, with Secret `cmapi-ldap-bind` in `cmapi` and `keycloak` | `oc get secret cmapi-ldap-bind -n cmapi -o name; oc get secret cmapi-ldap-bind -n keycloak -o name` |
| The bind user can read `ou=People` and `ou=Groups`, and the gate group `app-ssb-autobahnusers` exists | Step 9 reads both before it writes |

### Read-only facts, as read on 2026-11-06

The coordinator read these from CRC. Read them again if much time has passed.

| Question | Answer | Command |
|---|---|---|
| Does RHBK serve `spec.resources` on an import? | Yes. The field's text says "inherited from the Keycloak CR", while the Job measured there requests the operator's 1,700 Mi, so step 15's server dry run is the real check | `oc explain keycloakrealmimport.spec.resources --api-version=k8s.keycloak.org/v2beta1` |
| Can cmapi's pods reach Keycloak? | Yes. `keycloak-network-policy` allows 8443 and 9000 from anywhere | `oc get networkpolicy -n keycloak -o name` |
| Will federation work over this path? | Likely: `corp` uses the same `ldaps://ldaps-ldap-testing.apps-crc.testing:443`, `useTruststoreSpi: always`, `uid`, `inetOrgPerson`, and the truststore `ldap-root-ca` is on the Keycloak CR | `oc get keycloak keycloak -n keycloak -o jsonpath='{.spec.truststores}{"\n"}'` |
| How does the backup sign in? | `postgres-0` runs `registry.redhat.io/rhel9/postgresql-16:latest`, container `postgres`, with `POSTGRESQL_USER`, `POSTGRESQL_PASSWORD`, `POSTGRESQL_DATABASE` from Secret `keycloak-db`, read inside the pod. `pg_dump` and `pg_restore` 16.15. Limit 512 Mi, using 52 Mi | `deploy/crc-backup.sh --inspect`: names and sources, never a value |
| Can a test sign in through LDAP? | Only as a `cmapi.<role>` test user, made in step 9. No real person's password is available (`ldap-structure` holds five hashes and one value that was not printed, #35), and the realm cannot read a real person | Below |

### Steps only the owner can take

The first two are for the Chrome proofs of step 23, and neither blocks the steps before it. The third comes before step 11.

**1. Trust the two CAs in the login keychain.** Chrome refuses these sites otherwise, and clicking through a warning would be TLS verification off. Neither `LDAP Enterprise Root CA` nor `ingress-operator` is on this Mac (measured with `security find-certificate -c`), and macOS asks for a password to add one, which is why this is the owner's step.

Only `CA:TRUE` certificates are trusted, never a site's own. `default-ingress-cert`'s bundle holds the `*.apps-crc.testing` site certificate first and its CA second (measured, #109), so step 1 of the run writes each CA to its own file and leaves the site certificate out. Trusting that as a root would pin one site, and it would not be what signs the next one.

| File, from step 1 | Certificate | SHA-1, measured on 2026-11-06 |
|---|---|---|
| `keycloak-ca.pem` | `CN=LDAP Enterprise Root CA`, `CA:TRUE` | `58E4A0F4B51C06119EA25526330BEA85885B0FD8` |
| `ingress-ca.pem` | `CN=ingress-operator@1789448506`, `CA:TRUE, pathlen:0` | `C016211CBBB5CD072C3FFAC433221C38D1374E05` |

After step 1 of the run, in a bash with `$RUN` set. A fingerprint that differs means the CA changed: stop and report. It adds nothing.

```bash
# Each file: exactly one certificate, a CA, with the fingerprint above. A second CA trusted by mistake is one more thing that can mint for any site.
trust_ca() {
  local pem=$1 want=$2 text got
  [ "$(grep -c 'BEGIN CERTIFICATE' "$pem")" = 1 ] || { echo "STOP: $pem does not hold exactly one certificate"; return 1; }
  text=$(openssl x509 -in "$pem" -noout -text | awk '/X509v3 Basic Constraints/ { getline; print }')
  case "$text" in *CA:TRUE*) ;; *) echo "STOP: $pem is not a CA"; return 1;; esac
  got=$(openssl x509 -in "$pem" -noout -fingerprint -sha1 | sed 's/.*=//; s/://g')
  [ "$got" = "$want" ] || { echo "STOP: $pem is $got, not $want"; return 1; }
  security add-trusted-cert -r trustRoot -p ssl -k ~/Library/Keychains/login.keychain-db "$pem"
}
trust_ca "$RUN/keycloak-ca.pem" 58E4A0F4B51C06119EA25526330BEA85885B0FD8
trust_ca "$RUN/ingress-ca.pem" C016211CBBB5CD072C3FFAC433221C38D1374E05
```

Take them out when Wave 1's screenshots are done. Each CA can mint a certificate for any site, and both keys live on a test cluster. The trust setting comes off first: deleting only the certificate would leave the setting behind.

```bash
security remove-trusted-cert "$RUN/keycloak-ca.pem"
security delete-certificate -Z 58E4A0F4B51C06119EA25526330BEA85885B0FD8 ~/Library/Keychains/login.keychain-db
security remove-trusted-cert "$RUN/ingress-ca.pem"
security delete-certificate -Z C016211CBBB5CD072C3FFAC433221C38D1374E05 ~/Library/Keychains/login.keychain-db
```

**What the trust may not fix.** Measured on 2026-11-06: Keycloak's site certificate has no Extended Key Usage, so macOS's own `security verify-cert -p ssl` refuses it (`Invalid Extended Key Usage for policy`), while the ingress site certificate has `TLS Web Server Authentication` and passes. Chrome's result is not yet measured, so whether Chrome accepts Keycloak's sign-in page is the first thing this step shows. If it refuses, report it: the Chrome proofs that sign in are then not done, and clicking through is still not an answer. Not measured: this Mac's trust has not been changed.

**2. Sign in once as `cmapi.requester`,** in Chrome, with the password from the clipboard, so that it reaches nobody else and no screen. See [The issue's proofs](#the-issues-proofs).

**3. The bot account's credentials, before step 11.** The step-by-step guide, with rotation and troubleshooting, is [`docs/19`](19-setup-connections-to-git.md). cmapi writes through the Git protocol, and opens and merges the PR through the host's API (#286). The identity on every host is one machine user account, `cmapi-git-bot` (the owner's decision of 2026-11-15): its SSH key does the Git transport, and its API token does the PR. So every push and every PR is authored by `cmapi-git-bot`, and the commits name it, with `instance.git.commitEmail`.

| Object | Kind | Keys | Mounted in | For |
|---|---|---|---|---|
| `cmapi-git-bot` | Secret, Opaque | `token` | api and worker | The host API: the PR, its state, the merge, and the API process's reads. Git over HTTPS too, on CRC for now |
| `cmapi-git-bot-ssh` | Secret, `kubernetes.io/ssh-auth` | `ssh-privatekey`, optional `ssh-publickey` | worker only | Git over SSH. An ed25519 key with no passphrase; cmapi refuses an encrypted or unparseable key, or an `ssh-publickey` that is not its own, at start, and logs the key's fingerprint |
| `cmapi-git-bot-known-hosts` | ConfigMap | `known_hosts` | worker only | The Git host's keys, every type it publishes. An SSH host not listed is refused, and nothing is ever added |

The mounts are folders (`components/cmapi/30-worker.yaml`), so a rotation reaches the pod with no restart: to rotate a host key, add the new one, then remove the old one. The SSH user is `git` (`git@github.com`): the key selects the account.

**CRC: SSH since 2026-11-15.** The owner added the bot's SSH key, so CRC's `instance.git.url` is `git@github.com:ephico2real2/cmapi-cluster-configs.git` (`environments/crc/20-config.yaml`). Git uses Secret `cmapi-git-bot-ssh` and ConfigMap `cmapi-git-bot-known-hosts`, and no longer sees the API token, which stays for the PR. How to make the key and switch: [`docs/19`](19-setup-connections-to-git.md), sections 3 to 5.

**The token, on GitHub.** The machine user `cmapi-git-bot` with write access to `ephico2real2/cmapi-cluster-configs`, and its fine-grained personal access token: repository access **only** that repository, and these repository permissions:

| Permission | Access | For |
|---|---|---|
| Contents | Read and write | `git fetch` and `git push` over HTTPS, and the API process's reads of a folder |
| Pull requests | Read and write | Opening, reading, merging and closing the PR, and its comments |
| Metadata | Read | Every call (GitHub sets it) |

No Checks permission, and no Commit statuses permission while host CI is off (`instance.git.hostChecks: false`, CRC's setting): cmapi reads no check and posts no status then. GitHub allows one machine user for automation ([Managing deploy keys](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys), "Machine users", read on 2026-11-15).

To make the token, signed in as `cmapi-git-bot`:

1. Open <https://github.com/settings/personal-access-tokens/new>.
2. **Token name:** `cmapi-crc`. **Resource owner:** `ephico2real2`. **Expiration:** 30 days, or whatever you prefer.
3. Under **Repository access**, choose **Only select repositories**, then pick `ephico2real2/cmapi-cluster-configs`.
4. Under **Repository permissions**, set **Contents** and **Pull requests** to Read and write. **Metadata** → Read-only is set by GitHub.
5. Click **Generate token** and copy it. GitHub shows it only once.

The token goes from the clipboard to the Secret on stdin, so it is on no command line, in no shell history and on no screen:

```bash
pbpaste | tr -d '\r\n' | oc create secret generic cmapi-git-bot -n cmapi --from-file=token=/dev/stdin
pbcopy </dev/null
```

**The SSH key, when it is added.** An ed25519 key with no passphrase, its public key added to the `cmapi-git-bot` account's SSH keys, and GitHub's host keys checked against the fingerprints GitHub publishes (<https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints>):

```bash
ssh-keygen -t ed25519 -N '' -C cmapi-git-bot -f ./cmapi-git-bot
oc create secret generic cmapi-git-bot-ssh -n cmapi --type=kubernetes.io/ssh-auth \
  --from-file=ssh-privatekey=./cmapi-git-bot --from-file=ssh-publickey=./cmapi-git-bot.pub
ssh-keyscan -t ed25519,ecdsa,rsa github.com >./known_hosts    # then compare: ssh-keygen -lf ./known_hosts
oc create configmap cmapi-git-bot-known-hosts -n cmapi --from-file=known_hosts=./known_hosts
rm ./cmapi-git-bot
```

**On each host.** The bot account is the default; a deploy key is the alternative where the host allows writes with one. Read on 2026-11-15 at each source; a row marked *not verified* is not yet checked at its host's documentation:

| Host | Bot account (default): SSH | Bot account: API | Alternative | Source |
|---|---|---|---|---|
| GitHub | the machine user's SSH key | the machine user's fine-grained token: Contents and Pull requests read and write | a deploy key with write access, for SSH ("read-only by default, but you can give them write access"); the API still needs a token | [GitHub, deploy keys](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys) |
| GitLab | the service account's SSH key | the service account's token | a read-write deploy key, made by the service account ("You should use a service account, and create the deploy key with the service account"); or a project access token for the API | [GitLab, deploy keys](https://docs.gitlab.com/user/project/deploy_keys/) |
| Bitbucket Cloud | the bot account's own SSH key | the bot's API token, or a repository access token | none for writes: repository and project access keys are read-only, and workspace keys write to every repository of the workspace | [Atlassian, access keys](https://support.atlassian.com/bitbucket-cloud/kb/difference-between-repository-project-and-workspace-access-keys/) |
| Bitbucket Data Center | the bot user's SSH key | the bot user's HTTP access token | a repository access key with write access | Atlassian's Data Center pages, *not verified* |

On every host `main` is protected, so that only a merged PR changes it: the host enforces "cmapi never pushes to `main`" too. CRC's repository cannot: it is private on GitHub's free plan, which refuses branch protection (#227).

**Upgrading from `cmapi-git`.** Before #286 the token was Secret `cmapi-git`. Nothing migrates it: the owner loads the bot account's new token into `cmapi-git-bot` with the two lines above, and the rollback removes the old `cmapi-git` by name (`deploy/crc-rollback.sh`).

Give the token an expiry, and put a new one in before then: an expired token makes every request fail at the host, retried and then failed, and `cmapi_git_operations_total{result="refused"}` climbs. A new token: `oc delete secret cmapi-git-bot -n cmapi`, the same two lines, then `oc rollout restart deploy/cmapi-api deploy/cmapi-worker -n cmapi`, since the API client reads the token at start. Git over HTTPS reads the file at each call. Step 11 checks that the token is there, and reads no value.

## The run

Run these in one bash, not zsh, from the repository's root. Keep every output: it goes in `docs/reviews/`, once checked for secret values.

**How a stop works.** Each step is a subshell with `set -euo pipefail`, as in `docs/12`: `set -e` in a terminal's own shell would close it on the first failure, and a pasted `exit` would lose the variables below and leave the next paste running somewhere else. `stopped` writes any failure to `$STOP`. So a stop ends that step, the terminal stays, and every later step refuses at its first line, however much later it is pasted. Keep `; stopped $?` on its own after the `)`: a list such as `( ... ) || stopped` turns `set -e` off inside the parentheses, which is bash's rule.

```bash
RUN=$PWD/deploy/rendered/wave1-run; mkdir -p "$RUN"; R=$PWD/deploy/rendered/crc; STOP=$RUN/stop
G=deploy/crc-guard.py; export CMAPI_CRC_CA=$RUN/crc-ca.pem
stopped() { [ "$1" = 0 ] && return 0; echo "STOP at step $2 (rc $1): report it. No retry and no workaround." | tee -a "$STOP"; return "$1"; }
( set -euo pipefail
  $G gate "$STOP"
  [ -z "$(git status --porcelain)" ]
  git rev-parse --short=10 HEAD                                    # the merged commit
); stopped $? 0
```

### Step 1: the trust file still verifies Keycloak

```bash
( set -euo pipefail
  $G gate "$STOP"
  deploy/crc-trust.sh --check
  deploy/crc-trust.sh --mac-ca "$RUN/crc-ca.pem"
); stopped $? 1
```

**Stops when** `30-trust.yaml` no longer verifies Keycloak: a real TLS handshake against the Route, with that file as the only CA. It reads no Secret. See [If the CA rotates](#if-the-ca-rotates).

### Step 2: this is CRC, and there is room

```bash
( set -euo pipefail
  $G gate "$STOP"
  $G preflight --needs 768 | tee "$RUN/preflight.txt"
  oc adm top node | tee "$RUN/top-before.txt"
  oc get pv -o name >"$RUN/pv-before.txt"
); stopped $? 2
```

**Stops when** the API server is not `https://api.crc.testing:6443`; the context is not `<namespace>/api-crc-testing:6443/kubeadmin`; `oc whoami` is not kubeadmin (`kube:admin` or `kubeadmin`); any kind cluster exists; request headroom minus 768 Mi is under 2 GiB; `keycloak-0` or `postgres-0` is not Ready.

### Step 3: nothing is there that this run did not make

```bash
( set -euo pipefail
  $G gate "$STOP"
  left=$(oc get ns cmapi-imports cmapi-system --ignore-not-found -o name)
  left+=$(oc get clusterrole,clusterrolebinding cmapi-reader --ignore-not-found -o name)
  [ -z "$left" ] || { echo "STOP: this run did not make: $left"; exit 1; }
  oc get ns cmapi -o jsonpath='{.metadata.labels}{"\n"}'
); stopped $? 3
```

**Stops when** anything is listed that this run has not made: stop and ask whose it is.

### Step 4: realm `cmapi` does not exist

```bash
( set -euo pipefail
  $G gate "$STOP"
  rc=0; $G issuer || rc=$?
  [ "$rc" = 10 ]
  echo "absent: go on"
); stopped $? 4
```

**Stops on** anything but Keycloak's own 404. A timeout, a certificate failure or a router's 503 is not "absent".

### Step 5: the images, before anything touches Keycloak

```bash
( set -euo pipefail
  $G gate "$STOP"
  IMAGE=$(deploy/crc-image.sh | tail -1)
  PORTAL_IMAGE=$(deploy/crc-image.sh cmapi-portal | tail -1)
  deploy/render.sh crc "$IMAGE" --portal-image "$PORTAL_IMAGE"
  echo "$IMAGE" | tee "$RUN/image.txt"
  echo "$PORTAL_IMAGE" | tee "$RUN/portal-image.txt"
); stopped $? 5
```

**Stops on** a failure of any check in either script. It is finished before any Keycloak step, so its load is never beside an import. Two images, each built from this commit and labelled with it, each in its own image stream: `cmapi` (the api, the worker and the realm sync) and `cmapi-portal` (the front door: nginx with the portal's build and the mockup, `cmapi-portal-ui/Containerfile`). `render.sh` takes each by digest only, each from its own repository. `podman push --cert-dir` is not honoured on this Mac (measured), so `crc-image.sh` pushes with `skopeo`, TLS verified against the ingress CA, with the session's token in a 0600 file and never on an argument.

### Step 6: the environment

Top-level files only. Never `-R` here: `reader/`, `deliverer/` and `realm/` are applied by name, in their own steps.

```bash
( set -euo pipefail
  $G gate "$STOP"
  oc apply --server-side --field-manager=cmapi-wave1 -f "$R/environment/"
); stopped $? 6
```

Writes only to `cmapi` and `cmapi-imports`.

### Step 7: the reader, and the worker's one write with its containment

```bash
( set -euo pipefail
  $G gate "$STOP"
  oc apply --server-side --field-manager=cmapi-wave1 -f "$R/environment/reader/00-cmapi-reader.yaml"
  deploy/crc-reader-import.sh
  oc apply --server-side --field-manager=cmapi-wave1 -f "$R/environment/deliverer/00-cmapi-deliverer.yaml"
); stopped $? 7
```

**Stops when** the token Secret is not filled in 30 tries, or the API refuses the admission policy.

`deliverer/` is the chart's reviewed design for apply delivery on the hub (`deploy/helm/cmapi/templates/rbac.yaml`), held to it by `test_crc_deliverer_is_the_charts`. ClusterRole `cmapi-deliverer` gives the worker's own ServiceAccount `create`, `patch` and `delete` on the kinds cmapi renders, and `bind` on `cmapi-token-issuer` alone: a server-side apply that creates an object needs `create` as well as `patch` ([Kubernetes, Server-Side Apply, "Access control and permissions"](https://kubernetes.io/docs/reference/using-api/server-side-apply/#rbac-and-permissions)). RBAC cannot scope `create` to names that do not exist yet, so ValidatingAdmissionPolicy `cmapi-deliverer-managed-only` is what keeps the worker out of every other project: it may touch only a namespace labelled `cmapi.net/managed=true` (read from the old object on an update, so it cannot label one first), never create a reserved name (`default`, `openshift*`, `kube-*`, `cmapi`, `cmapi-system`, `cmapi-imports`, `ocp-*`, `kubernetes-*`), add or change no `kubernetes.io`, `k8s.io` or `openshift.io` key, and write only the one RoleBinding the renderer writes. The file creates the policy and its binding before the ClusterRole and its binding, so the worker never holds the write without the containment. The api's ServiceAccount gets nothing. Step 23 proves the containment with server dry runs as the worker.

### Step 8: the ServiceAccounts first, with their pull secrets

Admission copies an account's `imagePullSecrets` into a pod when the pod is created, so a pod made before the controller has filled them would never get them (inferred). So wait. The front door runs as the namespace's `default` account, as the chart's does, and pulls `cmapi-portal` from the same registry, so `default` is checked too.

```bash
( set -euo pipefail
  $G gate "$STOP"
  oc apply --server-side --field-manager=cmapi-wave1 -f "$R/components/cmapi/00-serviceaccounts.yaml"
  for sa in cmapi-api cmapi-worker cmapi-jobs default; do
    for _ in $(seq 1 60); do [ -n "$(oc get sa "$sa" -n cmapi -o 'jsonpath={.imagePullSecrets}')" ] && break; sleep 1; done
    [ -n "$(oc get sa "$sa" -n cmapi -o 'jsonpath={.imagePullSecrets}')" ] || { echo "STOP: $sa has no pull secret"; exit 1; }
    echo "$sa: pull secret there"
  done
); stopped $? 8
```

**Stops when** an account has no pull secret after 60 s.

### Step 9: the test users and the new groups in LDAP

```bash
( set -euo pipefail
  $G gate "$STOP"
  examples/cmapi-sso/ldap/apply-test-identities.sh | tee "$RUN/ldap-identities.txt"
); stopped $? 9
```

Before any Keycloak step, because the realm's federation reads these. It writes the ten groups of `cmapi-groups.ldif`, the 13 users of `test-identities.tsv`, and Secret `cmapi-ldap-test-users` in `cmapi`, with passwords only as hashes in LDAP. A second run changes nothing. `docs/11`, "The test users".

**Stops when,** before anything is written: the bind user cannot read `ou=People` or `ou=Groups`; the gate group `app-ssb-autobahnusers` cannot be read; OpenShift's login filter finds nobody, or finds a `cmapi.*` user; a `uidNumber` is held by another entry; an entry with one of these names is not what the script would write, or is a `cmapi.*` user or `app-cmapi-rbac-*` group it does not hold. **Stops when,** after: a digest of every other entry's name and non-password attributes under `ou=People` and `ou=Groups` moved; the gate's members moved; the bind user cannot read the 10 groups and 13 users, or can see a hash; a user cannot sign in to LDAP with the Secret's password. A stop after the write leaves what it wrote, and `apply-test-identities.sh --remove-test-identities` takes exactly that away.

### Step 10: the ten old groups out of LDAP

```bash
( set -euo pipefail
  $G gate "$STOP"
  examples/cmapi-sso/ldap/apply-test-identities.sh --remove-old-groups | tee -a "$RUN/ldap-identities.txt"
); stopped $? 10
```

Each by its full `dn`, from a list in the script: no filter, no `-r`, and it takes no name from outside. A look-alike such as `cn=cmapi-other` stays.

**Stops when** a new group or test user is not there, or is not what step 9 writes; an old name holds anything but a `groupOfNames`, before it deletes any; the digest of everything else moved. A real person who was a member loses `memberOf` for those groups if the server's overlay tracks `member`, which is the removal itself and is left out of the digest. Nothing puts these groups back: the rollback does not. If the listed new entries differ, stop and report their DNs to the directory owner. Have the owner review extra attributes and their ownership before any retry; do not strip attributes or delete entries to force migration.

### Step 11: the Secrets

```bash
( set -euo pipefail
  $G gate "$STOP"
  deploy/secrets.sh --issuer https://keycloak.apps-crc.testing/realms/cmapi --ca-file "$CMAPI_CRC_CA" --test-users
  [ "$(oc get secret cmapi-git-bot -n cmapi -o 'go-template={{if .data.token}}present{{end}}')" = present ] || { echo "STOP: Secret cmapi-git-bot has no token: the owner's step 3"; exit 1; }
); stopped $? 11
```

This writes `cmapi-realm-secrets` in `keycloak`, by name, and `cmapi-keycloak`, `cmapi-keys` and `cmapi-test-users` in `cmapi`, and checks that the owner's `cmapi-git-bot` holds a token, reading no value out. Before minting it asks the realm: a 200 stops it, since a realm exists whose client secrets nobody here knows, and anything but Keycloak's own 404 stops it too. A later run mints nothing, so it does not ask.

### Step 12: the snapshot, and the watch from here to the end

```bash
( set -euo pipefail
  $G gate "$STOP"
  $G snapshot "$RUN/s0.json"
  rm -f "$RUN/watch.log.done"
  nohup $G watch "$RUN/watch.log" "$STOP" "$RUN/s0.json" >"$RUN/watch.out" 2>&1 &
  $G watching "$STOP"
); stopped $? 12
```

**Stops when** a realm does not answer 200, or the watch did not begin. From here the watch runs in the background, with `CMAPI_CRC_CA` exported, and a breach writes `$STOP`. Every later step checks it, and also that the watch is still running and has looked within 120 s: a watch that is killed or hangs writes nothing, and nobody would be looking.

### Step 13: the backup, immediately before the import

```bash
( set -euo pipefail
  $G gate "$STOP"
  deploy/crc-backup.sh
); stopped $? 13
```

**A failed backup stops the run.** See [The backup](#the-backup).

### Step 14: the backup changed nothing

```bash
( set -euo pipefail
  $G gate "$STOP"
  $G snapshot "$RUN/s1.json"
  $G compare "$RUN/s0.json" "$RUN/s1.json"
); stopped $? 14
```

**Stops on** any difference.

### Step 15: the import, alone on the quietest cluster

```bash
( set -euo pipefail
  $G gate "$STOP"
  I=$R/environment/realm/10-realm-import.yaml
  $G headroom --needs 768
  $G check-import "$I"
  rc=0; $G issuer || rc=$?
  [ "$rc" = 10 ]
  oc apply --server-side --dry-run=server --field-manager=cmapi-wave1 -f "$I"
  oc apply --server-side --field-manager=cmapi-wave1 -f "$I"
); stopped $? 15
```

**Stops when** the run is stopped; headroom is under the line; the file names anything but `cmapi`; the realm is not absent; the API refuses `spec.resources`.

If RHBK's Job needs more than the 1 Gi limit, it is killed, the wait in step 16 withdraws it, and the fallback is a pull request deleting the `resources` block: the operator's 1,700 Mi default fits alone at 2,318 Mi left (see [Memory](#memory)).

### Step 16: follow the import

```bash
( set -euo pipefail
  $G import-wait "$STOP" | tee "$RUN/import.txt"
); stopped $? 16
```

| What it sees | Bound | What it does |
|---|---|---|
| Our pod's container not started | 300 s from the apply. An earlier import here waited about 6.5 days | Deletes `KeycloakRealmImport cmapi`, by name |
| The run stopped, not started | At once | The same delete |
| Started, not done | 300 s after start; 79 s measured at this CPU limit | Reports. **Never interrupted** |
| `HasErrors` with a failed pod | At once | The same delete, which stops the Job's further attempts. `HasErrors` alone is not enough: the operator also sets it for an error of its own while a pod runs on (its 26.6.4 source; RHBK's is inferred) |
| A read that fails | Goes on, on what it last knew, to these same bounds | Logged. It does not leave a pending import unfollowed |
| `Done`, realm present | | rc 0, unless the watch stopped the run meanwhile |
| `Done`, realm absent | | Stops |

This step alone starts with no gate, since a stop is what it must act on. It has no bound on a running import, so if it stops without saying `withdrawn` or `Done`, read `oc get keycloakrealmimport cmapi -n keycloak`: an import still there can still start.

### Step 17: nothing else changed, with time for a late restart

```bash
( set -euo pipefail
  $G gate "$STOP"
  oc logs job/cmapi -n keycloak --tail=5 | tee "$RUN/import-log-tail.txt"
  sleep 120
  $G gate "$STOP"
  $G snapshot "$RUN/s2.json"
  $G compare "$RUN/s0.json" "$RUN/s2.json"
); stopped $? 17
```

**Stops on** any difference. 120 s because a restart could lag.

### Step 18: delete the import, keep the realm

The operator's guide says to delete it once the realm is imported. It removes the Job, the pod and the Secret holding the realm's JSON. The realm stays, because no code path in the controller calls Keycloak. Deleting also means it can never start again unattended.

```bash
( set -euo pipefail
  $G gate "$STOP"
  oc delete keycloakrealmimport cmapi -n keycloak
  $G issuer
  echo "realm present"
  $G gate "$STOP"
  $G snapshot "$RUN/s3.json"
  $G compare "$RUN/s0.json" "$RUN/s3.json"
); stopped $? 18
```

**Stops when** the realm is not present afterwards, or on any difference.

### Step 19: the database

```bash
( set -euo pipefail
  $G gate "$STOP"
  $G headroom --needs 672
  oc apply --server-side --field-manager=cmapi-wave1 -f "$R/components/database-cnpg/cluster.yaml"
  oc wait cluster.postgresql.cnpg.io/cmapi-db -n cmapi --for=jsonpath='{.status.phase}'='Cluster in healthy state' --timeout=300s
); stopped $? 19
```

**Stops when** the run is stopped, headroom is under the line, or the database is not healthy.

### Step 20: the realm's mutable parts

The user profile, group mappings, read-only LDAP federation and local test users. Without it `employee_id` never reaches a token. One try and no retries: `requireSync` fails the Job when federation read nobody (#96), and `expectUsers` when it read anything but the 13 test users, which is what `usersFilter` lets it read (#110).

The sync runs before the workloads, so the API never serves a realm that is not complete. The Job needs no API and no database. Its trust file is from step 6, its ServiceAccount from step 8 and its Secrets from step 11. On a realm that was imported before #184 the sync also sets the client attribute for the header `typ: at+jwt`. This run imports a new realm, which has the attribute from the import. [`docs/15`](15-keycloak-integration.md#the-type-of-an-access-token) gives the order of an upgrade.

```bash
( set -euo pipefail
  $G gate "$STOP"
  oc delete job cmapi-realm-sync -n cmapi --ignore-not-found
  oc apply --server-side --field-manager=cmapi-wave1 -f "$R/environment/realm/20-realm-sync.yaml"
  rc=0; oc wait job/cmapi-realm-sync -n cmapi --for=condition=Complete --timeout=600s || rc=$?
  oc logs job/cmapi-realm-sync -n cmapi | tee "$RUN/realm-sync.txt"      # whichever way it ended: the log says why
  [ "$rc" = 0 ]
); stopped $? 20
```

**Stops when** the Job fails, which includes a federation that read nobody, or read anyone but the 13. A failed Job is not Complete, so the wait runs out its 600 s; read the log.

### Step 21: the workloads, the policies first

The two policies go first by themselves: `-R` applies files in name order, `20-api` ahead of `40-networkpolicy`, and "started under the policy" must be true from the first moment. `cmapi-metrics` lets only the front door reach the API's port, and `cmapi-front-door` lets only the router reach the front door.

```bash
( set -euo pipefail
  $G gate "$STOP"
  oc apply --server-side --field-manager=cmapi-wave1 -f "$R/components/cmapi/40-networkpolicy.yaml"
  oc apply --server-side --field-manager=cmapi-wave1 -R -f "$R/components/cmapi" -f "$R/components/portal"
  for d in cmapi-api cmapi-worker cmapi-portal; do oc rollout status "deploy/$d" -n cmapi --timeout=600s; done
); stopped $? 21
```

**Stops when** a rollout is not done.

### Step 22: nothing else changed

```bash
( set -euo pipefail
  $G gate "$STOP"
  $G snapshot "$RUN/s4.json"
  $G compare "$RUN/s0.json" "$RUN/s4.json"
); stopped $? 22
```

### Step 23: the proofs

```bash
( set -euo pipefail
  $G gate "$STOP"
  since=$(head -1 "$RUN/preflight.txt" | cut -d' ' -f1)
  CMAPI_PROOF_SINCE=$since deploy/crc-proof.sh "$R" | tee "$RUN/proof.txt"
); stopped $? 23
```

Then the Chrome proofs in [The issue's proofs](#the-issues-proofs). **Stops at** the first failure. Each call has 15 s, except the
dry-run namespace plan, the API's slowest call, which has as long as the Route gives it: 130 s, `CMAPI_PROOF_PLAN_SECONDS` (#275).

**A restart is the run's from the run's start on (#425).** `CMAPI_PROOF_SINCE` is the time on the first line of step 2's
`preflight.txt`, the run's first record, written before any step writes to the cluster or loads the Mac as step 5's build does (#157).
A container that restarted before it is printed with its pod, count, last termination's time, reason and exit code, and passes:
no step recreates `cmapi-db-1`, so a restart from before the run would otherwise stop every later run (run 24 stopped here on
one from 15:44:56Z, during the host stall of #157). A container running since that time or later, or not running at all, fails, and
so does any pod that is not Ready. A restart is dated by the container's `state.running.startedAt`, "the time at which the container
was last (re-)started" in the [Pod API](https://kubernetes.io/docs/reference/kubernetes-api/workload-resources/pod-v1/#PodStatus)
(read with `oc explain` on CRC, Kubernetes v1.35.6): `lastState` can be empty, and `restartCount` can go back to 0 after a node
restart. Not chosen: restart counts recorded before the rollout and compared after, which is new state and leans on that count; and
checking only the pods the run rolls, which would pass a database restart the run caused (step 19 applies its cluster). A resume
goes on from step 12, so it keeps step 2's time, and a restart since the run first began still fails. The proof compares the Mac's
clock with the node's; they agreed within the second on 2026-11-18 (`Date` of `https://api.crc.testing:6443/version`).

### Step 24: the end of the watch

```bash
( set -euo pipefail
  $G gate "$STOP"
  $G snapshot "$RUN/s5.json"
  $G compare "$RUN/s0.json" "$RUN/s5.json"
  touch "$RUN/watch.log.done"
  for _ in $(seq 1 90); do case "$(tail -1 "$RUN/watch.log")" in *"watch ended"*) break;; esac; sleep 1; done
  last=$(tail -1 "$RUN/watch.log"); echo "$last"
  case "$last" in *"watch ended rc=0") ;; *) echo "STOP: the watch did not end clean"; exit 1;; esac
  oc adm top node | tee "$RUN/top-after.txt"
); stopped $? 24
```

**Stops on** any difference, or a last line that is not `watch ended rc=0`.

### Step 25: delete the backup

Once the run is verified and the coordinator agrees. It is the owner's term.

```bash
( set -euo pipefail
  $G gate "$STOP"
  deploy/crc-backup.sh --delete
); stopped $? 25
```

## The issue's proofs

| Proof | How | Where |
|---|---|---|
| Admitted under `restricted-v2` and started under the policy | Each pod's `openshift.io/scc`, Ready, no container restarted since the run began (step 2's time; a restart before it is printed with its count, last termination time and reason, and passes, #425), `status.startTime` after its policy's `creationTimestamp`: the api and the worker after `cmapi-metrics`, the front door after `cmapi-front-door` | `crc-proof.sh` |
| The front door answers | `/healthz` 200 through the Route, `curl --cacert`; the front door's `imageID` holds the `cmapi-portal` digest | `crc-proof.sh` |
| `/api/v1/version` names the built commit | Through the front door; equals `git rev-parse --short=10 HEAD`; the api's and worker's `imageID` hold the digest | `crc-proof.sh` |
| Only the API's paths reach the API | `/metrics` and `/readyz` through the Route answer the portal's page (`200 text/html`), never the API's metrics or probe | `crc-proof.sh` |
| The headers are the front door's | The portal's page carries `Strict-Transport-Security`, `X-Content-Type-Options: nosniff` and the portal's `Content-Security-Policy` | `crc-proof.sh` |
| The Route through the policies | A Route that answers proves nothing unless something was blocked. A throwaway namespace's pod must reach a control pod in `cmapi` that no policy selects (made for the proof and deleted after), and must be blocked from the api's port and from the front door's: wget's own `download timed out`, what a dropped connection gives on the probe's image (measured), with the instance answering the router straight after each. A bad address, a refused connection or a failed `oc exec` fails the proof, since none of them says anything about the policy. OVN-Kubernetes's documentation describes a drop, not a reset; the first run measures it, and a reset would stop here to be read. Plain HTTP is redirected | `crc-proof.sh` |
| `/docs` signed in, `GET /api/v1/me` | Open `https://cmapi.apps-crc.testing/docs`, Authorize, sign in as local user `ola`, Try it out on `/api/v1/me`, screenshot. Her password goes to the clipboard, never the screen: `oc get secret cmapi-test-users -n cmapi -o 'jsonpath={.data.ola}' \| base64 -d \| pbcopy`. `crc-proof.sh` signs in the client `cmapi-automation` with client credentials, and holds the password grant to `unauthorized_client` | Chrome and `crc-proof.sh` |
| Each test user's token through LDAP federation | Signs in each of the 13 as a browser does (`deploy/oidc-login.py`: the authorization code grant with PKCE through `cmapi-docs`), its password from the Secret on stdin and only to Keycloak's login form, and holds its token against `test-identities.tsv`: exactly those groups and roles, and `employee_id` equal to `uidNumber`. `cmapi.noaccess` gets 403 on `/api/v1/clusters`, where `cmapi.viewer` gets 200. Before it, `LDAP full sync: 200` with `added` 13 in the Job's log | `crc-proof.sh` |
| A login through LDAP federation in a browser | The owner signs in to `/docs` as `cmapi.requester`, Try it out on `/api/v1/me`, screenshot: `/cmapi/app-cmapi-rbac-requester` and `employeeId` 10102. The password goes to the clipboard, never the screen: `oc get secret cmapi-ldap-test-users -n cmapi -o 'jsonpath={.data.cmapi\.requester}' \| base64 -d \| pbcopy` | Chrome |
| The portal on the API, one origin | Open `https://cmapi.apps-crc.testing/`, sign in as `cmapi.requester` (the password as above), screenshot of the requests list. DevTools shows the portal's calls to `/api/v1` on the same origin, with no `Origin` preflight and no CSP violation in the console | Chrome |
| The mockup, captioned as static | `https://cmapi-mockup.apps-crc.testing/portal.html`, screenshot captioned "static mockup, no API behind it" | Chrome |
| The database connections | From the server's side, `pg_stat_ssl`: every `cmapi` connection on TLS. From each container's side: the api and the worker connect with `sslmode=verify-full` (#91). The server cannot see whether a client verified it, so both are read. The migrate containers' proof is `kind-test.sh`'s, on kind | `crc-proof.sh` |
| Prometheus scraping | Thanos Querier's Route, the session's token on stdin: `up` for both targets, and `cmapi_cluster_status` connected. No exec into someone else's pod | `crc-proof.sh` |
| `oc adm top node` before and after | Steps 2 and 24 | Files |
| Only the worker writes, and only inside its policy | The api may not create or patch namespaces or create rolebindings (`oc auth can-i`). Server dry runs as the worker: a namespace labelled `cmapi.net/managed=false` is refused with the policy's own message, one labelled `true` is admitted, and a label on namespace `default` is refused with the same message. A dry run persists nothing | `crc-proof.sh` |
| A plan reads GitHub and writes nothing | `?dryRun=true` for `cmapi-proof-plan` answers 200 with its files, through the GitHub adapter (the API process reads through GitHub's API, #286), the token in `cmapi-git-bot` and the Git trust of `CMAPI_GIT_CA_BUNDLE` (#97); afterwards no namespace `cmapi-proof-plan` | `crc-proof.sh` |
| Kyverno's reports are served to the reader | Discovery as `cmapi-reader`, the Policies tab's premise (#387): the served groups, then `GET /apis/wgpolicyk8s.io/v1alpha2`, which must list `clusterpolicyreports` and `policyreports`, each of which the reader may list in every namespace (`oc auth can-i`); the proof stops otherwise. Without the group the tab reads "Kyverno not installed". Whether `openreports.io` is served (#382) is recorded | `crc-proof.sh` |
| A request delivered | [The full request flow](#the-full-request-flow), in the portal and on the API | Chrome and `oc` |

## The full request flow

Since #157, the owner's decision of 2026-11-15. What changes from Wave 1, all in `deploy/manifests/environments/crc/`:

| File | Setting | Why |
|---|---|---|
| `20-config.yaml` | `clusters.yaml`: CRC `writes: true` | The one cluster takes requests |
| `20-config.yaml` | `instance.git.repository: ephico2real2/cmapi-cluster-configs` | cmapi's own repository. It is not the organisation's `cluster-configs`, which stays as it is |
| `20-config.yaml` | `instance.git`: `url: git@github.com:ephico2real2/cmapi-cluster-configs.git`, `username: cmapi-git-bot`, `hostChecks: false` | The Git layer over SSH with the bot account's key; the token is for the PR alone; no host CI is read and no status is posted (#286, docs/19) |
| `20-config.yaml` | `integrations.yaml`: `delivery.mode: apply` | CRC has no Argo CD. The worker server-side applies the PR branch's folder, confirms it with a read, and only then merges the PR (apply before merge, #286). A delete merges first and is held until an operator's `POST /api/v1/admin/prune:confirm` (`core/sync.py`). The design's mode stays `argocd` (Wave 5) |
| `10-env.yaml` | `CMAPI_GIT_URL: https://api.github.com`, `CMAPI_GIT_CA_BUNDLE: /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem` | GitHub, verified against the image's system trust. `cmapi-trust` and `SSL_CERT_FILE` hold Keycloak's private CA alone, and httpx 0.28.1 honours `SSL_CERT_FILE` for `verify=True`, so without a trust of its own the Git provider could not verify github.com (#97) |
| `deliverer/00-cmapi-deliverer.yaml` | The worker's write, and its containment | Step 7 |

**The path of one request.** A plan reads the namespace's folder on `main` through GitHub's API. On submit, the auto-approval policy `baseline-rnd-namespace` approves a `small` or `medium` namespace in `dev`, and anything else waits for its approvers. Then the worker's jobs, one external effect each (`cmapi/src/cmapi/jobs/delivery.py`):

1. `push_branch`: `git fetch origin main` into the pod's mirror; the folder on `main` must still be the plan's base (else `superseded`); `git worktree add -b cmapi/CRC/<requestId> <workdir>/CRC/<requestId>` from `origin/main`; one commit by `cmapi-git-bot` with the trailers `Cmapi-Request-Id`, `Cmapi-Plan-Hash`, `Cmapi-Approval`, `Cmapi-Requester` and `Cmapi-Instance`; a push of that branch alone.
2. `open_pr`: the PR, as `cmapi-git-bot`.
3. `pr_checks`: kubeconform and the Kyverno bundle on the PR head, the cmapi check, and the merge check (`git merge-tree`, and the folder on `main` against the plan's base).
4. `apply`: `apply_started`, then server-side apply of the branch's folder, confirmed by a read. The request is `applied`.
5. `merge`: the merge check again, then GitHub's merge pinned to the applied head. The request is `synced`.
6. `git_cleanup`: the branch deleted with a lease, and the worktree removed.

Nothing is ever pushed to `main`. A merge that fails after the apply leaves the request in `merge_failed`, with its PR, its branch and the namespace's lock kept, and `CmapiMergeFailed` fires; `:retry` merges it.

**No host checks.** `instance.git.hostChecks` is `false`: cmapi reads no check of GitHub, posts no commit status, and needs no Checks or Commit statuses permission. cmapi's own checks are the gate. `examples/cluster-configs/.github/workflows/ci.yml` can still run on each PR, as a record; cmapi does not wait for it.

**No branch protection (#227).** The repository is private on GitHub's free plan, which refuses branch protection (HTTP 403, "Upgrade to GitHub Pro or make this repository public"). So nothing on GitHub stops a person with write access from pushing to `main` or merging by hand. What holds instead is cmapi's own: the bot pushes only its request branches, each with a lease; the merge check refuses a folder on `main` that is not the plan's base; the merge is pinned to the applied head; and the admission policy keeps the worker out of every namespace not labelled `cmapi.net/managed=true`. A hand edit of a folder on `main` is refused at the next request, not prevented. A hand merge of a cmapi PR is adopted.

**Which test namespaces.** Only cmapi's own: names that start `cmapi-` and are not reserved. Each one is removed by a delete request, approved, then `prune:confirm`.

## Other realms unaffected

**Nothing else deleted or changed.** In `keycloak` the run writes exactly Secret `cmapi-realm-secrets` and `KeycloakRealmImport cmapi`, one named file with one document. It deletes only `keycloakrealmimport cmapi` and, with the flag in [Rollback](#rollback), that Secret. No `--all`, label selector, `--prune` or `oc delete -f` of a directory; `deploy/tests/crc-scripts-test.sh` and `deploy/tests/doc13-test.py` hold that. `check-import` refuses a file whose one document is not exactly `KeycloakRealmImport cmapi`, realm `cmapi`, namespace `keycloak`, Keycloak CR `keycloak`.

**Proof.** `crc-guard.py snapshot` needs no credential. It takes each of `master`, `corp`, `inkcast-prod`, `inkcast-staging`, `tutorial` and any realm another import names, with its HTTP status and the SHA-256 of its `public_key`; each other import's UID, creation time, generation and Done condition; `keycloak-0`'s and `postgres-0`'s UID, container start and restart count; and the Keycloak CR's generation. `compare` stops on any difference and prints the field.

**What it cannot show.** A public key shows a realm was replaced, not that a client inside it changed. A realm no import names is invisible unless listed. Seeing those needs an admin credential, which stays forbidden.

**Watching.** `crc-guard.py watch` polls every realm and `keycloak-0` every 5 s, one timestamped line to `watch.log`. A non-200, a changed key, a changed `keycloak-0` or anything that stops it looking writes the stop file, prints `BREACH`, and goes on logging, so the outage's length is on record. It beats in `$STOP.alive`, and `gate` refuses when that beat's process is gone or the beat is over 120 s old.

## If Keycloak restarts

It can only be bounded, not ruled out: Keycloak has one instance, and the cause of the one measured restart is unknown (exit 143, then failed probes, 35 h after the last import). The import itself should not cause one: 26.6.7's source says "no need to restart Keycloak as we're only importing new realms", while 26.0.8's did restart, and that RHBK's matches is inferred.

1. **Stop at once.** The stop file is there, and every step's `gate` refuses. `import-wait` withdraws our import only if its container has not started. A running import is left to finish.
2. **Take no action on Keycloak:** no delete, no restart, no CR edit, no scale.
3. **Tell the owner immediately,** with `watch.log` and `oc describe pod keycloak-0 -n keycloak`, read-only.
4. **The baseline is 2 min 42 s**, the one measured restart. **At 300 s still unready, the watch prints `REPORT TO THE OWNER NOW`.** That is 1.85 times the only measurement, so a normal restart does not raise it, and it comes well before the kubelet's own limit: the startup probe's `600 x 1 s` would kill and restart the container, doubling the outage.
5. **The run does not resume by itself.** After the owner has heard: snapshot, and compare with `s0`. A new `keycloak-0` start is expected to differ. The realms must not. If the owner says go on: `touch "$RUN/watch.log.done"`, wait for `watch ended` in `watch.log`, `rm -f "$STOP" "$STOP.alive"`, and go on from step 12, which takes a new baseline and a new watch. The same goes for any other stop.

While Keycloak is down, cmapi's own pods hold (read from `auth.py`, `health.py`, `keycloak_admin.py`): issued tokens keep verifying from the cached signing keys, an unknown `kid` is 503 `idp-unavailable`, `/readyz` tests only the database so no pod restarts, and there is no retry storm: one JWKS fetch per pod per 30 s. A new sign-in is impossible, since that is Keycloak's.

## The backup

Approved by the owner on 2026-11-06, as the step immediately before the import. `deploy/crc-backup.sh` is read-only on the server, and it holds every realm's secrets and users.

- **Sign-in.** `pg_dump` runs in the pod, over TCP to the pod's own loopback, as `POSTGRESQL_USER` with `POSTGRESQL_PASSWORD`, each read by the pod's own shell, so it is on no argument list on the Mac or in the pod. Measured on `registry.redhat.io/rhel9/postgresql-16` (PostgreSQL 16.15): the image as it ships trusts both its socket and 127.0.0.1, and with those rules tightened to `peer` and `md5` the socket refuses this user while the password on the loopback still works. A wrong password, an empty variable or another image's variable names stop the backup and leave no file. Whether `postgres-0`'s own rules match the image's is the first run's check: if it cannot sign in, the run stops at this step.
- **Load.** It stops with under 128 Mi of room below `postgres-0`'s limit, or under 5 free connections. `pg_dump` takes ACCESS SHARE locks and one snapshot and does not block readers or writers (PostgreSQL's page); `--lock-wait-timeout=30s` fails rather than queueing behind DDL.
- **The stream.** To stdout, over `oc exec` with no TTY, redirected on the Mac. Nothing is written in the pod. Each check that reads the file back over `oc exec -i` drains its stdin after the check: `pg_restore --list` and `-t` stop at what they need, and CRI-O fails the exec when the process leaves stdin unread (`write |1: broken pipe`, the first run's stop at step 13, #268; that it is only past the pipe buffer is inferred).
- **Storage.** `~/.cmapi-keycloak-backup/`, directory 0700, file 0600, a symbolic link refused, excluded from Time Machine, outside Git. Deleting a file on APFS does not wipe its blocks, and a local snapshot may hold it (inferred).
- **The proof, before the import.** `pg_restore --list` alone is not enough: a file 100 bytes short lists with rc 0 (measured). So, on the pod's own `pg_restore`, with any failure stopping the run and removing the file: non-empty and starting `PGDMP`; `--list` shows table data; `-f /dev/null` reads to the end; the rows of `realm` in the archive equal `select count(*) from realm`.
- **Measured short of CRC:** `deploy/tests/crc-backup-test.sh` runs the script on a real PostgreSQL of that image, with the container runtime's exec standing in for `oc exec`, fails an `exec -i` that leaves any stdin unread, and restores its dump into an empty database, rows the same. `oc` 4.22.18 on a kind cluster, against CloudNativePG's pod: `oc exec` passes the remote status, the dump arrives whole with no TTY, `oc exec -i` reaches EOF on stdin, and a file 100 bytes short fails the full read. The script has not run against `postgres-0`, which is the first run's check.

### Restoring

Never automatic, and no script does it. Restoring rolls **every realm** back to that moment: `corp`, `inkcast-*`, users, clients, keys and sessions, losing anything any project did since. **It is the owner's decision alone, and nothing in cmapi's steps ever triggers it.** Rolling back Wave 1 does not need it. If the owner decides:

1. Say which other projects lose what, and tell them.
2. Stop Keycloak, as the owner: `oc patch keycloak keycloak -n keycloak --type=merge -p '{"spec":{"instances":0}}'`, and wait for `keycloak-0` to go. All realms are now down.
3. Move the current database aside within `postgres-0`, keeping it until the outcome is verified, connected to database `postgres`: `ALTER DATABASE <db> RENAME TO <db>_before_restore; CREATE DATABASE <db> OWNER <owner>;`.
4. Restore into the empty database, from the Mac: `oc exec -i postgres-0 -n keycloak -c postgres -- sh -c 'PGPASSWORD="$POSTGRESQL_PASSWORD" exec pg_restore -w -h 127.0.0.1 --single-transaction -U "$POSTGRESQL_USER" -d "$POSTGRESQL_DATABASE"' < <the file>`. Stop on any error, and rename back. An empty database matters: `--clean` over a changed one leaves a table created after the dump in place (measured).
5. Start Keycloak: `{"spec":{"instances":1}}`. Expect at least 2 min 42 s.
6. Compare with `s0.json`, realm by realm. Keep the file until it agrees. Then drop `<db>_before_restore`, and delete the file.

Step 4 is measured on that image. Steps 2 and 3 have not been run anywhere.

## Rollback

```bash
deploy/crc-rollback.sh --yes
```

It first checks LDAP ownership and measurements without writing or deleting anything. If that preflight fails, stop and report the listed DNs to the directory owner; review any extra attributes and their ownership before retrying. Do not strip attributes or delete entries to force rollback. Once the preflight passes, it removes, each by name, what Wave 1 added, in dependency order. Every delete names one object. The LDAP removal repeats its checks because the preflight does not lock the directory.

**In LDAP** it removes exactly what step 9 added, each by its full `dn`: the 10 `app-cmapi-rbac-*` groups and the 13 test users, then Secret `cmapi-ldap-test-users` by name. It refuses, deleting none, if an entry at one of those names is not what step 9 writes, and it fails if anything else under `ou=People` or `ou=Groups` moved. It restores nothing: the old `cmapi-*` groups stay gone.

**A namespace a request delivered** is a team's, with its workloads, and the rollback names no namespace it did not make. So it stops first, deleting nothing, while any namespace labelled `cmapi.net/managed=true` is there: remove each through a cmapi delete request, approved, then `POST /api/v1/admin/prune:confirm`. It then removes the worker's write before its containment (the ClusterRoleBinding and ClusterRole `cmapi-deliverer`, then the policy's binding and the policy), and Secret `cmapi-git` by name, the name before #286, and `cmapi-git-bot`, `cmapi-git-bot-ssh` and ConfigMap `cmapi-git-bot-known-hosts` by name. The bot's branches and merges in `ephico2real2/cmapi-cluster-configs` stay: the repository is the record.

**Stays, because it was there before Wave 1:** namespace `cmapi` and the Secrets the cluster generated in it, `cmapi-ldap-bind` in both namespaces, every other LDAP entry. Only the label the apply added is removed.

**Stays by design:**

| Left behind | Why | Effect |
|---|---|---|
| Realm `cmapi`, with its federation | Deleting a realm is the owner's call | `GET /realms/cmapi` is 200, not 404. Keycloak polls LDAP for it every 15 min with the read-only bind user, until removed, and now finds nobody |
| `master`'s client `cmapi-realm` | Creating any realm adds it; it goes with the realm | One more client in `master`. No key or other realm changes |
| `cmapi-realm-secrets` in `keycloak` | The authority for the realm's secrets. A rerun copies from it and never mints | One Secret |
| The PV's data | The class is Retain. The script deletes the PV object only if its claim was `cmapi/cmapi-db-1` and it is `Released`; the directory stays on the node (inferred), and cmapi does not write to the node | Disk on the node, a 2 Gi claim |
| The images' blobs | `oc delete imagestream` removes the tags of `cmapi` and `cmapi-portal`; blobs stay until the registry is pruned (inferred) | Registry storage |

**Deleting realm `cmapi` too,** only if the owner asks:

```bash
deploy/crc-rollback.sh --yes --delete-realm --owner-approved
```

It signs in as the realm's own `cmapi-realm-admin` service client, with no master credential, and only `cmapi` is ever in the URL. Measured on Keycloak 26.6.4: 204, the other realms' keys unchanged, `master`'s `cmapi-realm` client gone, and 403 on another realm. RHBK is not measured. If that client cannot sign in, the realm stays and no other credential is tried.

## If the CA rotates

`30-trust.yaml` is in Git on purpose. Argo CD in Wave 5 renders in CI with no cluster access, and `render.sh`'s checksum restarts the api and the worker when the file changes, which a bundle kept only on the cluster would change behind. It holds Keycloak's CA alone: no Wave 1 pod calls an edge Route, and the next CA comes with the wave that needs it (#97). The CA expires on 2036-10-25.

If it rotates anyway, the pods fail closed: JWKS fetches fail, cached keys keep verifying, an unknown `kid` is 503, and `CmapiIdpUnavailable` fires. Verification is never off. Step 1's `--check` fails. Then:

```bash
deploy/crc-trust.sh --write          # asks for ca.crt alone; the API has no field filter, so tls.key reaches oc's memory in that one call, and it is not printed or written
git add deploy/manifests/environments/crc/30-trust.yaml              # a pull request; then render, and apply the environment, then the components
```

## Kyverno

cmapi's chart installs no Kyverno (docs/11). On CRC it is installed once, beside cmapi, so the policy bundle can run in audit mode (#342) and the Policies tab (#302) has reports to show. CRC is shared, so the install sees only namespaces cmapi manages and never refuses a request.

```sh
helm repo add kyverno https://kyverno.github.io/kyverno/
helm install kyverno kyverno/kyverno --version 3.10.0 -n kyverno --create-namespace \
  -f deploy/kyverno/crc-values.yaml --wait --timeout 8m
```

Chart 3.10.0 is Kyverno v1.20.0, the version of the CLI in cmapi's image. What `deploy/kyverno/crc-values.yaml` changes, and why:

| Value | Why |
|---|---|
| `config.webhooks.namespaceSelector`: `cmapi.net/managed In [true]` | The bundle's policies match every Namespace, ResourceQuota and LimitRange and narrow to managed ones inside Kyverno (`core/policygen.py`, `matchConditions`). The selector keeps other projects' requests from reaching Kyverno at all |
| `features.forceFailurePolicyIgnore` | If Kyverno is down, nothing is refused. cmapi's own checks still refuse (#342) |
| `backgroundController` and `cleanupController` off | The bundle has no generate or mutate-existing rules, and cmapi does not use cleanup policies. Fewer pods on a node at 80% memory |
| `runAsUser` and `runAsGroup` null | OpenShift's `restricted-v2` assigns them from the namespace's range and refuses the chart's 65534 ([platform notes](https://kyverno.io/docs/installation/platform-notes/)) |

**Measured on CRC, 2026-11-17** (OpenShift 4.22.14, Kubernetes v1.35.6):

- Both pods ran under `restricted-v2`: `kyverno-admission-controller` and `kyverno-reports-controller`, with no restarts.
- A no-op `ValidatingPolicy` on namespaces, applied and then deleted, got the webhook `vpol.validate.kyverno.svc-ignore`, with failure policy `Ignore` and the `cmapi.net/managed` selector. So the selector applies to the webhooks Kyverno builds per policy.
- Kyverno's only webhook on `*/*` is `protect-generation-labels`. It matches only objects labelled `generate.kyverno.io/policy-name`, and fails open.
- The webhooks that still fail closed cover only Kyverno's own types: policies, exceptions and global context entries.
- Memory, two minutes after start:
  - the admission controller used 54 Mi, with a 128 Mi request;
  - the reports controller used 86 Mi, with a 64 Mi request and a 128 Mi limit;
  - the node went from 80% to 82%.

Background reports follow each policy's own `matchConditions`, not the webhook selector. The probe had none, so it reported on all 87 namespaces until it was deleted. cmapi's policies narrow to managed namespaces.

The install brings no cmapi policy. The platform admin applies cmapi's bundle after it, as the next section says.

**Removal:** `helm uninstall kyverno -n kyverno`. The chart's pre-delete hook removes the webhooks first.

### cmapi's policy bundle on CRC

docs/02 delivers a cluster's policies through a policies Application. It syncs `policies/env/<its environment>/*.yaml` of `cmapi-cluster-configs`. CRC has no Argo CD (#64), and cmapi's worker delivers namespace folders only. `cmapi-deliverer` and its containment policy (step 7) keep the worker to managed namespaces, and it may not create a ValidatingPolicy: `oc auth can-i create validatingpolicies.policies.kyverno.io --as system:serviceaccount:cmapi:cmapi-worker` answers `no`. So the platform admin applies the bundle by hand, the same YAML files Argo CD would sync (#428).

**Who and when.** The platform admin, as kubeadmin, from a checkout of `cmapi-cluster-configs` at the merged commit. Apply it after each pull request that changes `policies/env/dev/` merges, and after each Kyverno install. CRC is in `dev`, so its bundle is `policies/env/dev/`. Name the three YAML files: `-f .` would also send `index.json`, the bundle's index of its checks, which is not a Kubernetes object.

Set `MERGED` to the merge commit of the bundle's pull request, then:

```bash
oc whoami --show-server                      # https://api.crc.testing:6443, as kubeadmin
CCFG="$(mktemp -d)/cmapi-cluster-configs"
gh repo clone ephico2real2/cmapi-cluster-configs "$CCFG" -- --quiet
git -C "$CCFG" checkout --detach "$MERGED"
cd "$CCFG/policies/env/dev"
oc get pods -n kyverno                       # note each pod's RESTARTS
oc apply --server-side --field-manager=cmapi-policies --dry-run=server -f cmapi-metadata-dev.yaml -f cmapi-quota-dev.yaml -f cmapi-limits-dev.yaml \
  && oc apply --server-side --field-manager=cmapi-policies -f cmapi-metadata-dev.yaml -f cmapi-quota-dev.yaml -f cmapi-limits-dev.yaml
```

The server dry run goes through the API server's validation and its admission webhooks, Kyverno's policy webhook among them, which fails closed. The apply runs only when the dry run exits 0 (`&&`), so a policy that Kyverno would refuse stops the step before anything is written. Both commands print 31 ValidatingPolicies. The field manager `cmapi-policies` is the bundle's own, apart from the run's `cmapi-wave1` and the worker's.

An apply prunes nothing. After a bundle change, the cmapi policies of `dev` that the files no longer hold stay on the cluster: this lists them, and each is deleted by its name (`oc delete validatingpolicy.policies.kyverno.io/<name>`). On the first apply it lists none.

```bash
comm -23 <(oc get validatingpolicies.policies.kyverno.io -o name | grep -E '/cmapi-(metadata|quota|limits)-dev-' | sort) \
         <(oc apply --dry-run=client -o name -f cmapi-metadata-dev.yaml -f cmapi-quota-dev.yaml -f cmapi-limits-dev.yaml | sort)
```

**Verify**, in the same folder:

```bash
# 31 policies, each with validationActions [Audit, Warn] and ready: prints "31 policies" and nothing else
oc get validatingpolicies.policies.kyverno.io -o go-template='{{range .items}}{{.metadata.name}} {{.spec.validationActions}} {{.status.conditionStatus.ready}}{{"\n"}}{{end}}' \
  | grep -E '^cmapi-(metadata|quota|limits)-dev-' \
  | awk '{ n++ } !/ \[Audit Warn\] true$/ { print "NOT AUDIT OR NOT READY: " $0 } END { print n + 0 " policies" }'
# each with its file's cmapi.net/policy-digest
diff <(awk '/^  name: /{ n = $2 } /cmapi\.net\/policy-digest:/{ print n, $2 }' cmapi-metadata-dev.yaml cmapi-quota-dev.yaml cmapi-limits-dev.yaml | sort) \
     <(oc get validatingpolicies.policies.kyverno.io -o go-template='{{range .items}}{{.metadata.name}} {{with .metadata.annotations}}{{index . "cmapi.net/policy-digest"}}{{end}}{{"\n"}}{{end}}' | grep -E '^cmapi-(metadata|quota|limits)-dev-' | sort) \
  && echo "digests: the files'"
# no native ValidatingAdmissionPolicy generated from them
oc get validatingadmissionpolicies -o name | grep '/vpol-' || echo "no vpol-* policy"
# the reports, and Kyverno itself
oc get policyreports -A -o custom-columns='NAMESPACE:.metadata.namespace,PASS:.summary.pass,FAIL:.summary.fail,WARN:.summary.warn,ERROR:.summary.error'
oc get clusterpolicyreports -o custom-columns='NAME:.metadata.name,PASS:.summary.pass,FAIL:.summary.fail,WARN:.summary.warn,ERROR:.summary.error'
oc get pods -n kyverno
oc adm top pods -n kyverno
```

- The digests are the render's. `cmapi-tools policies check` holds the files to cmapi's render in the pull request, and the API compares the cluster's digests with its own render. `GET /api/v1/policies/results?clusterId=CRC` (in `/docs`, signed in) must answer, for CRC, `state: ok`, `liveActions: [Audit, Warn]` and `bundle` with `expected`, `live`, `current` and `ready` all 31, `missing`, `differing` and `actionsDiffer` empty, and `actionsDifferTotal: 0`.
- The digests' template reads the annotation under `with`: oc's go-template stops at the first ValidatingPolicy with no annotations (`index of untyped nil`), and another team's policy sorted before `cmapi-` would leave no line of cmapi's to compare.
- A `vpol-*` ValidatingAdmissionPolicy would be Kyverno's native copy of a policy. CRC's admission controller runs `--generateValidatingAdmissionPolicy=true` (read on 2026-11-18). The rendered policies do not ask for one (no `autogenConfiguration`, whose default is off), so none appears.
- Kyverno rescans every resource when a ValidatingPolicy is added (its background report controller, `addVP`). The 10 policies that leave `evaluation` unset, so the background scan is on by Kyverno's default report on the managed namespaces' LimitRanges in `policyreports` and on the Namespaces in `clusterpolicyreports`. The other 21 are admission-only. The Kyverno CLI on the bundle and an export of CRC's 6 managed namespaces (2026-11-18, #428) predicted 84 pass and no fail, warn or error from the scan. That is a prediction, not a measurement on CRC.
- Stop and roll back if a Kyverno pod's RESTARTS rises after the apply, or if `kyverno-reports-controller` goes above 192 Mi, three quarters of its 256 Mi limit. On 2026-11-18 (#428) it used 46 Mi before the bundle, 96 Mi at the first background scan and 88 Mi four minutes later, under the chart's 128 Mi limit then; `deploy/kyverno/crc-values.yaml` now sets 128 Mi requested and 256 Mi limit.

**The Policies tab** then shows CRC with mode `audit`, Bundle running `current`, Policies ready `31 / 31`, the scan's pass count, and the state `ok`. The header reads `0 failing · 0 clusters off the bundle`. `KIND_CMAPI_TEST` is in `rnd` and runs `rnd`'s bundle ("Kyverno and the `rnd` bundle on kind", below, #430).

**Rollback**, from the same checkout:

```bash
cd "$CCFG/policies/env/dev"
oc delete -f cmapi-metadata-dev.yaml -f cmapi-quota-dev.yaml -f cmapi-limits-dev.yaml
```

This deletes the 31 policies by the names in the files, and nothing else. Kyverno drops their results at its next reconcile, and the tab reads CRC off the bundle, `31 missing`, as before.

## Memory

From the manifests, by Kubernetes' rule that a pod's effective request is the larger of the sum of its containers and its largest init container. `test_crc_memory_requests_are_the_planned_576_mi` holds it.

| Pod | Effective request |
|---|---|
| `cmapi-api` | 160 Mi |
| `cmapi-worker` | 128 Mi |
| `cmapi-db-1` | 256 Mi |
| `cmapi-portal` (the front door) | 32 Mi |
| **Steady** | **576 Mi** |

Against 4,018 Mi of headroom (read on 2026-11-06; each step reads it again), with a stop line of 2,048 Mi:

| When | Added | Left | |
|---|---|---|---|
| Import alone, as designed | 768 Mi | 3,250 Mi | The Job ends, and a finished pod no longer counts. 768 Mi is the peak measured for this realm under a 1 Gi limit, about 735 MB, on Keycloak 26.6.4 |
| Import alone, if RHBK refuses `resources` | 1,700 Mi | 2,318 Mi | Passes, so the realm goes first in either case |
| Import plus cmapi, operator default | 2,276 Mi | 1,742 Mi | Under the line. **This order is never run** |
| Steady | 576 Mi | 3,442 Mi | |
| The database plus the realm-sync Job | 352 Mi | 3,666 Mi | Step 20. The Job requests 96 Mi, and it ends before the workloads start |
| Steady plus the realm-sync Job | 672 Mi | 3,346 Mi | What step 19 asks for. It is more than the run uses after the import, because the Job and the workloads do not run together |

## A second cluster: kind

The owner asked on 2026-11-18 for a long-lived kind cluster on this Mac, imported into the CRC instance as docs/02 designs cluster import. The cluster-onboard operation is not built, so `deploy/kind-import/` does the baseline's part by hand, and this pull request is the propose-registry step. First made by OB1 run 22 on 2026-11-18.

| Part | What there is |
|---|---|
| The cluster | kind `cmapi-test` (`KIND_EXPERIMENTAL_PROVIDER=podman`, kind v0.33.0), one node, the node image `kind-test.sh` pins, from `deploy/kind-import/kind-cmapi-test.yaml` |
| Its API server | Published on the Mac's LAN address, `https://192.168.86.110:16443`. Its certificate adds `host.crc.testing` and `192.168.86.110` to kind's names, through a kubeadm `ClusterConfiguration` patch of `apiServer.certSANs` |
| The baseline's part on it | `deploy/kind-import/reader.yaml`: namespace `cmapi-system`, ServiceAccount `cmapi-reader` with no long-lived token Secret, and ClusterRole and binding `cmapi-reader`, with the rules of `environments/crc/reader/` plus `get, list, watch` on nodes (the owner's grant, 2026-11-18) |
| The import, on the hub | Secret `cmapi-imports/cmapi-cluster-kind-cmapi-test`, from `deploy/kind-import/import-secret.py`: labelled `cmapi.net/secret-type: cluster` and `cmapi.net/cluster-id: KIND_CMAPI_TEST`, annotated `cmapi.net/managed-by: cluster-baseline` and `cmapi.net/token-expires-at`. It holds `apiUrl`, a TokenRequest token for `cmapi-system/cmapi-reader` that lasts 7 days, `caData` (kind's CA) and `insecure: "false"`. The token goes from `kubectl create token` to `oc apply -f -` through a pipe alone |
| The registry | `KIND_CMAPI_TEST` in `clusters.yaml`: environment `rnd`, `writes: false` |
| The firewall | pf anchor `com.apple/cmapi-kind`, from `deploy/kind-import/pf-cmapi-kind.conf`: the LAN's traffic to the API port is dropped at `en8` |
| Kyverno and the bundle | Kyverno v1.20.0 (chart 3.10.0, `deploy/kyverno/kind-values.yaml`) and the 31 policies of `rnd`, from `deploy/kind-import/kyverno.sh` (#430, below) |

**Up and down.** `deploy/kind-import/up.sh <cmapi-cluster-configs checkout>` creates the cluster, or reuses it, applies the reader, installs Kyverno and the `rnd` bundle from the checkout (`kyverno.sh`, below), and writes the import Secret with a new token. `deploy/kind-import/down.sh` deletes, each by name, the import Secret and then the cluster, so cmapi retires `KIND_CMAPI_TEST` instead of reading it as unreachable. Both stop before they write anything when `oc` is not CRC's, when `kind-cmapi-test.yaml`, its `certSANs` and the pf anchor do not name one address, when the Mac no longer holds that address (a moved DHCP lease), or when the certificate the API server serves does not name it and `host.crc.testing`. up.sh also stops unless kind's CA verifies `/version`, and before it writes anything unless the checkout's `policies/env/rnd/` is clean at a commit. `deploy/tests/kind-import-test.sh` holds each of these on stubs, and that the token is on no argument list.

**Delete before every deploy.** The owner's rule, 2026-11-18: each CRC deploy runs `deploy/kind-import/down.sh` first, since `crc-guard.py preflight` (step 2) stops on any kind cluster and its message says so, and `kind-test.sh` refuses the taken name. After the run, `up.sh <checkout>` brings the cluster, its Kyverno and bundle, and its import back. cmapi then shows `KIND_CMAPI_TEST` connected at its next relist, within 5 minutes.

**How CRC reaches it.** Red Hat's guide names `host.crc.testing` for a service on the host, and it resolves in CRC's pods to `192.168.127.254`. Connections to it time out here, because CRC's `host-network-access` is off (the default), and turning it on takes a CRC stop and start. gvproxy's outbound NAT does reach the Mac's own LAN address, so the API server is published there, verified against kind's CA. `/version` answered 200 over TLS 1.3 from the `cmapi-api` pod, and CRC's own CA was refused. The owner kept the LAN address and added the firewall (2026-11-18). Turning on `host-network-access` would let `apiUrl` move to `https://host.crc.testing:16443` with no new certificate.

**The firewall.** The owner's decision, 2026-11-18: keep the LAN address, and drop other devices' traffic to it. CRC's gvproxy and this Mac reach the address over the loopback, which the rule does not touch (`route -n get 192.168.86.110` answers `interface: lo0`).

This rule belongs to this lab Mac alone: it is not part of cmapi and ships in no chart, manifest or image. cmapi consumes a network path from the hub to each cluster's API server, which the platform team provides, and it never opens, closes or manages a firewall. A real fleet keeps that path private to the hub (a private network, a VPN or an egress rule on the hub), and the import Secret's `apiUrl` names it.

```bash
sudo pfctl -a com.apple/cmapi-kind -f deploy/kind-import/pf-cmapi-kind.conf   # load the anchor
sudo pfctl -E                                     # enable pf; keep the token it prints
sudo pfctl -a com.apple/cmapi-kind -s rules       # verify: the one block rule
sudo pfctl -s info | head -1                      # verify: Status: Enabled
```

Then `/version` from the `cmapi-api` pod must still answer 200. To undo: `sudo pfctl -a com.apple/cmapi-kind -F all`, then `sudo pfctl -X <token>`. pf's state does not survive a reboot of the Mac, so it is loaded again after one. That a device on the LAN is refused has not been tested from one.

**A moved address.** `down.sh --stale` deletes both even though the address moved. Then put the new address in `kind-cmapi-test.yaml` (`apiServerAddress` and `certSANs`) and in `pf-cmapi-kind.conf`, reload the anchor, and run `up.sh`.

**Why writes are off.** The kind cluster has no GitOps folder and no Argo CD, and this instance delivers by apply on the hub. With `writes: false`, a plan or a request on it gets 422 `cluster-not-writable` before anything is planned (`test_the_kind_cluster_is_rnd_and_never_written`). Reads work.

**Rotation.** The token lasts 7 days, after which the cluster reads `auth_failed`. The baseline's rule is to write a new one at 80% of its life: `up.sh` again, which prints that time. Nothing runs it on a schedule yet.

### Kyverno and the `rnd` bundle on kind

The owner's decision, 2026-11-18 (#430): Kyverno goes on the kind cluster, so `rnd`'s bundle, the 31 policies of `cmapi-cluster-configs` `policies/env/rnd/`, runs on a cluster, and the Policies tab shows `KIND_CMAPI_TEST` on it. Before, its row read "Kyverno not installed" (`state: not-installed`, `bundle: null`), and the bundle ran on no cluster.

`deploy/kind-import/kyverno.sh <checkout>` does it, and `up.sh` runs it after the reader, before the import Secret. Run it alone after a pull request that changes `policies/env/rnd/` merges. In order:

1. It stops before it writes anything unless the checkout's `policies/env/rnd/` is clean at a commit and holds the three files, and unless the kubeconfig's context is `kind-cmapi-test` and its server `https://192.168.86.110:16443`. It never reaches CRC: each kubectl call names kind's kubeconfig, each helm call names it and the context and clears helm's `HELM_KUBE*` variables (`HELM_KUBEAPISERVER`, `HELM_KUBECAFILE` and the rest win over both flags), and it runs no `oc`.
2. `helm upgrade --install` of chart 3.10.0 (Kyverno v1.20.0, the CLI pin) with `deploy/kyverno/kind-values.yaml`, `--wait --timeout 8m`. A failed install stops it before any policy.
3. A server dry run of the three files, with field manager `cmapi-policies`. The apply runs only when the dry run exits 0, and a refused dry run stops the script (`|| die`: in a script under `set -e`, a bare `&&` list that fails does not stop it).
4. It waits until each policy of the files is ready, then prints the count and the commit.

The bundle is read from the checkout, not fetched on each run: the operator chooses the commit, the script prints it and refuses a changed working copy. The chart comes from Kyverno's repository.

`kind-values.yaml` makes CRC's choices ("Kyverno", above): the webhooks scoped to `cmapi.net/managed=true`, `forceFailurePolicyIgnore`, the background and cleanup controllers off, and the reports controller at 128 Mi requested and a 256 Mi limit (CRC's measurement under its bundle, #432). It drops OpenShift's `runAsUser` and `runAsGroup` nulls: kind is plain Kubernetes, so the chart's own security context (65534, non-root) stays.

```bash
CCFG="$(mktemp -d)/cmapi-cluster-configs"
gh repo clone ephico2real2/cmapi-cluster-configs "$CCFG" -- --quiet
git -C "$CCFG" checkout --detach "$MERGED"         # the merge commit of the bundle's pull request
deploy/kind-import/up.sh "$CCFG"                   # or, with the cluster up and imported: deploy/kind-import/kyverno.sh "$CCFG"
```

**Verify**, from the repository's root, then the same folder:

```bash
KC=$PWD/.cmapi-test.kubeconfig; cd "$CCFG/policies/env/rnd"
kubectl --kubeconfig="$KC" get pods -n kyverno     # the admission and reports controllers Running
kubectl --kubeconfig="$KC" get validatingpolicies.policies.kyverno.io -o go-template='{{range .items}}{{.metadata.name}} {{.spec.validationActions}} {{.status.conditionStatus.ready}}{{"\n"}}{{end}}' \
  | grep -E '^cmapi-(metadata|quota|limits)-rnd-' \
  | awk '{ n++ } !/ \[Audit Warn\] true$/ { print "NOT AUDIT OR NOT READY: " $0 } END { print n + 0 " policies" }'
diff <(awk '/^  name: /{ n = $2 } /cmapi\.net\/policy-digest:/{ print n, $2 }' cmapi-metadata-rnd.yaml cmapi-quota-rnd.yaml cmapi-limits-rnd.yaml | sort) \
     <(kubectl --kubeconfig="$KC" get validatingpolicies.policies.kyverno.io -o go-template='{{range .items}}{{.metadata.name}} {{with .metadata.annotations}}{{index . "cmapi.net/policy-digest"}}{{end}}{{"\n"}}{{end}}' | grep -E '^cmapi-(metadata|quota|limits)-rnd-' | sort) \
  && echo "digests: the files'"
kubectl --kubeconfig="$KC" get policyreports -A; kubectl --kubeconfig="$KC" get clusterpolicyreports
```

Then `GET /api/v1/policies/results` on CRC's cmapi must answer, for `KIND_CMAPI_TEST`, `state: ok`, `liveActions: [Audit, Warn]`, `bundle` with `expected`, `live`, `current` and `ready` all 31 and nothing missing or differing, and `counts` with numbers, not null. As with CRC, an apply prunes nothing: after a bundle change, list the `cmapi-*-rnd-*` policies the files no longer hold with the `comm` of "cmapi's policy bundle on CRC", and delete each by name.

**Measured, 2026-11-18** (#430; kind `cmapi-test`, Kubernetes v1.35.8, bundle at `cmapi-cluster-configs` f545841):

- `kyverno.sh` took 3 min 55 s, rc 0: Kyverno installed, the dry run and the apply passed, and 31 policies were ready.
- Both pods Running with no restart. The admission controller failed one startup probe while its certificate was made (`tls: internal error`), then passed.
- 31 ValidatingPolicies `[Audit Warn]` and ready, each with its file's digest, and no `vpol-*` ValidatingAdmissionPolicy. Each policy's webhook fails open (`Ignore`) and selects `cmapi.net/managed=true`.
- No policy report: kind has no namespace labelled `cmapi.net/managed=true`, and every policy narrows to managed objects, so 0 reports is the expected answer.
- Memory (`crictl stats` on the node, at the end): the admission controller 102 MB, the reports controller 54 MB. The kind node's container went from 514 MB to 1.08 GB (`podman stats`).
- CRC's cmapi (`GET /api/v1/policies/results` as `cmapi.operator`): `KIND_CMAPI_TEST` went from `not-installed`, `bundle: null`, to `ok`, `liveActions: [Audit, Warn]`, `bundle` 31 expected, live, current and ready, and `counts` all 0. Each `rnd` policy's counts went from null to 0. CRC's own row did not change.
- The load (#157): the Mac's load average went from 7.46 before to 11.41 at its peak during the install. `keycloak-0` did not restart, and the read-only watch of every realm recorded no breach.

**Rollback**, from the same folder:

```bash
kubectl --kubeconfig="$KC" delete -f cmapi-metadata-rnd.yaml -f cmapi-quota-rnd.yaml -f cmapi-limits-rnd.yaml
env -u HELM_KUBEAPISERVER -u HELM_KUBETOKEN -u HELM_KUBECAFILE -u HELM_KUBEINSECURE_SKIP_TLS_VERIFY -u HELM_KUBETLS_SERVER_NAME \
    -u HELM_KUBEASUSER -u HELM_KUBEASGROUPS -u HELM_KUBECONTEXT \
    helm uninstall kyverno -n kyverno --kubeconfig "$KC" --kube-context kind-cmapi-test
```

The first command deletes the 31 policies by the names in the files, and nothing else. The second removes Kyverno; the chart's pre-delete hook removes its webhooks first. It clears every `HELM_KUBE*` variable, as `deploy/kind-import/common.sh` does: Helm lets `HELM_KUBEAPISERVER` and its peers override `--kubeconfig` and `--kube-context`, so an inherited one could aim the uninstall at another cluster (OB3, PR #433). `down.sh` needs neither: it deletes the whole cluster.

## Trying it without CRC

`deploy/kind-test.sh` runs the components on a `cmapi-test` kind cluster on Podman, and the tests in `.github/workflows/ci.yml`, job `manifests`, hold the rest. Never run a kind cluster during a CRC step: `preflight` stops on one, and `deploy/kind-import/down.sh` deletes the long-lived one (above).

## Not proven before the run

RHBK's Job on `spec.resources`; `restricted-v2`; the internal registry and its pull, of both images; the `cmapi-portal` image's build on this Mac (CI builds it and runs `deploy/tests/front-door-test.py --image` on it); the front door on a cluster: nginx resolving the headless Service `cmapi-api-pods` through the pod's DNS server, the router's `set-forwarded-headers: replace`, and the portal's sign-in through it; OVN-Kubernetes enforcing the policy; the router through it; `ldaps` through Keycloak's truststore on a new realm; user workload monitoring; a real restart's recovery; the backup against `postgres-0` itself; `apply-test-identities.sh` against the real server's rules, memberOf overlay and gate group (`deploy/tests/ldap-identities-test.sh` runs it on the same image, `osixia/openldap:1.5.0`, with rules shaped as the server's and the overlay both ways); what `oc whoami` prints for kubeadmin on this CRC (either form passes). The full request flow (#157): the GitHub adapter against GitHub itself (#61; `test_crc_environment.py` runs CRC's configuration end to end on a fake Git host and a fake cluster); `/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem` in the running image (the image's build stage fetches from github.com with the same base image's system trust, which is inferred evidence); the admission policy on OpenShift, including a server dry run as the worker; a RoleBinding to `cmapi-token-issuer`, which no ClusterRole defines on CRC yet, accepted on the strength of `bind` alone; the repository's Actions reporting `ci/kubeconform` and `ci/kyverno`. `crc-proof.sh` has run only on stubs. The measurements used community Keycloak 26.6.4, since 26.6.7 is not on quay, so that RHBK behaves the same is inferred.
