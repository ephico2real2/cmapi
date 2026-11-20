"""The sync state of a managed namespace: Git, the desired state, against the live namespace on the cluster (#481, design
section 4.2). Pure: the routes pass in what they read, so tests/core runs it without a database or a cluster."""
from __future__ import annotations

from typing import Any, Mapping

from cmapi.core.metadata import MetadataKeys

Maps = Mapping[str, Mapping[str, str]]      # {"label": {...}, "annotation": {...}}


def sync_state(open_request: Mapping[str, Any] | None, compared: bool, drifted: list[dict[str, Any]],
               on_cluster: bool = True) -> str:
    """The one place the state is decided, in the design's order, first match wins:

        pending   an open request holds the namespace; merged is one of its states, so this also covers a change that
                  Git has and the cluster does not have yet (the lock holds until synced)
        drift     Git and the cluster were compared, and a key differs or the cluster does not have the namespace
        in-sync   they were compared, and none differs
        unknown   they were not compared: the cluster's watch is not fresh, or the read holds no Git (the list)
    """
    if open_request is not None:
        return "pending"
    if compared and (drifted or not on_cluster):
        return "drift"
    if compared:
        return "in-sync"
    return "unknown"


def sync_view(keys: MetadataKeys, git: Maps | None, live: Maps, open_request: Mapping[str, Any] | None,
              live_fresh: bool, on_cluster: bool = True) -> dict[str, Any]:
    """NamespaceSync. git is None when the read holds no Git (the list); live is the watch cache's namespace, compared only
    when the watch is fresh, so a stale cache never reports drift or in-sync. on_cluster is False when the cluster does
    not have the namespace and live is empty maps: that is never in-sync, also when Git holds no key to compare."""
    compared = git is not None and live_fresh
    drifted = keys.drifted_keys(git, live) if compared else []
    return {"state": sync_state(open_request, compared, drifted, on_cluster), "openRequest": open_request,
            "driftedKeys": drifted}


__all__ = ["sync_state", "sync_view"]
