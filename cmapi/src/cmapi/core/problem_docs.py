"""/problems and /problems/{code}: the documentation of each problem type (#182).

RFC 9457, section 4: a problem type documents its type URI, a title and the HTTP status code, and the URI "SHOULD resolve to
HTML [HTML5] documentation that explains how to resolve the problem". The pages come from the registry PROBLEMS of core/docs.py
and from ACTIONS below. Nothing is computed from a request except the code in the path, and nothing is fetched.
"""
from __future__ import annotations

import html

from cmapi.core.docs import PROBLEMS

# What the caller does about each problem type. tests/service/test_problem_type_docs.py holds one entry for each code of PROBLEMS.
ACTIONS: dict[str, str] = {
    "unauthenticated": "Get a new access token from Keycloak, and send it as `Authorization: Bearer`. The token must be an access token for this instance's audience.",
    "forbidden": "Ask for the role that grants the permission in `detail`. `GET /api/v1/me` lists your permissions.",
    "environment-forbidden": "Use an environment that your roles permit, or ask for a role that permits this one.",
    "cluster-not-found": "Use a cluster ID from `GET /api/v1/clusters`.",
    "object-not-found": "Check the identifier. The object does not exist, or this instance does not serve it.",
    "change-pending": "Wait for the open request in `detail` to finish, or cancel it. One object has one open change.",
    "namespace-exists": "Use another name, or change the namespace that exists.",
    "namespace-exists-unmanaged": "Use another name. cmapi does not manage the namespace that exists on the cluster.",
    "not-pending": "Read the request. Only a request in the state `pending_approval` takes an approval or a rejection.",
    "invalid-transition": "Read the request. Its state does not permit this action.",
    "already-approved": "Do nothing. Your approval is recorded, and another person must give the next one.",
    "self-approval": "Ask another person of the approving group. A requester cannot approve their own request in this environment.",
    "nothing-to-prune": "Do nothing. No delete of this namespace waits for a prune.",
    "idempotency-replay": "Send a new `Idempotency-Key` for a new request. A key belongs to one request body.",
    "precondition-failed": "Read the object again, and send the change with the new `ETag` in `If-Match`.",
    "validation-failed": "Correct the fields that `errors` names, and send the request again.",
    "policy-violation": "Correct the items that `errors` names. Each item has a code and the key or the field that the policy refused.",
    "capacity-exceeded": "Ask for less, or choose another cluster. `detail` names the resource that does not fit.",
    "environment-not-served": "Send the request to the instance that serves the environment. `detail` names it.",
    "cluster-not-writable": "Choose a cluster that takes writes, or ask the platform team to add this cluster to `clusters.yaml`.",
    "plugin-disabled": "Ask the platform team. `plugins.yaml` turns this kind of write off for the environment.",
    "reserved-namespace": "Use a name that matches no reserved pattern.",
    "invalid-namespace-name": "Use a DNS-1123 label: lower-case letters, digits and `-`, at most 63 characters.",
    "no-change": "Do nothing. The object already has the values of the request.",
    "identity-incomplete": "Ask the identity team. The token does not have a claim that cmapi requires, for example `employee_id`.",
    "unknown-user": "Use the employee ID of an enabled user.",
    "invalid-team-dl": "Use an address in one of the mail domains that `detail` lists.",
    "expiration-not-allowed": "Do not set an expiration here. The environment does not permit one.",
    "expiration-limit": "Use a date in the limits of the environment, or ask the platform approvers for a longer one.",
    "expiration-in-past": "Use a date that is later than the current one.",
    "expiration-not-set": "Use `:set` to give the namespace its first expiration.",
    "expiration-already-set": "Use `:extend` to move the date that exists.",
    "namespace-protected": "Ask the platform team. A protected namespace is not deleted through the API.",
    "unknown-serviceaccount": "Use the name of a ServiceAccount of this namespace.",
    "on-behalf-of-not-allowed": "Remove `onBehalfOf`. A person calls as themselves.",
    "on-behalf-of-required": "Name the person in `onBehalfOf`. A service client must say for whom it calls.",
    "not-eligible": "Ask a person of an approving group that the request still needs.",
    "precondition-required": "Read the object, and send its `ETag` in `If-Match`.",
    "idempotency-key-required": "Send an `Idempotency-Key` header with each write.",
    "invalid-cursor": "Start the list again without `cursor`. A cursor is valid only for the list that gave it.",
    "invalid-sort": "Use a sort field that the operation lists in the API reference.",
    "invalid-limit": "Use a limit that the operation lists in the API reference.",
    "rate-limited": "Wait for the number of seconds in `Retry-After`, then send the request again.",
    "idp-unavailable": "Try again after the seconds in `retryAfter`. cmapi cannot read Keycloak's signing keys.",
    "cluster-unreachable": "Try again later. The cluster did not answer.",
    "capacity-service-unavailable": "Try again later. The capacity service did not answer.",
    "git-unavailable": "Try again later. The Git host did not answer.",
    "validator-unavailable": "Try again later. The manifest validator did not start.",
    "docs-assets-missing": "Use the image of cmapi, which holds the bundles, or run `cmapi-tools docs-assets` once in a source checkout.",
}

_HEAD = ('<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8"/>\n'
         '<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>{title}</title>\n'
         "<style>body{{font:16px/1.5 system-ui,sans-serif;margin:2rem auto;max-width:60rem;padding:0 1rem}}"
         "code{{background:#f2f2f2;padding:0 .25rem}}table{{border-collapse:collapse}}"
         "th,td{{border-bottom:1px solid #ddd;padding:.3rem .6rem;text-align:left;vertical-align:top}}</style></head><body>\n")


def _code_spans(text: str) -> str:
    """Escaped text, with each `name` as a code element."""
    parts = html.escape(text).split("`")
    return "".join(f"<code>{p}</code>" if i % 2 else p for i, p in enumerate(parts))


def problem_title(code: str) -> str:
    return code.replace("-", " ")


def problem_html(code: str, base: str, instance: str) -> str:
    """The page of one problem type. `code` is a key of PROBLEMS: the caller checks."""
    status, example = PROBLEMS[code]
    e = html.escape
    return (_HEAD.format(title=e(f"{code} - cmapi problem type"))
            + f'<h1 id="code">{e(code)}</h1>\n'
            + "<table>\n"
            + f'<tr><th>Type URI</th><td><code id="type">{e(base + code)}</code></td></tr>\n'
            + f'<tr><th>Title</th><td id="title">{e(problem_title(code))}</td></tr>\n'
            + f'<tr><th>HTTP status</th><td id="status">{status}</td></tr>\n'
            + f'<tr><th>Example of <code>detail</code></th><td id="example">{e(example)}</td></tr>\n'
            + f'<tr><th>What to do</th><td id="action">{_code_spans(ACTIONS[code])}</td></tr>\n'
            + "</table>\n"
            + f"<p>A client compares <code>type</code> or <code>code</code>, never <code>detail</code>. "
              f"This page is served by cmapi ({e(instance)}). "
              f'<a href="/problems">All problem types</a>.</p>\n</body></html>\n')


def problems_index_html(base: str, instance: str) -> str:
    e = html.escape
    rows = "".join(f'<tr><td><a href="/problems/{e(code)}"><code>{e(code)}</code></a></td><td>{status}</td>'
                   f"<td>{_code_spans(ACTIONS[code])}</td></tr>\n"
                   for code, (status, _) in sorted(PROBLEMS.items(), key=lambda kv: (kv[1][0], kv[0])))
    return (_HEAD.format(title=e("cmapi problem types"))
            + f"<h1>cmapi ({e(instance)}): problem types</h1>\n"
            + "<p>Each refusal of the API is an RFC 9457 problem with the media type <code>application/problem+json</code>. "
              f"Its <code>type</code> is <code>{e(base)}</code> and the code.</p>\n"
            + "<table>\n<tr><th>Code</th><th>HTTP status</th><th>What to do</th></tr>\n" + rows + "</table>\n</body></html>\n")
