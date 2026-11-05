"""The request state machine (docs/01, Request lifecycle, state table).

One table of (state, event) -> state. The pipeline, the worker and the request endpoints all move a
request through transition(), so no code path can invent a state change. Lock and reservation
ownership follow from the state, never from separate flags.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from cmapi.core.errors import Problem


class State(str, Enum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    PR_OPEN = "pr_open"
    MERGED = "merged"
    AWAITING_PRUNE = "awaiting_prune"
    SYNCED = "synced"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    FAILED = "failed"
    SYNC_FAILED = "sync_failed"
    SUPERSEDED = "superseded"
    REVERTED = "reverted"                         # sync_failed, handed over to a :revert request


class Event(str, Enum):
    PLAN_NEEDS_APPROVAL = "plan_needs_approval"   # plan passed, approvals required
    PLAN_AUTO_APPROVED = "plan_auto_approved"     # auto:<policy> or none-required
    PLAN_FAILED = "plan_failed"                   # policy, capacity or validation refusal
    APPROVED = "approved"                         # the count is met and capacity still fits
    REJECTED = "rejected"                         # an approver rejected, with a comment
    CANCEL = "cancel"                             # the requester, before pr_open
    APPROVAL_TIMEOUT = "approval_timeout"
    PR_OPENED = "pr_opened"
    PR_FAILED = "pr_failed"                       # 5 attempts with backoff, CI failed, PR closed
    BASE_CHANGED = "base_changed"                 # the namespace's files changed in Git after the plan
    MERGED = "merged"
    SYNCED = "synced"                             # Argo CD Synced at or after the merge, confirmed by a read
    PRUNE_PENDING = "prune_pending"               # a delete merged; Argo CD waits for confirmation
    PRUNE_CONFIRMED = "prune_confirmed"
    SYNC_TIMEOUT = "sync_timeout"                 # not synced within 30 minutes, or a failed sync
    RETRY = "retry"                               # :retry (requests:retry)
    REVERT = "revert"                             # :revert opens a revert request; this one releases its lock


S, E = State, Event
_T: dict[tuple[State | None, Event], State] = {
    (None, E.PLAN_NEEDS_APPROVAL): S.PENDING_APPROVAL,
    (None, E.PLAN_AUTO_APPROVED): S.APPROVED,
    (None, E.PLAN_FAILED): S.REJECTED,
    (S.PENDING_APPROVAL, E.APPROVED): S.APPROVED,
    (S.PENDING_APPROVAL, E.REJECTED): S.REJECTED,
    (S.PENDING_APPROVAL, E.CANCEL): S.CANCELLED,
    (S.PENDING_APPROVAL, E.APPROVAL_TIMEOUT): S.TIMEOUT,
    (S.APPROVED, E.PR_OPENED): S.PR_OPEN,
    (S.APPROVED, E.CANCEL): S.CANCELLED,
    (S.APPROVED, E.PR_FAILED): S.FAILED,
    (S.APPROVED, E.BASE_CHANGED): S.SUPERSEDED,
    (S.PR_OPEN, E.MERGED): S.MERGED,
    (S.PR_OPEN, E.PR_FAILED): S.FAILED,
    (S.PR_OPEN, E.BASE_CHANGED): S.SUPERSEDED,
    (S.MERGED, E.SYNCED): S.SYNCED,
    (S.MERGED, E.PRUNE_PENDING): S.AWAITING_PRUNE,
    (S.MERGED, E.SYNC_TIMEOUT): S.SYNC_FAILED,
    (S.AWAITING_PRUNE, E.PRUNE_CONFIRMED): S.SYNCED,
    (S.AWAITING_PRUNE, E.SYNC_TIMEOUT): S.SYNC_FAILED,   # the namespace on the cluster is not ours: :revert is the way out
    (S.FAILED, E.RETRY): S.APPROVED,              # re-acquires lock and reservation; 409 if another request holds the lock
    (S.SYNC_FAILED, E.RETRY): S.SYNC_FAILED,      # restarts the sync watch; the worker moves it on with SYNCED
    (S.SYNC_FAILED, E.SYNCED): S.SYNCED,
    (S.SYNC_FAILED, E.REVERT): S.REVERTED,
}

TERMINAL = frozenset({S.SYNCED, S.REJECTED, S.CANCELLED, S.TIMEOUT, S.SUPERSEDED, S.REVERTED})
_LOCK = frozenset({S.PENDING_APPROVAL, S.APPROVED, S.PR_OPEN, S.MERGED, S.AWAITING_PRUNE, S.SYNC_FAILED})
_RESERVATION = frozenset({S.PENDING_APPROVAL, S.APPROVED, S.PR_OPEN, S.MERGED})

# Who may cause each externally triggered event (everything else is the worker or the pipeline).
PERMISSION = {E.APPROVED: "requests:approve", E.REJECTED: "requests:reject",
              E.CANCEL: "requests:cancel", E.RETRY: "requests:retry", E.REVERT: "requests:retry"}


def holds_lock(state: State) -> bool:
    return state in _LOCK


def holds_reservation(state: State) -> bool:
    return state in _RESERVATION


@dataclass(frozen=True)
class Transition:
    before: State | None
    event: Event
    after: State
    releases_lock: bool
    releases_reservation: bool
    acquires_lock: bool                           # the caller must take the namespace lock (409 if held)
    acquires_reservation: bool                    # the caller must reserve capacity again


def transition(state: State | None, event: Event, *, actor_is_requester: bool = True,
               actor_is_operator: bool = False) -> Transition:
    if event is E.CANCEL and not (actor_is_requester or actor_is_operator):
        raise Problem.forbidden("Only the requester or an operator can cancel")
    after = _T.get((state, event))
    if after is None:
        code = "not-pending" if event in (E.APPROVED, E.REJECTED) else "invalid-transition"
        raise Problem.conflict(code, f"{event.value} is not allowed in state {state.value if state else 'new'}",
                               state=state.value if state else None)
    held_lock = state is not None and holds_lock(state)
    held_res = state is not None and holds_reservation(state)
    return Transition(state, event, after,
                      releases_lock=held_lock and not holds_lock(after),
                      releases_reservation=held_res and not holds_reservation(after),
                      acquires_lock=not held_lock and holds_lock(after),
                      acquires_reservation=not held_res and holds_reservation(after))


def allowed_events(state: State | None) -> list[Event]:
    return [e for (s, e) in _T if s == state]
