# #263 and #321: the daily expire_check, and every expiry day a UTC day

Part of story #25 (criteria 2 and 3). Implementer: Opus 5.5 at `high`. The review record goes here when the reviews return.

## What the design says, and what was built

The design is not reopened. These are the lines the code follows.

- docs/01, "Namespace expiration": "The worker notifies the team DL (cmapi.net/team-dl) through the Notifier at 14, 7 and 1
  days. On the date the namespace enters grace: it keeps running, can still be extended, and is flagged on the Expiration tab.
  After grace, cmapi opens a delete request approved by the expired-namespace policy, whose guards are no open request on the
  namespace, not protected, no extension in the last 24 hours, and at least two notices sent. [...] The bot PR removes the
  folder and Argo CD waits for an operator to confirm the prune (awaiting_prune), so data and PVCs are never removed by a
  timer alone."
- docs/02, Worker jobs: "expire_check | Daily | Notices at 14, 7 and 1 days, grace flags, expired-namespace deletes; deletes
  a guard holds are listed for action".
- docs/02, "Held expiry deletes": "When a guard fails (open request, protected, recent extension, too few notices),
  expire_check does not open the delete; it lists the namespace for action and tries again the next day."
- docs/02: "Grace starts on the expiry date, and lasts graceDays including that date", and "Notices send the nearest
  threshold, so a short expiry still gets its 1-day notice."
- docs/01, Data model: `expiration_notices`: "Notices sent per namespace and threshold, grace start, the delete request
  opened; the date itself lives in Git".

Built (`cmapi/src/cmapi/jobs/expire_check.py`): a recurring worker job, daily, that runs `ExpirationRules.expire_check`
(the reference code, unchanged) per cluster on the UTC day, sends each notice once, records the grace once, and opens the
delete after grace through `Pipeline.plan_expiry_delete` and `Pipeline.submit`: the normal delete request.

### The brief's "pending_approval" and the design's "approved by the expired-namespace policy"

The design says the expiry delete is "approved by the expired-namespace policy" when its guards pass; the reference
`approval-rules.yaml` enables that policy for rnd and dev. So the code does not force `pending_approval`: the approval rules
decide, as for every request. When the policy is off, paused (the kill switch) or stopped by a guard, the environment's
`delete` rule asks for approvers and the request is `pending_approval`. Both are tested. Either way nothing is deleted on a
cluster until a bot PR merges and an operator confirms the prune (`awaiting_prune`), which is story #25's criterion 3.

## Choices the design leaves open

| Question | Choice | Why, and the options not taken |
|---|---|---|
| Which day is "today"? | `utc_today()`, one function in `plugins/expiration/rules.py`, used by the planner, the list and the job (#321) | `creationTimestamp` is UTC: metav1.Time marshals with `t.UTC().AppendFormat(buf, time.RFC3339)` (kubernetes/apimachinery `pkg/apis/meta/v1/time.go`, read 2026-11-25). RFC 3339, section 4.1: "true interoperability is best achieved by using Coordinated Universal Time (UTC)". Python's `date.today()` is "the current local date" and `datetime.now(tz)` "is preferred over today() and utcnow()" (docs.python.org/3/library/datetime.html, read 2026-11-25). Rejected: setting `TZ=UTC` on the pods only, which leaves every non-pod host wrong |
| Who is the requester of the expiry delete? | `cmapi-expire-check`, a service identity, not a person; no role check (no token stands behind it) | The design says "cmapi opens a delete request". Rejected: a built-in role on a synthetic identity (a site can redefine `cmapi-requester` in `authz-roles.yaml` and silently stop every expiry delete); a person's identity (that person could not approve it, and it would be false) |
| How is a notice delivered without SMTP? | Recorded in `expiration_notices` with the detail `portal: the Expiration tab`, and counted in `noticesSent` | The same rule as approval prompts (`jobs/channel_notify.py`: "until then every notification is recorded in approval_notifications with channel=portal"). With `notifier.smtp.host`, an email to the team DL through `EmailNotifier`, the Notifier port of `core/ports.py` |
| Several replicas, restarts | One pending `expire_check` (`uq_jobs_pending`), claimed with SKIP LOCKED and a lease; each action in its own transaction, fenced by the lease (`JobRepo.fence`) and locked per namespace (`pg_advisory_xact_lock`), then a re-read of its row | Per-action transactions because SQLAlchemy's `Session.rollback()` "always rolls back the topmost database transaction, discarding any nested transactions that may be in progress" (SQLAlchemy 2.1.8, `orm/session.py`): in one job transaction, `RequestRepo.insert`'s rollback on a lost race would undo the notices already sent. Rejected: a unique index on `expiration_notices` (a migration, and a failed send must be recordable beside a later good one) |
| "No extension in the last 24 hours" | The reference check holds on an extension asked the same UTC day; the delete's fact `lastExtensionHoursAgo` carries whole hours, so the policy's guard reads the real 24 hours | Keeps the reference rules unchanged and gives the approval engine the exact fact |
| When does the next run come? | 24 hours after a complete run; 15 minutes after one that could not finish (a stale cache, a failed email, Git or the cluster down for a delete) | A daily job that fails would otherwise wait a day, and the worker re-enqueues a failed recurring job after its full period |

## Proof

- `cmapi/tests/service/test_expire_check_263.py`: 14 tests. Before the fix (src stashed) each fails: 12 with
  `ModuleNotFoundError: No module named 'cmapi.jobs.expire_check'`, the UTC test with
  `assert '2026-11-25' == '2026-11-26'` (GET /expirations counted the Mac's local date, CST, while the UTC date was the 26th),
  and the timestamp test with `ImportError: cannot import name 'utc_day'`. After: all pass.
- Mutants, each killed by its test: no lock and re-read in the notice (`[7, 7] == [7]`, a duplicate notice from two runs at
  once); the job on `date.today()` (the UTC test); grace recorded only on the date itself (the missed-run test).
- The service tests that compared server dates with the local `date.today()` now use `utc_today()`: on this Mac in the
  evening (UTC is the next day) two of them failed after the fix (`daysLeft` 19 against 20), because they encoded the bug.
