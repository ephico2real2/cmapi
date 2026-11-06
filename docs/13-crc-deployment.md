# Deploying cmapi on CRC (Wave 1)

This is the runbook for the first deployment of cmapi on CRC (OpenShift Local), issue #94. Follow it from the top, in order, in one bash. It is interim: `oc apply` by hand, with the image in CRC's internal registry by digest. Argo CD adopts these objects in Wave 5. There is no real namespace request in this wave, since that needs GitHub (Wave 3) and Argo CD (Wave 5).

**CRC is shared.** Other projects' realms live on the same Keycloak, which has one instance. The owner's requirement (2026-11-06): the other realms must not be affected, `inkcast` and `corp` must not be deleted, and a restart must not bleed long. So each step below has a stop. A stop means stop and report: no retry and no workaround.

**Status of this document.** It has not been run on CRC yet. Everything marked *measured* was measured elsewhere, on community Keycloak 26.6.4, PostgreSQL 16.15, an OpenLDAP stand-in and a kind cluster. See [Not proven before the run](#not-proven-before-the-run). The decisions and their reasons are in [`docs/reviews/2026-11-06-wave1-design/README.md`](reviews/2026-11-06-wave1-design/README.md).

## What this adds to CRC

| Where | What |
|---|---|
| Namespace `cmapi` (exists, holding `cmapi-ldap-bind`) | A label, the workloads, the database, Routes `cmapi-api` and `cmapi-mockup`, the monitoring objects, image stream `cmapi` |
| Namespace `cmapi-imports` (new) | The imports reader Role, Secret `cmapi-cluster-crc` |
| Namespace `cmapi-system` (new) | ServiceAccount `cmapi-reader` and its token Secret |
| Cluster | ClusterRole and ClusterRoleBinding `cmapi-reader`: `get, list, watch` on namespaces, resourcequotas and limitranges, `list` on pods and persistentvolumeclaims |
| Namespace `keycloak` | Secret `cmapi-realm-secrets`, and `KeycloakRealmImport cmapi`, deleted once Done |
| Keycloak | Realm `cmapi`. Creating any realm also adds a client `cmapi-realm` to `master` (measured). That is the one known change outside realm `cmapi` |

In LDAP nothing is written: the realm reads it through the read-only `cmapi-ldap-bind`. See [`docs/11`](11-existing-identity-services.md).

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
| The ten `cmapi-*` LDAP groups | `docs/11`, "The groups" |

### Read-only facts, as read on 2026-11-06

The coordinator read these from CRC. Read them again if much time has passed.

| Question | Answer | Command |
|---|---|---|
| Does RHBK serve `spec.resources` on an import? | Yes. The field's text says "inherited from the Keycloak CR", while the Job measured there requests the operator's 1,700 Mi, so step 13's server dry run is the real check | `oc explain keycloakrealmimport.spec.resources --api-version=k8s.keycloak.org/v2beta1` |
| Can cmapi's pods reach Keycloak? | Yes. `keycloak-network-policy` allows 8443 and 9000 from anywhere | `oc get networkpolicy -n keycloak -o name` |
| Will federation work over this path? | Likely: `corp` uses the same `ldaps://ldaps-ldap-testing.apps-crc.testing:443`, `useTruststoreSpi: always`, `uid`, `inetOrgPerson`, and the truststore `ldap-root-ca` is on the Keycloak CR | `oc get keycloak keycloak -n keycloak -o jsonpath='{.spec.truststores}{"\n"}'` |
| How does the backup sign in? | `postgres-0` runs `registry.redhat.io/rhel9/postgresql-16:latest`, container `postgres`, with `POSTGRESQL_USER`, `POSTGRESQL_PASSWORD`, `POSTGRESQL_DATABASE` from Secret `keycloak-db`, read inside the pod. `pg_dump` and `pg_restore` 16.15. Limit 512 Mi, using 52 Mi | `deploy/crc-backup.sh --inspect`: names and sources, never a value |
| Is an LDAP person's password available? | No. `ldap-structure` holds five hashes and one value that was not printed (#35). So the owner signs in | Below |

### Steps only the owner can take

Both are for the Chrome proofs of step 21, and neither blocks the steps before it.

**1. Trust the two CAs in the login keychain.** Chrome refuses these sites otherwise, and clicking through a warning would be TLS verification off. Neither `LDAP Enterprise Root CA` nor `ingress-operator` is on this Mac (measured with `security find-certificate -c`), and macOS asks for a password to add one, which is why this is the owner's step. After step 1 of the run:

```bash
# One file per certificate, from the bundle step 1 wrote; a second CA trusted by mistake is one more thing that can mint for any site.
cd "$RUN" && awk '/BEGIN CERTIFICATE/{n++} {print > ("crc-ca-" n ".pem")}' crc-ca.pem && cd -
for pem in "$RUN"/crc-ca-*.pem; do
  openssl x509 -in "$pem" -noout -subject -fingerprint -sha1
  security add-trusted-cert -r trustRoot -p ssl -k ~/Library/Keychains/login.keychain-db "$pem"
done
```

Take them out when Wave 1's screenshots are done, by the fingerprints printed above. Each CA can mint a certificate for any site, and both keys live on a test cluster:

```bash
security delete-certificate -Z <sha1 without colons> ~/Library/Keychains/login.keychain-db
```

Not measured: this Mac's trust has not been changed.

**2. Sign in once as an LDAP person,** typing the password into Chrome, so that it reaches nobody else. If that is not wanted, the LDAP login proof is reported as not done.

## The run

Run these in one bash, not zsh, from the repository's root. Keep every output: it goes in `docs/reviews/`, once checked for secret values.

```bash
set -uo pipefail
git status --porcelain; git rev-parse --short=10 HEAD            # nothing printed by the first; the merged commit by the second
RUN=$PWD/deploy/rendered/wave1-run; mkdir -p "$RUN"; R=$PWD/deploy/rendered/crc; STOP=$RUN/stop
G=deploy/crc-guard.py
```

### Step 1: the trust file still verifies Keycloak

```bash
deploy/crc-trust.sh --check && deploy/crc-trust.sh --mac-ca "$RUN/crc-ca.pem" && export CMAPI_CRC_CA=$RUN/crc-ca.pem
```

**Stops when** `30-trust.yaml` no longer verifies Keycloak: a real TLS handshake against the Route, with that file as the only CA. It reads no Secret. See [If the CA rotates](#if-the-ca-rotates).

### Step 2: this is CRC, and there is room

```bash
$G preflight --needs 768 | tee "$RUN/preflight.txt"; echo "preflight rc=${PIPESTATUS[0]}"
oc adm top node | tee "$RUN/top-before.txt"; oc get pv -o name >"$RUN/pv-before.txt"
```

**Stops when** the API server is not `https://api.crc.testing:6443`; the context is not `<namespace>/api-crc-testing:6443/kubeadmin`; `oc whoami` is not kubeadmin (`kube:admin` or `kubeadmin`); any kind cluster exists; request headroom minus 768 Mi is under 2 GiB; `keycloak-0` or `postgres-0` is not Ready.

### Step 3: nothing is there that this run did not make

```bash
oc get ns cmapi-imports cmapi-system --ignore-not-found
oc get clusterrole,clusterrolebinding cmapi-reader --ignore-not-found
oc get ns cmapi -o jsonpath='{.metadata.labels}{"\n"}'
```

**Stops when** anything is listed that this run has not made: stop and ask whose it is.

### Step 4: realm `cmapi` does not exist

```bash
$G issuer; [ $? = 10 ] && echo "absent: go on" || echo STOP
```

**Stops on** anything but Keycloak's own 404. A timeout, a certificate failure or a router's 503 is not "absent".

### Step 5: the image, before anything touches Keycloak

```bash
IMAGE=$(deploy/crc-image.sh | tail -1) && deploy/render.sh crc "$IMAGE" && echo "$IMAGE" | tee "$RUN/image.txt"
```

**Stops on** a failure of any check in either script. It is finished before any Keycloak step, so its load is never beside an import. `podman push --cert-dir` is not honoured on this Mac (measured), so `crc-image.sh` pushes with `skopeo`, TLS verified against the ingress CA, with the session's token in a 0600 file and never on an argument.

### Step 6: the environment

Top-level files only. Never `-R` here: `reader/` and `realm/` are applied by name, in their own steps.

```bash
oc apply --server-side --field-manager=cmapi-wave1 -f "$R/environment/"
```

Writes only to `cmapi` and `cmapi-imports`.

### Step 7: the reader

```bash
oc apply --server-side --field-manager=cmapi-wave1 -f "$R/environment/reader/00-cmapi-reader.yaml" && deploy/crc-reader-import.sh
```

**Stops when** the token Secret is not filled in 30 tries.

### Step 8: the ServiceAccounts first, with their pull secrets

Admission copies an account's `imagePullSecrets` into a pod when the pod is created, so a pod made before the controller has filled them would never get them (inferred). So wait.

```bash
oc apply --server-side --field-manager=cmapi-wave1 -f "$R/components/cmapi/00-serviceaccounts.yaml"
for sa in cmapi-api cmapi-worker cmapi-jobs; do
  for _ in $(seq 1 60); do [ -n "$(oc get sa "$sa" -n cmapi -o 'jsonpath={.imagePullSecrets}')" ] && break; sleep 1; done
  [ -n "$(oc get sa "$sa" -n cmapi -o 'jsonpath={.imagePullSecrets}')" ] && echo "$sa: pull secret there" || echo "STOP: $sa has no pull secret"
done
```

**Stops when** an account has no pull secret after 60 s.

### Step 9: the Secrets

```bash
deploy/secrets.sh --issuer https://keycloak.apps-crc.testing/realms/cmapi --ca-file "$CMAPI_CRC_CA" --test-users
```

This writes `cmapi-realm-secrets` in `keycloak`, by name, and `cmapi-keycloak`, `cmapi-keys` and `cmapi-test-users` in `cmapi`. Before minting it asks the realm: a 200 stops it, since a realm exists whose client secrets nobody here knows, and anything but Keycloak's own 404 stops it too. A later run mints nothing, so it does not ask.

### Step 10: the snapshot, and the watch from here to the end

```bash
$G snapshot "$RUN/s0.json"
nohup $G watch "$RUN/watch.log" "$STOP" "$RUN/s0.json" >"$RUN/watch.out" 2>&1 &
```

**Stops when** a realm does not answer 200. From here the watch runs in the background, with `CMAPI_CRC_CA` exported, and a breach writes `$STOP`. Every later step checks it.

### Step 11: the backup, immediately before the import

```bash
$G gate "$STOP" && deploy/crc-backup.sh
```

**A failed backup stops the run.** See [The backup](#the-backup).

### Step 12: the backup changed nothing

```bash
$G gate "$STOP" && $G snapshot "$RUN/s1.json" && $G compare "$RUN/s0.json" "$RUN/s1.json"
```

**Stops on** any difference.

### Step 13: the import, alone on the quietest cluster

```bash
I=$R/environment/realm/10-realm-import.yaml
$G gate "$STOP" && $G headroom --needs 768 && $G check-import "$I" && { $G issuer; [ $? = 10 ]; } \
  && oc apply --server-side --dry-run=server --field-manager=cmapi-wave1 -f "$I" \
  && oc apply --server-side --field-manager=cmapi-wave1 -f "$I"
```

**Stops when** the run is stopped; headroom is under the line; the file names anything but `cmapi`; the realm is not absent; the API refuses `spec.resources`.

If RHBK's Job needs more than the 1 Gi limit, it is killed, the wait in step 14 withdraws it, and the fallback is a pull request deleting the `resources` block: the operator's 1,700 Mi default fits alone at 2,318 Mi left (see [Memory](#memory)).

### Step 14: follow the import

```bash
$G import-wait "$STOP" | tee "$RUN/import.txt"; echo "import-wait rc=${PIPESTATUS[0]}"
```

| What it sees | Bound | What it does |
|---|---|---|
| Our pod's container not started | 300 s from the apply. An earlier import here waited about 6.5 days | Deletes `KeycloakRealmImport cmapi`, by name |
| The run stopped, not started | At once | The same delete |
| Started, not done | 300 s after start; 79 s measured at this CPU limit | Reports. **Never interrupted** |
| `HasErrors` with a started pod | At once | The same delete, which stops the Job's further attempts |
| `Done`, realm present | | rc 0, unless the watch stopped the run meanwhile |
| `Done`, realm absent | | Stops |

### Step 15: nothing else changed, with time for a late restart

```bash
$G gate "$STOP" && oc logs job/cmapi -n keycloak --tail=5 | tee "$RUN/import-log-tail.txt"
sleep 120; $G gate "$STOP" && $G snapshot "$RUN/s2.json" && $G compare "$RUN/s0.json" "$RUN/s2.json"
```

**Stops on** any difference. 120 s because a restart could lag.

### Step 16: delete the import, keep the realm

The operator's guide says to delete it once the realm is imported. It removes the Job, the pod and the Secret holding the realm's JSON. The realm stays, because no code path in the controller calls Keycloak. Deleting also means it can never start again unattended.

```bash
$G gate "$STOP" && oc delete keycloakrealmimport cmapi -n keycloak
$G issuer; [ $? = 0 ] && echo "realm present" || echo STOP
$G gate "$STOP" && $G snapshot "$RUN/s3.json" && $G compare "$RUN/s0.json" "$RUN/s3.json"
```

**Stops when** the realm is not present afterwards, or on any difference.

### Step 17: the database

```bash
$G gate "$STOP" && $G headroom --needs 672 && oc apply --server-side --field-manager=cmapi-wave1 -f "$R/components/database-cnpg/cluster.yaml" \
  && oc wait cluster.postgresql.cnpg.io/cmapi-db -n cmapi --for=jsonpath='{.status.phase}'='Cluster in healthy state' --timeout=300s
```

**Stops when** the run is stopped, headroom is under the line, or the database is not healthy.

### Step 18: the workloads, the policy first

The policy goes first by itself: `-R` applies files in name order, `20-api` ahead of `40-networkpolicy`, and "started under the policy" must be true from the first moment.

```bash
$G gate "$STOP" && oc apply --server-side --field-manager=cmapi-wave1 -f "$R/components/cmapi/40-networkpolicy.yaml" \
  && oc apply --server-side --field-manager=cmapi-wave1 -R -f "$R/components/cmapi" -f "$R/components/portal"
for d in cmapi-api cmapi-worker cmapi-mockup; do oc rollout status "deploy/$d" -n cmapi --timeout=600s || echo "STOP: $d"; done
```

**Stops when** a rollout is not done.

### Step 19: the realm's mutable parts

The user profile, group mappings, read-only LDAP federation and local test users. Without it `employee_id` never reaches a token. One try and no retries: `requireSync` fails the Job when federation read nobody (#96).

```bash
$G gate "$STOP" && oc delete job cmapi-realm-sync -n cmapi --ignore-not-found \
  && oc apply --server-side --field-manager=cmapi-wave1 -f "$R/environment/realm/20-realm-sync.yaml" \
  && oc wait job/cmapi-realm-sync -n cmapi --for=condition=Complete --timeout=600s
oc logs job/cmapi-realm-sync -n cmapi | tee "$RUN/realm-sync.txt"
```

**Stops when** the Job fails, which now includes a federation that read nobody. A failed Job is not Complete, so the wait runs out its 600 s; read the log.

### Step 20: nothing else changed

```bash
$G gate "$STOP" && $G snapshot "$RUN/s4.json" && $G compare "$RUN/s0.json" "$RUN/s4.json"
```

### Step 21: the proofs

```bash
$G gate "$STOP" && deploy/crc-proof.sh "$R" | tee "$RUN/proof.txt"; echo "proof rc=${PIPESTATUS[0]}"
```

Then the Chrome proofs in [The issue's proofs](#the-issues-proofs). **Stops at** the first failure.

### Step 22: the end of the watch

```bash
$G gate "$STOP" && $G snapshot "$RUN/s5.json" && $G compare "$RUN/s0.json" "$RUN/s5.json"
touch "$RUN/watch.log.done"; sleep 10; tail -1 "$RUN/watch.log"
oc adm top node | tee "$RUN/top-after.txt"
```

**Stops on** any difference, or a last line that is not `watch ended rc=0`.

### Step 23: delete the backup

Once the run is verified and the coordinator agrees. It is the owner's term.

```bash
$G gate "$STOP" && deploy/crc-backup.sh --delete
```

## The issue's proofs

| Proof | How | Where |
|---|---|---|
| Admitted under `restricted-v2` and started under the policy | Each pod's `openshift.io/scc`, 0 restarts, `status.startTime` after the policy's `creationTimestamp` | `crc-proof.sh` |
| `/readyz` 200 | `curl --cacert` through the Route | `crc-proof.sh` |
| `/api/v1/version` names the built commit | Equals `git rev-parse --short=10 HEAD`; the api's and worker's `imageID` hold the digest | `crc-proof.sh` |
| The Route through the policy | A Route that answers proves nothing unless something was blocked. A throwaway namespace's pod must reach the mockup (the control), and must be blocked from the api. `/metrics` is 404 through the Route. Plain HTTP is redirected | `crc-proof.sh` |
| `/docs` signed in, `GET /api/v1/me` | Open `https://cmapi-api.apps-crc.testing/docs`, Authorize, sign in as local user `ola`, Try it out on `/api/v1/me`, screenshot. Her password goes to the clipboard, never the screen: `oc get secret cmapi-test-users -n cmapi -o 'jsonpath={.data.ola}' \| base64 -d \| pbcopy`. `crc-proof.sh` signs in `bot-user` by password grant | Chrome and `crc-proof.sh` |
| A login through LDAP federation | The owner, as an LDAP person; `/me` shows `/cmapi/cmapi-*` groups and `employeeId` equal to `uidNumber`, screenshot. Before it, `LDAP full sync: 200` with `added` above 0 in the Job's log | Chrome |
| The mockup, captioned as static | `https://cmapi-mockup.apps-crc.testing/portal.html`, screenshot captioned "static mockup, no API behind it" | Chrome |
| `pg_stat_ssl` | From the server's side: every `cmapi` connection on TLS. For the migrate container's environment, `kind-test.sh`'s pod by the same steps, if wanted | `crc-proof.sh` |
| Prometheus scraping | Thanos Querier's Route, the session's token on stdin: `up` for both targets, and `cmapi_cluster_status` connected. No exec into someone else's pod | `crc-proof.sh` |
| `oc adm top node` before and after | Steps 2 and 22 | Files |
| Nothing can write | `oc auth can-i` both ways, and a namespace plan with `?dryRun=true` stops at 422 `cluster-not-writable` | `crc-proof.sh` |

## Other realms unaffected

**Nothing else deleted or changed.** In `keycloak` the run writes exactly Secret `cmapi-realm-secrets` and `KeycloakRealmImport cmapi`, one named file with one document. It deletes only `keycloakrealmimport cmapi` and, with the flag in [Rollback](#rollback), that Secret. No `--all`, label selector, `--prune` or `oc delete -f` of a directory; `deploy/tests/crc-scripts-test.sh` and `deploy/tests/doc13-test.py` hold that. `check-import` refuses a file whose one document is not exactly `KeycloakRealmImport cmapi`, realm `cmapi`, namespace `keycloak`, Keycloak CR `keycloak`.

**Proof.** `crc-guard.py snapshot` needs no credential. It takes each of `master`, `corp`, `inkcast-prod`, `inkcast-staging`, `tutorial` and any realm another import names, with its HTTP status and the SHA-256 of its `public_key`; each other import's UID, creation time, generation and Done condition; `keycloak-0`'s and `postgres-0`'s UID, container start and restart count; and the Keycloak CR's generation. `compare` stops on any difference and prints the field.

**What it cannot show.** A public key shows a realm was replaced, not that a client inside it changed. A realm no import names is invisible unless listed. Seeing those needs an admin credential, which stays forbidden.

**Watching.** `crc-guard.py watch` polls every realm and `keycloak-0` every 5 s, one timestamped line to `watch.log`. A non-200, a changed key or a changed `keycloak-0` writes the stop file, prints `BREACH`, and goes on logging, so the outage's length is on record.

## If Keycloak restarts

It can only be bounded, not ruled out: Keycloak has one instance, and the cause of the one measured restart is unknown (exit 143, then failed probes, 35 h after the last import). The import itself should not cause one: 26.6.7's source says "no need to restart Keycloak as we're only importing new realms", while 26.0.8's did restart, and that RHBK's matches is inferred.

1. **Stop at once.** The stop file is there, and every step's `gate` refuses. `import-wait` withdraws our import only if its container has not started. A running import is left to finish.
2. **Take no action on Keycloak:** no delete, no restart, no CR edit, no scale.
3. **Tell the owner immediately,** with `watch.log` and `oc describe pod keycloak-0 -n keycloak`, read-only.
4. **The baseline is 2 min 42 s**, the one measured restart. **At 300 s still unready, the watch prints `REPORT TO THE OWNER NOW`.** That is 1.85 times the only measurement, so a normal restart does not raise it, and it comes well before the kubelet's own limit: the startup probe's `600 x 1 s` would kill and restart the container, doubling the outage.
5. **The run does not resume by itself.** After the owner has heard: snapshot, and compare with `s0`. A new `keycloak-0` start is expected to differ. The realms must not.

While Keycloak is down, cmapi's own pods hold (read from `auth.py`, `health.py`, `keycloak_admin.py`): issued tokens keep verifying from the cached signing keys, an unknown `kid` is 503 `idp-unavailable`, `/readyz` tests only the database so no pod restarts, and there is no retry storm: one JWKS fetch per pod per 30 s. A new sign-in is impossible, since that is Keycloak's.

## The backup

Approved by the owner on 2026-11-06, as the step immediately before the import. `deploy/crc-backup.sh` is read-only on the server, and it holds every realm's secrets and users.

- **Sign-in.** `pg_dump` runs in the pod, over TCP to the pod's own loopback, as `POSTGRESQL_USER` with `POSTGRESQL_PASSWORD`, each read by the pod's own shell, so it is on no argument list on the Mac or in the pod. Measured on `registry.redhat.io/rhel9/postgresql-16` (PostgreSQL 16.15): the image as it ships trusts both its socket and 127.0.0.1, and with those rules tightened to `peer` and `md5` the socket refuses this user while the password on the loopback still works. A wrong password, an empty variable or another image's variable names stop the backup and leave no file. Whether `postgres-0`'s own rules match the image's is the first run's check: if it cannot sign in, the run stops at this step.
- **Load.** It stops with under 128 Mi of room below `postgres-0`'s limit, or under 5 free connections. `pg_dump` takes ACCESS SHARE locks and one snapshot and does not block readers or writers (PostgreSQL's page); `--lock-wait-timeout=30s` fails rather than queueing behind DDL.
- **The stream.** To stdout, over `oc exec` with no TTY, redirected on the Mac. Nothing is written in the pod.
- **Storage.** `~/.cmapi-keycloak-backup/`, directory 0700, file 0600, a symbolic link refused, excluded from Time Machine, outside Git. Deleting a file on APFS does not wipe its blocks, and a local snapshot may hold it (inferred).
- **The proof, before the import.** `pg_restore --list` alone is not enough: a file 100 bytes short lists with rc 0 (measured). So, on the pod's own `pg_restore`, with any failure stopping the run and removing the file: non-empty and starting `PGDMP`; `--list` shows table data; `-f /dev/null` reads to the end; the rows of `realm` in the archive equal `select count(*) from realm`.
- **Measured short of CRC:** `deploy/tests/crc-backup-test.sh` runs the script on a real PostgreSQL of that image, with the container runtime's exec standing in for `oc exec`, and restores its dump into an empty database, rows the same. `oc` 4.22.18 on a kind cluster, against CloudNativePG's pod: `oc exec` passes the remote status, the dump arrives whole with no TTY, `oc exec -i` reaches EOF on stdin, and a file 100 bytes short fails the full read. The script has not run against `postgres-0`, which is the first run's check.

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

It removes, each by name, what Wave 1 added, in dependency order. Every delete names one object.

**Stays, because it was there before Wave 1:** namespace `cmapi` and the Secrets the cluster generated in it, `cmapi-ldap-bind` in both namespaces, every LDAP entry. Only the label the apply added is removed.

**Stays by design:**

| Left behind | Why | Effect |
|---|---|---|
| Realm `cmapi`, with its federation | Deleting a realm is the owner's call | `GET /realms/cmapi` is 200, not 404. Keycloak polls LDAP for it every 15 min with the read-only bind user, until removed |
| `master`'s client `cmapi-realm` | Creating any realm adds it; it goes with the realm | One more client in `master`. No key or other realm changes |
| `cmapi-realm-secrets` in `keycloak` | The authority for the realm's secrets. A rerun copies from it and never mints | One Secret |
| The PV's data | The class is Retain. The script deletes the PV object only if its claim was `cmapi/cmapi-db-1` and it is `Released`; the directory stays on the node (inferred), and cmapi does not write to the node | Disk on the node, a 2 Gi claim |
| The image's blobs | `oc delete imagestream` removes the tags; blobs stay until the registry is pruned (inferred) | Registry storage |

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

## Memory

From the manifests, by Kubernetes' rule that a pod's effective request is the larger of the sum of its containers and its largest init container. `test_crc_memory_requests_are_the_planned_576_mi` holds it.

| Pod | Effective request |
|---|---|
| `cmapi-api` | 160 Mi |
| `cmapi-worker` | 128 Mi |
| `cmapi-db-1` | 256 Mi |
| `cmapi-mockup` | 32 Mi |
| **Steady** | **576 Mi** |

Against 4,018 Mi of headroom (read on 2026-11-06; each step reads it again), with a stop line of 2,048 Mi:

| When | Added | Left | |
|---|---|---|---|
| Import alone, as designed | 768 Mi | 3,250 Mi | The Job ends, and a finished pod no longer counts. 768 Mi is the peak measured for this realm under a 1 Gi limit, about 735 MB, on Keycloak 26.6.4 |
| Import alone, if RHBK refuses `resources` | 1,700 Mi | 2,318 Mi | Passes, so the realm goes first in either case |
| Import plus cmapi, operator default | 2,276 Mi | 1,742 Mi | Under the line. **This order is never run** |
| Steady | 576 Mi | 3,442 Mi | |
| Steady plus the realm-sync Job | 672 Mi | 3,346 Mi | The run's peak |

## Trying it without CRC

`deploy/kind-test.sh` runs the components on a `cmapi-test` kind cluster on Podman, and the tests in `.github/workflows/ci.yml`, job `manifests`, hold the rest. Never run a kind cluster during a CRC step: `preflight` stops on one.

## Not proven before the run

RHBK's Job on `spec.resources`; `restricted-v2`; the internal registry and its pull; OVN-Kubernetes enforcing the policy; the router through it; `ldaps` through Keycloak's truststore on a new realm; user workload monitoring; a real restart's recovery; the backup against `postgres-0` itself; what `oc whoami` prints for kubeadmin on this CRC (either form passes). `crc-proof.sh` has run only on stubs. The measurements used community Keycloak 26.6.4, since 26.6.7 is not on quay, so that RHBK behaves the same is inferred.
