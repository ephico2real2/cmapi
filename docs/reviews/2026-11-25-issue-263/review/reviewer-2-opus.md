# Reviewer 2 (Opus 5.5 high) · cmapi PR #699 · head `9539685`

Every measurement below ran on **PostgreSQL 16.15** (`127.0.0.1:55432`, database `cmapi_r2_699`), from each tree's own
`cmapi/` folder, with `/Users/olasumbo/gitRepos/workbench/cmapi/wt-655-outputs/venv-merged/bin/python` (CPython 3.12.14).
No cluster, no live relay, no repository or GitHub change. Trees in `review-699/`: `r2-head/` (plain head, plus the
measurement file `test_r2_measure_699.py`), `r2-codex/` (head with Codex's `fix.diff`), `r2-work/` (head with my patch),
`r2-check/` (a fresh head with `r2-outputs/fix.diff` applied by `patch -p1 -F0`). Logs are in `r2-logs/`.

Baseline: head's `test_expire_check_263.py` and `test_expirations.py` on PostgreSQL: **33 passed** (`r2-logs/head-baseline.txt`).

## Primary sources (all read 2026-11-25)

| Source | The sentence the decision rests on |
|---|---|
| RFC 8314 §5.3, https://www.rfc-editor.org/rfc/rfc8314.html | "MUAs MUST validate TLS server certificates according to [RFC7817] and PKIX [RFC5280]." |
| RFC 8314 §3 | "this specification now recommends the use of Implicit TLS for POP, IMAP, SMTP Submission, and all other protocols"; §3.3: "clients and servers SHOULD implement both STARTTLS on port 587 and Implicit TLS on port 465 for this transition period" |
| RFC 8314 §1, §4 | MUAs and MSPs "discourage the use of cleartext protocols for mail access and mail submission"; "MSPs SHOULD deprecate the use of cleartext ... Mail Submission Servers as soon as practicable" |
| Python 3.15.2 `smtplib`, https://docs.python.org/3/library/smtplib.html | `SMTP.starttls(*, context=None)`: "Optional context parameter is an ssl.SSLContext object". The page does not say what an omitted context does |
| CPython 3.12.14 `smtplib.SMTP.starttls` (the venv's source, read with `inspect`) | `if context is None: context = ssl._create_stdlib_context()`; and `ssl._create_stdlib_context is ssl._create_unverified_context` → `cert_reqs=CERT_NONE, check_hostname=False` (measured: `verify_mode 0, check_hostname False`) |
| Python 3.15.2 `ssl`, "Security considerations / Best defaults", https://docs.python.org/3/library/ssl.html | "For client use ... it is highly recommended that you use the create_default_context() function ... It will load the system's trusted CA certificates, enable certificate validation and hostname checking" |
| This project, `cmapi/src/cmapi/core/clients/trust.py` docstring, and `docs/reviews/2026-11-18-issue-434/analysis.md` measurement 6 | "the pods point that variable [SSL_CERT_FILE] at cmapi-trust, Keycloak's CA alone, and `ssl.create_default_context()` lets it replace the OpenSSL bundle"; `deploy/manifests/components/cmapi/30-worker.yaml:53` sets `SSL_CERT_FILE=/etc/cmapi/ca/ca-bundle.crt` on the worker |
| RFC 5321 §6.1, https://www.rfc-editor.org/rfc/rfc5321.txt | "When the receiver-SMTP accepts a piece of mail (by sending a "250 OK" message in response to DATA), it is accepting responsibility for delivering or relaying the message." |
| RFC 5321 §4.5.3.2.6 | "A spurious timeout at this point would be very wasteful and would typically result in delivery of multiple copies of the message" |
| Transactional outbox, https://microservices.io/patterns/data/transactional-outbox.html | "The Message relay might publish a message more than once" ... "a message consumer must be idempotent" |
| Argo CD gitops-engine `pkg/sync/sync_context.go` @ `5baed56` (master, 2025-12-17), line 1409 | `if resourceutil.HasAnnotationOption(task.liveObj, common.AnnotationSyncOptions, common.SyncOptionPruneRequireConfirm)`: the prune confirmation is read from the **live** object |
| Argo CD sync options, https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/ | Prune=confirm is set by the resource annotation `argocd.argoproj.io/sync-options`; the page does not say live or Git, hence the source above |
| docs/01 line 556 (head) | "After grace, cmapi opens a delete request approved by the expired-namespace policy, whose guards are no open request on the namespace, not protected, no extension in the last 24 hours, and at least two notices sent ... so data and PVCs are never removed by a timer alone." |
| docs/01 line 557 | "Namespaces are rendered with the Argo CD sync option Prune=confirm, so every namespace delete, by request or by expiry, waits for an operator." |
| docs/02 line 2429 | "When a guard fails (open request, protected, recent extension, too few notices), expire\_check does not open the delete; it lists the namespace for action and tries again the next day." |
| docs/01 line 828 | `expiration_notices`: "Notices sent per namespace and threshold, grace start, the delete request opened" |
| `plugins/namespaces/router.py:251` (#366) | "Protection from the labels in Git, the input of a delete (plan\_delete), not from the live object" |

## Verdicts on Codex's findings

Severity is mine after measuring; "Codex" is Codex's severity.

| # | Codex | Measured on plain head (PostgreSQL) | Verdict | Mine |
|---|---|---|---|---|
| H1 Prune / ownership recheck | High | **Confirmed, narrowed.** Live namespace without `argocd.argoproj.io/sync-options` → head opened `auto:expired-namespace`, reached `awaiting_prune` (`r2-logs/head-measure.txt`). Argo CD reads the option from the live object (gitops-engine line 1409), so a real Argo CD would prune at merge: a timer-only removal, which docs/01 line 556 forbids | **Amend** | High |
| H2 extension across midnight | High | **Confirmed.** Extension asked 23:30 UTC, cancelled; run at 00:30 → head opened a delete, `pending_approval`, `autoFallback: noExtensionInLast24h`. docs/02 line 2429 says the check "does not open the delete" | **Amend** (simpler fix; severity) | Medium |
| H3 SMTP | High | **Confirmed.** Default config: `login` and `send_message` with no `starttls` (clear text). `starttls: true`: `starttls()` with no context → CERT_NONE, no host-name check. Pre-existing in base's `EmailChannel._send`; head moved it into the shared `EmailNotifier` and now sends expiry notices through it | **Amend**: Codex's `ssl.create_default_context()` trusts only Keycloak's CA in the pods (measured: 1 CA with `SSL_CERT_FILE` set, against 187) | High |
| M1 identity collision | Medium | **Confirmed.** A client token `service-account-cmapi-expire-check` with `cmapi-onboarding` cancelled the worker's delete: **200 cancelled** (routers/requests.py:204 compares usernames). Audit and request events record it as `cmapi-expire-check` | **Accept** (status kept at 401; tests rewritten end to end) | Medium (security: spoofing and repudiation) |
| M2 −1 marker unread | Medium | **Confirmed.** Rejected expiry delete → the next day opened `req-…-0003`; two −1 rows for one date | **Accept**, moved under the namespace lock and logged as held | Medium |
| M3 address from snapshot; missing DL counted | Medium | Reading only. A missing DL with SMTP on is recorded as a portal notice, the same rule as SMTP off (the README's recorded choice); Codex's fix makes it never count with SMTP on but count with SMTP off, an inconsistency, and adds a Git read per notice | **Reject** as Medium; Backlog Low B2, B3 | Low |
| M4 send before commit | Medium | **Measured:** a relay that accepts and a worker lost before commit → sent twice, recorded once (`test_m4…`, passes on head). That is at-least-once, the outbox's and RFC 5321's own guarantee, and `jobs/channel_notify.py`'s existing pattern | **Reject** the ledger. Fix only head's docstring, which claimed "a run that stopped half way ... send[s] no notice twice" | Low (doc) |
| M5 relay text persisted | Medium | smtplib's `SMTPAuthenticationError(code, resp)` carries the **server's** reply, never the credentials (CPython `SMTP.login` source); `expiration_notices.detail` is served by no API (only `GET /expirations` reads the table, and only counts) | **Reject** | none |
| M6 `examples/local/app.py` local date | Medium | Reading: correct, the local reference app still calls `date.today()` | **Amend** severity; outside the changed lines → Backlog B1 with Codex's fix | Low |
| L1 `utc_day` OverflowError | Low | **Confirmed**: `OverflowError: date value out of range` | **Accept** (inside the changed lines) | Low |

### H1: what I kept and what I cut

Kept: for the expiry delete only, `Pipeline._plan_delete` must read the live Namespace (an unreadable cluster is re-raised,
so the check is tried again), and `check_prune_confirm` refuses with 409 `prune-confirmation-missing` unless the live
object is `cmapi.net/managed=true` and its `argocd.argoproj.io/sync-options` holds `Prune=confirm`. The job logs it as
`expiry_delete_held` and tries the next day. Person deletes are unchanged.

Cut from Codex's 62 KB:
- The Git-side checks of name, managed, env and sync-options. Argo CD decides the prune from the live object; Git's copy
  does not decide it.
- Refusing protection in either view. #366 decided that protection comes from Git, and head's scan already holds on live
  protection.
- The `cmapi.net/env` filter in the scan and in the plan. The design scopes expiry by the cluster's environment; a label
  filter would silently stop drifted namespaces from expiring.
- The extra stale-list 503. The scan refuses a stale list moments before.

### H2: the simpler fix

Codex added an advisory lock to every `:extend`/`:set` submit, and a check in `Pipeline.submit` keyed on `who is
EXPIRY_REQUESTER`. Both are on a hot shared path and are not needed:
- the one-open-request index (`uq_cr_open_namespace`) already serializes an extension in flight against the delete;
- what is left is an extension that closed: one rejected or cancelled within 24 hours.

My fix stays inside `_open_delete`. Under the namespace lock, it re-reads the namespace's last `:extend`/`:set`
`created_at` and holds the delete when it is less than 24 hours old (`noExtensionInLast24h`, the guard's own name in the
log). The reference rules are unchanged. Severity is Medium, not High: head's delete went to `pending_approval`, so people
and the prune still stood between it and the data.

### H3: the corrected SMTP design

`EmailNotifier`:
- `notifier.smtp.tls` is `starttls` (the default) or `implicit`. `implicit` uses `SMTP_SSL` and defaults to port 465, the
  mode RFC 8314 §3 recommends.
- The context is the project's `trusted_context()`: PROTOCOL_TLS_CLIENT, so CERT_REQUIRED and the host name checked, over
  the image's system store and `CMAPI_TRUSTED_CA_FILE`. The pods' `SSL_CERT_FILE` (Keycloak's CA alone) does not narrow it.
- TLS comes before the login and the message. A relay without STARTTLS raises `SMTPNotSupportedError` and gets nothing.
- `starttls: false` or an unknown `tls` raises `ValueError` before any socket.
- A failed QUIT after the relay accepted DATA is not a failure (RFC 5321 §6.1). Head's `with smtplib.SMTP(...)` raised from
  `__exit__` on a non-221 QUIT reply, so the notice was recorded as failed and sent again.
- The approval email channel goes through the same class.

Cut from Codex: `ssl.create_default_context()` and the `EmailDeliveryUnknown` classification.

### M4: why "hold ambiguous deliveries for reconciliation" is not right here

Codex's change was not run on PostgreSQL by Codex. Its design:
- commits an "unconfirmed" row;
- sends in a second transaction;
- on an ambiguous outcome, leaves the row unconfirmed, never resends it and never counts it;
- docs/18 then tells operators to edit `expiration_notices` rows by hand after reading the relay log.

The cost: one lost reply turns into a **permanently held expiry delete** (`noticesSentAtLeast2` can never be met for that
threshold) and a manual database procedure. The gain: one duplicate email avoided.

The standard pattern goes the other way:
- the transactional outbox accepts at-least-once ("The Message relay might publish a message more than once");
- RFC 5321 §4.5.3.2.6 names duplicate copies as the normal result of a lost reply;
- the project's own approval notifier (`channel_notify`) fences, sends and records in one transaction.

So: keep head's at-least-once, state it in the docstring and docs/18, and pin it with a characterization test.

## What Codex missed

1. **Codex's own TLS fix breaks mail in the deployed pods (High, in its fix).** `ssl.create_default_context()` honours
   `SSL_CERT_FILE`, and the worker manifest sets it to Keycloak's CA alone (`30-worker.yaml:53`; #434 measurement 6).
   Measured: with `SSL_CERT_FILE` set to a one-certificate file, `create_default_context()` holds **1** CA and
   `trusted_context()` holds **187**. Every relay signed by a public or corporate CA would fail verification, and every
   notice would fail. Codex's test cannot catch it, because it checks only `isinstance(SSLContext)`, `check_hostname` and
   `CERT_REQUIRED`. Mine asserts `context is trusted_context()`.
2. **No implicit TLS.** RFC 8314 §3 recommends implicit TLS for submission, and §3.3 says to implement both. Codex allowed
   only STARTTLS, so a relay on port 465 alone could not be used.
3. **Argo CD decides `Prune=confirm` from the live object, not Git** (gitops-engine line 1409). Codex checked both views
   without that source. The live check is the one that holds; I cut the Git half.
4. **Codex's M2 return path was silent.** `_open_delete` returned `True` with no log when the marker existed, so a rejected
   expiry was not "listed for action" (docs/02 line 2429). Mine raises 409 `expiry-delete-already-opened` inside the
   locked transaction, which logs `expiry_delete_held` and counts `delete_held` each day.
5. **Head's docstring overclaimed exactly-once** ("a run that stopped half way ... send no notice twice"). Corrected to
   at-least-once, with the sources.
6. **Codex's M4 design makes the delete guard unsatisfiable** after one ambiguous send. Its `docs/18` change asked
   operators to hand-edit database rows. See M4 above.
7. **Severity.** H2 is Medium: its outcome was `pending_approval`, not an unattended delete. M5 is no finding. M6 is Low.

## Backlog (Low, outside the changed lines or not a defect of this PR; no fix)

- **B1** `examples/local/app.py:265-270, 316, 406` still use `date.today()` for the local reference app's expiry planner and
  request IDs. Codex's four-line fix and its `tests/core/test_expiry_reference_699.py` are ready in `r1-outputs/fix.diff`.
- **B2** `_notice` addresses the notice from the live `cmapi.net/team-dl`, so it lags Git by one sync. Reading Git per
  notice would be a Git read per row, which GET /expirations deliberately avoids.
- **B3** With SMTP on, a namespace with no `cmapi.net/team-dl` gets a portal notice that counts toward
  `noticesSentAtLeast2`. That is consistent with the SMTP-off rule in the README's choices table. The owner may want to
  decide it explicitly; record the answer in the README.
- **B4** Head's scan reads protection from live labels, while #366 names Git as the source for deletes. It is conservative,
  because both are checked before a delete opens, but it should be noted in the README's choices.

## The final patch

`r2-outputs/fix.diff`: 10 files, 37 KB, 590 lines; versus Codex's 14 files and 62 KB. It applies to a fresh copy of
`head/` with `patch -p1 -F0` (all 10 files), and the result is identical to `r2-work/`.

| File | Change |
|---|---|
| `core/channels.py` | `EmailNotifier`: verified TLS by `trusted_context()`, `tls: starttls\|implicit`, refusal of clear text, QUIT after acceptance |
| `core/identity/claims.py`, `core/identity/checks.py` | `EXPIRY_NAME`, `is_reserved`; 401 for a token, `unknown-user` for a directory entry |
| `core/pipeline.py` | `check_prune_confirm` on the live object for the expiry delete; `EXPIRY_REQUESTER` from `EXPIRY_NAME` |
| `jobs/expire_check.py` | Under the namespace lock: the −1 marker, and the 24-hour extension by the clock; `LeaseLost` stops the run; at-least-once docstring |
| `plugins/expiration/rules.py` | `utc_day` returns None on `OverflowError` |
| `tests/service/test_expire_check_263.py` | +6 PostgreSQL tests (9 cases) |
| `tests/service/test_expiry_review2_699.py` | New: 15 cases, no database |
| `docs/18-configuration.md`, `deploy/helm/cmapi/values.yaml` | `notifier.smtp.tls`, the hold rules, at-least-once |

### PostgreSQL results

| Run (PostgreSQL 16.15, `cmapi_r2_699`) | Result | Log |
|---|---|---|
| Plain head: `test_expire_check_263.py` + `test_expirations.py` | 33 passed | `r2-logs/head-baseline.txt` |
| Plain head: my measurements (`test_r2_measure_699.py`) | H1, H2, M1, M2 fail as findings; M4 at-least-once measured | `r2-logs/head-measure.txt` |
| **Before**: plain head with my new tests (24 cases) | **23 failed**; 1 passed, the at-least-once characterization, which is meant to pass on both | `r2-logs/head-new.txt` |
| **After**: patched tree, the same selection | **25 passed** (the 24 cases plus one existing worker test matched by `-k`) | `r2-logs/work-new.txt` |
| Patched tree, 13 affected service files (expiry, expirations, email links, protected, delete dry run, idempotency, authz, flow, expiry reviews 322 and 479, API samples) | **162 passed** | `r2-logs/work-affected.txt` |
| **Fresh head plus `r2-outputs/fix.diff`**: `test_expire_check_263.py`, `test_expiry_review2_699.py`, `test_expirations.py` | **57 passed** | `r2-logs/check-final.txt` |
| Reference suite `tests/core`, head and patched (`wt-689-outputs/venv-ref` is absent, as Codex found; `venv-merged` used) | 753 passed, 113 skipped on both | `r2-logs/work-core.txt` |
| Codex's tree (`r2-codex/`) on PostgreSQL, for the record: its 4 database tests now run | 70 passed. Its fix works under test; my objections are its trust store (measured: 1 CA under the worker's `SSL_CERT_FILE`, against 187 for mine) and its delivery-ledger design, not crashes | `r2-logs/codex-pg.txt` |

Which tests fail on head, and why (`r2-logs/head-new.txt`):

| Area | Cases | Reason on head |
|---|---|---|
| Prune=confirm | 1 | Delete opened |
| Midnight extension | 1 | Delete opened |
| Rejected expiry | 1 | Reopened as `req-…-0003` |
| Look-alike identity | 4 | `service-account-cmapi-expire-check` and `cmapi-expire-check`: 200 cancelled. The mixed-case name and the reserved `sub`: 403 instead of 401 |
| Lease loss | 1 | `DID NOT RAISE LeaseLost`, with an `expire_check_failed` error logged for each later namespace |
| SMTP | 11 | No `starttls` call, or a `None` context; no refusal; a QUIT failure raised |
| Directory attribution | 3 | `DID NOT RAISE Problem` |
| `utc_day` | 1 | `OverflowError` |

### The coordinator applies

`cd <checkout> && patch -p1 -F0 < /Users/olasumbo/gitRepos/workbench/cmapi/review-699/r2-outputs/fix.diff`. Then add to the
PR record:
- the Backlog items B1 to B4;
- the M4 decision: at-least-once, with its sources.
