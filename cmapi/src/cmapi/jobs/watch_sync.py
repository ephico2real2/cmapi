"""watch_sync: the request is merged. Deliver (apply mode), wait for Argo CD (argocd mode), or wait for whatever
applies Git main (gitops mode, #751), then confirm by a read of the full plan; a delete stops in awaiting_prune.
Re-enqueues itself every poll interval until synced, or sync_failed after the timeout; a gitops change whose only
differences are objects its deliverer did not prune goes to awaiting_prune instead. prune: in apply mode an operator
confirmed, so remove the namespace; in every mode, confirm by a read that what the plan removes is gone."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from cmapi.core.clients.kube import BadResponse, ClusterUnreachable, KubeError
from cmapi.core.context import AppContext
from cmapi.core.db.models import JobRow
from cmapi.core.db.repo import JobRepo, RequestRepo
from cmapi.core.errors import Problem
from cmapi.core.git.base import GitUnavailable, as_plan
from cmapi.core.lifecycle import Event as E, State as S
from cmapi.core.observability import LEAD_TIME, log
from cmapi.core.render.manifests import folder
from cmapi.core.sync import (ApplyDelivery, ArgoCdSignal, PlanRead, Unreadable, application_name, confirmed_by_read,
                             deliverer_signal, not_synced, read_plan)
from cmapi.jobs.delivery import ADOPTION_STALE, adoption_stored, adoption_writes


def _deliverer(ctx: AppContext, cluster_id: str):
    """The write identity for apply delivery: the worker's own ServiceAccount on the hub (the one
    cluster CRC has), or a per-cluster deliverer Secret when one is mounted."""
    from pathlib import Path

    from cmapi.core.clients.kube import KubeClient
    from cmapi.core.clients.trust import require_https

    if ctx.deliverer_factory is not None:
        return ctx.deliverer_factory(cluster_id)
    s = ctx.settings
    secret_dir = Path(f"/etc/cmapi/deliverer/{cluster_id}")
    if (secret_dir / "token").exists():
        api_url = (secret_dir / "apiUrl").read_text().strip()
        require_https(api_url, str(secret_dir / "apiUrl"))
        ca = secret_dir / "ca.crt"
        return KubeClient(cluster_id, api_url, (secret_dir / "token").read_text().strip(),
                          str(ca) if ca.exists() else None)
    if s.kube_token_file.exists():
        require_https(s.kube_api_url, "CMAPI_KUBE_API_URL")
        return KubeClient(cluster_id, s.kube_api_url, s.kube_token_file.read_text().strip(),
                          str(s.kube_ca_file) if s.kube_ca_file.exists() else None)
    raise RuntimeError(f"no deliverer credential for {cluster_id}")


def _mode(ctx: AppContext, cluster_id: str) -> str:
    st = ctx.registry.get(cluster_id)
    return (st.policy.delivery if st.policy and st.policy.delivery else ctx.delivery.mode)


def _managed(obj: dict | None) -> bool:
    return ((obj or {}).get("metadata", {}).get("labels") or {}).get("cmapi.net/managed") == "true"


# Who a move is recorded by, in each mode.
ACTOR = {"apply": "cmapi-deliverer", "argocd": "argocd", "gitops": "gitops"}


# The kinds the reader may list in a namespace but not get (deploy/manifests/environments/crc/reader, #748).
_LISTED = ("ServiceAccount", "RoleBinding")


def _live(cache):
    """read_plan's Getter on a watch cache: the cached object, else a direct read of the reader. A read of one object that
    fails is Unreadable, never an absence; a cluster that cannot be read raises ClusterUnreachable, a wait (#751, D2)."""
    def get(kind: str, ns: str | None, name: str):
        hit = cache.get(kind, ns, name) if kind in cache.kinds else None
        if hit is not None:
            return hit
        try:
            if kind in _LISTED:
                # One list of the namespace, unpaged: without `limit` the API server answers in one response.
                return next((o for o in cache.client.list(kind, namespace=ns)["items"]
                             if (o.get("metadata") or {}).get("name") == name), None)
            return cache.client.get_object(kind, ns, name)
        except (KubeError, BadResponse, KeyError) as exc:       # KeyError: a kind the reader has no path for (RESOURCES)
            raise Unreadable(str(exc) or type(exc).__name__) from exc
    return get


def _rules(ctx: AppContext) -> dict:
    """read_plan's skip rules from this instance's files: liveOnlyKeys (metadata-keys.yaml) and the D3 skip prefixes
    (adoption.yaml)."""
    return {"live_only": ctx.cfg.metadata.live_only, "skip_prefixes": ctx.cfg.adoption.skip_prefixes}


def _reader_cache(ctx: AppContext, cluster_id: str):
    """The watch cache; a cluster whose import is not connected is something to wait for, not a job failure."""
    try:
        return ctx.registry.cache(cluster_id)
    except Problem as exc:
        raise _NotYet(exc.detail) from exc


def watch_sync(ctx: AppContext, s: Session, job: JobRow) -> None:
    repo, jobs = RequestRepo(s), JobRepo(s)
    row = repo.get(job.request_id)
    if row.status not in (S.MERGED.value, S.SYNC_FAILED.value):
        jobs.done(job)
        return
    # A :retry restarts the clock; the merge time would leave it one attempt.
    retried = (job.payload or {}).get("since")
    since = datetime.fromisoformat(retried) if retried else (row.merged_at or row.updated_at or datetime.now(timezone.utc))
    waited = (datetime.now(timezone.utc) - since).total_seconds()
    files = {p: t for p, t in row.plan["files"].items() if t is not None}
    removed = {p: row.plan["prev"][p] for p, t in row.plan["files"].items() if t is None and p in row.plan.get("prev", {})}
    mode = _mode(ctx, row.cluster_id)
    if row.action == "delete":
        if row.status == S.MERGED.value:
            note = ("waiting for the deliverer to remove the namespace; a read of its absence ends the request, and a "
                    "deliverer that does not prune waits for an operator to remove it" if mode == "gitops"
                    else "Prune=confirm: waiting for an operator to confirm the prune")
            repo.move(row, E.PRUNE_PENDING, ACTOR[mode], note)
        jobs.done(job)
        if mode in ("argocd", "gitops"):
            # The confirmation happens in the deliverer, with no call to cmapi: only a watch of the namespace ends the request.
            jobs.enqueue("prune", request_id=row.request_id, cluster_id=row.cluster_id, delay=ctx.delivery.poll_seconds)
        return
    try:
        if mode == "apply":
            # A folder that holds a name or text that is not UTF-8 is never the plan's: as_plan reads it as False (#626).
            if not as_plan(lambda: ctx.git.read_folder(folder(row.cluster_id, row.namespace))[0] == files):
                return _refuse(repo, jobs, row, job, "Git main's folder differs from the approved plan; nothing applied")
            d = ApplyDelivery(_deliverer(ctx, row.cluster_id))
            writes = files
            if adoption_stored(row) is not None:
                # An approved adoption writes only the objects its plan read, unchanged since but by cmapi's own write
                # (story #26, D16); a namespace that is gone, or managed by another write, is refused too.
                try:
                    found, writes = adoption_writes(ctx, row, files, resuming=True)
                except Problem as exc:                    # live_objects: the cluster did not answer
                    raise ClusterUnreachable(exc.detail) from exc
                if found is not None:
                    return _refuse(repo, jobs, row, job, f"{ADOPTION_STALE}: {found.detail}; nothing applied")
            else:
                live = d.client.get_object("Namespace", None, row.namespace)
                if live is not None and not _managed(live):
                    # The plan-time check is hours old by now. Server-side apply with force would take it over.
                    return _refuse(repo, jobs, row, job, f"{row.namespace} exists on the cluster and cmapi does not manage it; nothing applied")
            jobs.fence()
            n = d.apply_folder(writes)
            if removed:
                from cmapi.core import kube_yaml

                # A file rename removes a path, not the Kubernetes objects retained in another file.
                def identity(doc):
                    meta = doc["metadata"]
                    return doc["kind"], meta.get("namespace", row.namespace), meta["name"]

                retained = {identity(doc) for text in files.values() for doc in kube_yaml.load_all(text)}
                obsolete = {}
                for path, text in removed.items():
                    docs = [doc for doc in kube_yaml.load_all(text) if identity(doc) not in retained]
                    if docs:
                        obsolete[path] = kube_yaml.dump_all(docs, sort_keys=False)
                d.prune_objects(row.namespace, obsolete)
            repo.event(row, "applied", "cmapi-deliverer", f"server-side applied {n} objects from Git {row.merge_sha[:8] if row.merge_sha else 'main'}")
        elif mode == "gitops":
            # Whatever applies the folder applies main: a folder that is not the plan cannot reach the cluster as approved,
            # so a later change of it is refused at once, as in argocd mode (#751, D3 step 1; D7).
            if not as_plan(lambda: ctx.git.read_folder(folder(row.cluster_id, row.namespace))[0] == files):
                return _refuse(repo, jobs, row, job, "Git main's folder differs from the approved plan")
        else:
            # Three things must hold before a read can confirm: Git main still carries the approved plan (a later
            # change to the folder is a new request, not this one), Argo CD has compared a revision at or after the
            # merge (status.sync.revision is the head of main, so a later merge moves it), and this folder's own objects
            # are Synced (the Application's status covers every namespace, so a neighbour's pending prune says nothing).
            if not as_plan(lambda: ctx.git.read_folder(folder(row.cluster_id, row.namespace))[0] == files):
                return _refuse(repo, jobs, row, job, "Git main's folder differs from the approved plan")
            st = ctx.registry.get(row.cluster_id)
            reader = st.client                  # once: `_set` or the relist may clear it between a check and a use (#402)
            if reader is None:
                raise ClusterUnreachable(f"{row.cluster_id} is {st.status}")
            app = ArgoCdSignal(reader, ctx.delivery.argocd_namespace,
                               application_name(ctx.delivery.argocd_root_application, row.cluster_id, row.namespace)).status(row.cluster_id)
            observed = app.revisions or (frozenset({app.revision}) if app.revision else frozenset())
            repo.event(row, "argocd", "argocd", f"{app.sync} {app.health} at {','.join(sorted(r[:8] for r in observed)) or '?'}")
            # A merged request with no merge sha has nothing to compare: it fails closed, not open.
            if not row.merge_sha or not any(ctx.git.contains(r, row.merge_sha) for r in observed):
                raise _NotYet(f"Argo CD compared {sorted(r[:8] for r in observed)}, none holding {(row.merge_sha or 'an unknown merge')[:8]}")
            waiting = not_synced(app, files, row.plan.get("prev") or {})
            if waiting:
                raise _NotYet(f"Argo CD reports {waiting[:3]}")
        cache = _reader_cache(ctx, row.cluster_id)
        previous = row.plan.get("prev") or {}
        if mode == "gitops":
            found = read_plan(_live(cache), row.namespace, files, previous, **_rules(ctx))
            if not found.ok:
                raise _Differs(found, deliverer_signal(cache.client, ctx.delivery, row.cluster_id, row.namespace))
            why = found.summary()
        else:
            ok, why = confirmed_by_read(_live(cache), row.namespace, files, previous, **_rules(ctx))
            if not ok:
                raise _NotYet(why)
    except (_NotYet, ClusterUnreachable, KubeError, GitUnavailable) as exc:
        if waited > ctx.delivery.sync_timeout_seconds:
            if isinstance(exc, _Differs) and exc.found.only_removals:
                return _await_prune(ctx, repo, jobs, row, job, exc)
            if isinstance(exc, _Differs):
                # Every difference in the event's detail (request_events.detail, docs/16); the move's note names the first ones.
                repo.event(row, "sync_differences", "worker", str(exc)[:500],
                           {"differences": [d.view() for d in exc.found.differences], "signal": exc.signal})
            if row.status == S.MERGED.value:
                repo.move(row, E.SYNC_TIMEOUT, "worker",
                          f"not synced after {int(waited)} s: {str(exc)[:500 if isinstance(exc, _Differs) else 160]}")
            jobs.done(job)
            return
        repo.event(row, "sync_wait", "worker", str(exc)[:500 if isinstance(exc, _Differs) else 200])
        jobs.retry(job, str(exc)[:300], ctx.delivery.poll_seconds)
        job.attempts = 0                                  # waiting is not a failure
        return
    repo.move(row, E.SYNCED, ACTOR[mode], f"confirmed by a read: {why}")
    approval = "auto" if (row.requirement or {}).get("auto") else "human"
    LEAD_TIME.labels(row.plugin, row.action, approval).observe((datetime.now(timezone.utc) - row.created_at).total_seconds())
    jobs.done(job)


def _refuse(repo: RequestRepo, jobs: JobRepo, row, job: JobRow, why: str) -> None:
    """A delivery that must not happen: no retry can make it right, an operator looks at the request."""
    if row.status == S.MERGED.value:
        repo.move(row, E.SYNC_TIMEOUT, "worker", why)
    else:
        repo.event(row, "refused", "worker", why)
    jobs.done(job)


def _await_prune(ctx: AppContext, repo: RequestRepo, jobs: JobRepo, row, job: JobRow, exc: "_Differs") -> None:
    """#751, D5: at the timeout every difference is an object the plan removes, still on the cluster. The deliverer does not
    prune (Argo CD's automated sync does not by default; Flux with prune: false never does), so this is an operator's wait,
    not a failure: awaiting_prune, with a notice that names each object, and the prune job reads until they are gone."""
    names = ", ".join(d.object for d in exc.found.differences)
    note = (f"the deliverer has not removed {len(exc.found.differences)} object(s) this plan removes: {names}. Remove them, "
            f"or prune in the deliverer; a read of their absence ends the request")
    if exc.signal:
        note += f" ({exc.signal})"
    log.warning("prune_waiting", job=job.job_id, request_id=row.request_id, reason=note[:200])
    repo.move(row, E.PRUNE_PENDING, "gitops", note)      # whole: the operator acts on every name (request_events.note is text)
    jobs.done(job)
    jobs.enqueue("prune", request_id=row.request_id, cluster_id=row.cluster_id, delay=ctx.delivery.poll_seconds)


def _prune_change(ctx: AppContext, repo: RequestRepo, jobs: JobRepo, row, job: JobRow) -> None:
    """A gitops change in awaiting_prune (D5): synced once the full-plan read matches, which is when each removed object is
    gone. While only removed objects are left, the operator's wait, unbounded, with the reason on the request once
    (CmapiPruneStuck after a day). Anything else, a cluster or an object that cannot be read or a difference that is no
    removal, is bounded by syncTimeout, as for a delete (_cannot_read): awaiting_prune has no :retry or :revert of its own.
    Git main is read first, as watch_sync does (D3 step 1): the deliverer applies main, not this plan."""
    files = {p: t for p, t in row.plan["files"].items() if t is not None}
    try:
        if not as_plan(lambda: ctx.git.read_folder(folder(row.cluster_id, row.namespace))[0] == files):
            repo.move(row, E.SYNC_TIMEOUT, "worker", "Git main's folder differs from the approved plan")
            jobs.done(job)
            return
        cache = _reader_cache(ctx, row.cluster_id)
        found = read_plan(_live(cache), row.namespace, files, row.plan.get("prev") or {}, **_rules(ctx))
    except (_NotYet, ClusterUnreachable, GitUnavailable) as exc:
        _cannot_read(ctx, repo, jobs, row, job, f"{type(exc).__name__}: {exc}")
        return
    if not found.ok and not found.only_removals:
        _cannot_read(ctx, repo, jobs, row, job, found.summary(), failing="the plan did not match in more than removals")
        return
    if (job.payload or {}).get("unreachable_since"):
        job.payload = {k: v for k, v in job.payload.items() if k != "unreachable_since"}
    if not found.ok:
        _prune_wait(repo, jobs, row, job, ctx.delivery.poll_seconds, found.summary())
        return
    repo.move(row, E.PRUNE_CONFIRMED, "gitops", f"absence confirmed by a successful read: {found.summary()}")
    jobs.done(job)


def _prune_wait(repo: RequestRepo, jobs: JobRepo, row, job: JobRow, poll: int, why: str) -> None:
    """Waiting is not a failure: the attempts reset, so the one job this request has is never exhausted. It is not
    silent either: each new reason lands on the request once, and in the log every time."""
    log.warning("prune_waiting", job=job.job_id, request_id=row.request_id, reason=why[:200])
    if job.last_error != why[:2000]:
        repo.event(row, "prune_waiting", "worker", why[:300])
    jobs.retry(job, why, poll)
    job.attempts = 0


def _cannot_read(ctx: AppContext, repo: RequestRepo, jobs: JobRepo, row, job: JobRow, why: str,
                 failing: str = "the cluster could not be read") -> None:
    """A cluster that cannot be read, unreachable or its reader not connected (never connecting included), is a wait
    bounded by time, not by attempts: one clock from the first failed read, running for the design's syncTimeout, the
    bound watch_sync gives the same failure. The registry's relist, up to five minutes away, never decides the outcome.
    Within the bound the reason lands on the request once; past it the request is sync_failed, a legal state that
    keeps the lock and offers :retry (this job again, a new clock) and :revert."""
    now = datetime.now(timezone.utc)
    since = (job.payload or {}).get("unreachable_since")
    if since is None:
        job.payload = {**(job.payload or {}), "unreachable_since": now.isoformat()}
        since = now.isoformat()
    waited = (now - datetime.fromisoformat(since)).total_seconds()
    if waited < ctx.delivery.sync_timeout_seconds:
        _prune_wait(repo, jobs, row, job, ctx.delivery.poll_seconds, why)
        return
    note = f"{failing} for {int(waited)} s: {why[:160]}"
    if row.status == S.AWAITING_PRUNE.value:
        repo.move(row, E.SYNC_TIMEOUT, "worker", note)
    else:
        repo.event(row, "error", "worker", note)
    jobs.done(job)


def prune(ctx: AppContext, s: Session, job: JobRow) -> None:
    """Ends a delete: only a successful read that finds no namespace confirms it.

    Three outcomes short of that. A cluster that cannot be read (unreachable, or its reader not connected, never
    connecting included) waits for delivery.syncTimeout on one clock from the first failed read, with the reason on
    the request once, then is sync_failed (_cannot_read). A successful read that finds the namespace still there
    (Active, Terminating, whatever) is the operator's wait: unbounded, the reason once, CmapiPruneStuck after a day.
    Everything else, a read refused, a cluster gone from the config, a bug, is a failure: it takes the worker's five
    attempts, and after the last the request is sync_failed, a legal state that keeps the lock and offers :retry (this
    job again) and :revert. A done job on an awaiting_prune request, with nothing left to end it, cannot happen.

    Apply mode deletes only after POST /admin/prune:confirm. A :retry looks again, it confirms nothing."""
    repo, jobs = RequestRepo(s), JobRepo(s)
    row = repo.get(job.request_id)
    retrying = row.status == S.SYNC_FAILED.value and row.action == "delete"
    if row.status != S.AWAITING_PRUNE.value and not retrying:
        jobs.done(job)
        return
    if row.action != "delete":
        return _prune_change(ctx, repo, jobs, row, job)
    mode = _mode(ctx, row.cluster_id)
    if retrying:
        # A delete is done when its folder has left Git and its namespace the cluster. A sync_failed delete may have failed on
        # the first (_merged found a path left at the merge, #616), so the retry reads main before the cluster. A Git error is
        # the worker's retry, never a confirmation.
        left, main = ctx.git.list_folder(folder(row.cluster_id, row.namespace))
        if left:
            _refuse(repo, jobs, row, job, f"the folder on {ctx.git.default_branch} at {main[:8]} still holds {len(left)} "
                                          f"path(s), {sorted(left)[0]!r} first: remove them in Git, then retry")
            return
    try:
        reader = _reader_cache(ctx, row.cluster_id).client
        live = reader.get_object("Namespace", None, row.namespace)
    except (_NotYet, ClusterUnreachable) as exc:
        _cannot_read(ctx, repo, jobs, row, job, f"{type(exc).__name__}: {exc}")
        return
    if (job.payload or {}).get("unreachable_since"):        # a success clears the clock: a later outage starts its own
        job.payload = {k: v for k, v in job.payload.items() if k != "unreachable_since"}
    if live is not None and not _managed(live):
        why = f"{row.namespace} on the cluster is not cmapi-managed; nothing deleted"
        if row.status == S.AWAITING_PRUNE.value:
            repo.move(row, E.SYNC_TIMEOUT, "worker", why)      # :revert restores the folder; waiting cannot fix this
        else:
            repo.event(row, "refused", "worker", why)
        jobs.done(job)
        return
    if mode == "apply" and live is not None and live.get("status", {}).get("phase") != "Terminating":
        if not any(e.event == "prune_confirm" for e in repo.events(row.request_id)):
            _prune_wait(repo, jobs, row, job, ctx.delivery.poll_seconds, "waiting for POST /admin/prune:confirm")
            return
        jobs.fence()
        _deliverer(ctx, row.cluster_id).delete("Namespace", None, row.namespace)
        repo.event(row, "pruned", "cmapi-deliverer", "namespace delete issued")
        try:
            live = reader.get_object("Namespace", None, row.namespace)
        except ClusterUnreachable as exc:
            _cannot_read(ctx, repo, jobs, row, job, f"after the delete, {type(exc).__name__}: {exc}")
            return
    if live is not None:
        # Terminating is not gone: a finalizer can hold it for ever; CmapiPruneStuck says when it has waited too long.
        _prune_wait(repo, jobs, row, job, ctx.delivery.poll_seconds, f"namespace still present ({live.get('status', {}).get('phase', 'Unknown')})")
        return
    event = E.SYNCED if retrying else E.PRUNE_CONFIRMED
    repo.move(row, event, ACTOR[mode], "absence confirmed by a successful read")
    jobs.done(job)


class _NotYet(RuntimeError):
    pass


class _Differs(_NotYet):
    """gitops: the full-plan read is not the plan yet. Carries what was found and the deliverer's signal, for the timeout."""

    def __init__(self, found: PlanRead, signal: str | None):
        super().__init__(found.summary() + (f"; deliverer: {signal}" if signal else ""))
        self.found, self.signal = found, signal
