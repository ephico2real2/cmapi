"""Rotate bounded baseline imports from a fresh hub list. A conflicting write discards the grant."""
from __future__ import annotations

from collections import Counter
from contextlib import closing
from datetime import timezone
from time import time

from sqlalchemy.orm import Session

from cmapi.core.clients.kube import KubeError
from cmapi.core.cluster_tokens import ReaderGrant, TokenPolicy
from cmapi.core.context import AppContext
from cmapi.core.db.models import JobRow
from cmapi.core.db.repo import JobRepo
from cmapi.core.observability import CLUSTER_TOKEN_RENEWALS, log
from cmapi.core.registry import ClusterRegistry, HubImportSource, parse_token_expiry, token_expiry

# Scan every minute; failed scans retry using the capped delays below.
TOKEN_RENEW_EVERY = 60
RETRY_DELAYS = (5, 10, 20, 40, 60)


class RenewalError(ValueError):
    """Only fixed diagnostics are safe to report for a response containing a credential."""


def _renew(registry: ClusterRegistry, source: HubImportSource, cid: str, secret: dict, defaults: TokenPolicy) -> None:
    cluster = registry.policies.get(cid)
    policy = cluster.cluster_tokens if cluster else defaults
    expiry = token_expiry(secret)
    if expiry is None:
        raise RenewalError("invalid expiry annotation")
    old = ReaderGrant.parse(secret["data"].get("token"))
    now = time()
    if old.expires != expiry.timestamp() or not old.issued <= now < old.expires:
        raise RenewalError("current token or annotated expiry is invalid")
    if now < old.renewal_time(policy):
        return
    version = secret.get("resourceVersion")
    if not version:
        raise RenewalError("missing Secret resourceVersion")
    trust, _ = registry.import_trust(secret, cluster)
    if trust is None:
        raise RenewalError("invalid cluster connection")
    data = secret["data"]
    # Construct from this exact Secret version. The registry's cached client may belong to an older import.
    with closing(registry.client_factory(cid, data["apiUrl"], data["token"], trust, insecure=trust.source == "insecure")) as client:
        token, reported = client.request_reader_token(policy.duration)
    grant = ReaderGrant.parse(token)
    grant.check_new(policy, time())
    stamp = parse_token_expiry(reported)
    if stamp is None or stamp.timestamp() != grant.expires:
        raise RenewalError("TokenRequest expirationTimestamp disagrees with token")
    expires = stamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    source.patch_token(secret["name"], version, token, expires)
    CLUSTER_TOKEN_RENEWALS.labels(cid, "success").inc()
    log.info("cluster_token_renewed", cluster_id=cid, expires_at=expires)


def renew_imports(registry: ClusterRegistry, defaults: TokenPolicy) -> bool:
    """Return whether another scan should be scheduled with backoff. Directory imports are offline fixtures."""
    source = registry.source
    if not isinstance(source, HubImportSource):
        return False
    try:
        imports = source.list()
    except Exception as exc:
        log.warning("cluster_token_renew_failed", stage="list_imports", reason=type(exc).__name__)
        return True
    counts = Counter(s["labels"].get("cmapi.net/cluster-id") for s in imports)
    failed = False
    for secret in imports:
        cid = secret["labels"].get("cmapi.net/cluster-id")
        if not cid:
            continue
        annotations = secret["annotations"]
        if "cmapi.net/token-expires-at" not in annotations:
            log.info("cluster_token_renew_skipped", cluster_id=cid, reason="missing expiry annotation")
            continue
        if annotations.get("cmapi.net/managed-by") != "cluster-baseline":
            continue
        try:
            if counts[cid] != 1:
                raise RenewalError("duplicate cluster ID")
            _renew(registry, source, cid, secret, defaults)
        except Exception as exc:
            # Neither exception text from transports nor response bodies are safe (the old AND new token may appear).
            reason = str(exc) if isinstance(exc, RenewalError) else type(exc).__name__
            status = exc.status if isinstance(exc, KubeError) else None
            log.warning("cluster_token_renew_failed", cluster_id=cid, reason=reason, http_status=status)
            CLUSTER_TOKEN_RENEWALS.labels(cid, "failure").inc()
            failed = True
    return failed


def token_renew(ctx: AppContext, session: Session, job: JobRow) -> None:
    jobs = JobRepo(session)
    if renew_imports(ctx.registry, ctx.cfg.cluster_tokens):
        delay = RETRY_DELAYS[min(max(0, job.attempts - 1), len(RETRY_DELAYS) - 1)]
        jobs.retry(job, "import token renewal failed; see cluster_token_renew_failed", delay)
    else:
        jobs.done(job)
        jobs.enqueue("token_renew", delay=TOKEN_RENEW_EVERY, payload={"every": TOKEN_RENEW_EVERY})
