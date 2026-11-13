#!/usr/bin/env python3
"""Draft generator for two diagram pages (authorization decision, data model). The committed source.html is the source."""
import html, re, sys
from pathlib import Path
SRC = Path("/Users/olasumbo/gitRepos/workbench/cmapi/wt-diagrams/docs/diagrams/portal-architecture/source.html").read_text()
STYLE = SRC[SRC.index("<style>"):SRC.index("</style>") + 8]
FONTS = "\n".join(l for l in SRC.split("\n")[2:5])
e = html.escape
SANS = 'font-family="IBM Plex Sans, sans-serif" font-size="12.5" fill="currentColor"'

def box(x, y, w, h, title, lines=(), dashed=False, stroke="currentColor", fill="var(--surface)", mono=False):
    d = ' stroke-dasharray="5 4"' if dashed else ""
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="1.2"{d}/>']
    fam = ' font-family="IBM Plex Mono, monospace" font-size="12"' if mono else ""
    out.append(f'<text x="{x+14}" y="{y+21}" font-weight="600"{fam}>{e(title)}</text>')
    for i, l in enumerate(lines):
        col = ' fill="var(--muted)"' if i == len(lines) - 1 and len(lines) > 1 else ""
        out.append(f'<text x="{x+14}" y="{y+39+i*17}"{col}>{e(l)}</text>')
    return "\n".join(out)

def arrow(pts, mid, label=None, lx=None, ly=None, stroke="currentColor", dashed=False, anchor="start"):
    d = ' stroke-dasharray="6 5"' if dashed else ""
    p = " ".join(f"{x},{y}" for x, y in pts)
    out = f'<polyline points="{p}" fill="none" stroke="{stroke}" stroke-width="1.2"{d} marker-end="url(#{mid})"/>'
    if label:
        out += f'\n<text x="{lx}" y="{ly}" font-size="11" fill="var(--muted)" text-anchor="{anchor}">{e(label)}</text>'
    return out

def page(title, eyebrow, h1, lede, note, figs):
    parts = [f"<!-- SPDX-License-Identifier: MIT-0. Started from the diagram-kit template, https://github.com/ephico2real2/diagram-kit -->",
             f"<title>{e(title)}</title>", FONTS, STYLE, '', '<div class="page">', '  <header>',
             f'    <div class="eyebrow">{e(eyebrow)}</div>', f'    <h1>{e(h1)}</h1>', f'    <p class="lede">{lede}</p>',
             f'    <p class="muted">{note}</p>', '  </header>']
    for n, (h2, vb, aria, body, cap, mid) in enumerate(figs, 1):
        parts += ['  <section>', f'    <h2>{e(h2)}</h2>', '    <figure>', '      <div class="fig-scroll">',
                  f'        <svg viewBox="0 0 {vb[0]} {vb[1]}" role="img" aria-label="{e(aria)}">',
                  f'          <defs><marker id="{mid}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="context-stroke"/></marker></defs>',
                  f'          <g {SANS}>', body, '          </g>', '        </svg>', '      </div>',
                  f'      <figcaption>{cap}</figcaption>', '    </figure>', '  </section>']
    parts.append('</div>')
    return "\n".join(parts) + "\n"

# ---------------------------------------------------------------- figure A: the authorization decision
def authz():
    steps = [
        ("1  The token", ["RS256, signature, iss, aud, exp, typ", "core/auth.py · Authenticator.authenticate"],
         "401 unauthenticated", ["no token, or a check failed", "WWW-Authenticate: Bearer"]),
        ("2  The claims", ["roles of this client, groups, sub, employee_id", "core/identity/claims.py · from_claims"], None, None),
        ("3  The permission", ["one role in the token grants x-cmapi-permission", "routers/__init__.py · require"],
         "403 forbidden", ["no role grants the permission", "metric cmapi_authz_denied_total"]),
        ("4  The environment limit", ["the role covers the cluster's or request's env", "core/authz.py · RolePolicy.require"],
         "403 environment-forbidden", ["a role grants it, in another env", "detail names where it applies"]),
        ("5  Approvals only", ["not the requester, not twice, in a needed group", "core/approvals.py · ApprovalLedger.approve"],
         "409 self-approval · 409 already-approved", ["403 not-eligible: in no group", "that the request still needs"]),
    ]
    b, y, mid = [], 74, "ahz"
    b.append(f'<g font-family="IBM Plex Mono, monospace" font-size="13" font-weight="600">'
             f'<rect x="20" y="14" width="250" height="30" rx="6" fill="var(--none-wash)" stroke="var(--none)"/><text x="145" y="34" text-anchor="middle" fill="var(--none)">CALLER</text>'
             f'<rect x="330" y="14" width="400" height="30" rx="6" fill="var(--remote-wash)" stroke="var(--remote)"/><text x="530" y="34" text-anchor="middle" fill="var(--remote)">CMAPI-API  ·  in this order</text>'
             f'<rect x="790" y="14" width="290" height="30" rx="6" fill="var(--gap-wash)" stroke="var(--gap)"/><text x="935" y="34" text-anchor="middle" fill="var(--gap)">REFUSAL  ·  RFC 9457 problem</text></g>')
    b.append(box(20, 74, 250, 76, "A request", ["Authorization: Bearer <access token>", "from Keycloak, realm cmapi"]))
    b.append(arrow([(270, 112), (326, 112)], mid))
    H, GAP = 76, 28
    for i, (t, lines, rt, rlines) in enumerate(steps):
        yy = y + i * (H + GAP)
        b.append(box(330, yy, 400, H, t, lines))
        if rt:
            b.append(box(790, yy, 290, H, rt, rlines, stroke="var(--gap)", fill="var(--gap-wash)"))
            b.append(arrow([(730, yy + 38), (786, yy + 38)], mid, "no", 746, yy + 31, stroke="var(--gap)", anchor="middle"))
        if i < len(steps) - 1:
            b.append(arrow([(530, yy + H), (530, yy + H + GAP - 4)], mid, "yes", 540, yy + H + 17))
    yy = y + len(steps) * (H + GAP)
    b.append(arrow([(530, yy - GAP), (530, yy - 4)], mid, "yes", 540, yy - 11))
    b.append(box(330, yy, 400, 58, "The route runs", ["200, 202 with a ChangeRequest, or the route's own problem"], stroke="var(--remote)", fill="var(--remote-wash)"))
    b.append(box(790, y + 1 * (H + GAP), 290, H, "503 idp-unavailable", ["step 1: signing keys unreachable and", "this key is not cached · never a 401"], stroke="var(--gap)", fill="var(--gap-wash)"))
    b.append(arrow([(730, y + 58), (766, y + 58), (766, y + H + GAP + 38), (786, y + H + GAP + 38)], mid, "keys unreachable", 772, y + H + 17, stroke="var(--gap)"))
    fy = yy + 58 + 34
    b.append(f'<text x="20" y="{fy}">Each box is built code with tests in the service suite. Plain arrow = the check passed. Red arrow = the check refused.</text>')
    b.append(f'<text x="20" y="{fy+19}">Step 5 runs only on POST /requests/{{request_id}}:approve. Keycloak decides who holds a role or a group; cmapi only reads the token.</text>')
    b.append(f'<text x="20" y="{fy+38}" fill="var(--host)" font-weight="600">Measured in the service suite on 2026-11-13. Not yet measured with a token of the realm on CRC.</text>')
    aria = ("cmapi decides a request in five ordered steps: the token (401 unauthenticated, or 503 idp-unavailable when the keys are unreachable), "
            "the claims, the permission (403 forbidden), the environment limit (403 environment-forbidden) and, for an approval only, who can approve "
            "(409 self-approval, 409 already-approved, 403 not-eligible). Only then does the route run.")
    cap = ("The order is the order of the code. A refusal ends the request at that step with an RFC 9457 problem. Steps 1 to 4 run for each route that needs a "
           "permission, and step 5 runs for an approval only. The 503 belongs to step 1: a token whose key cannot be checked is never called invalid.")
    return ("The authorization decision", (1100, fy + 54), aria, "\n".join(b), cap, mid)

# ---------------------------------------------------------------- figure B: the tables
def er():
    mid, b = "ahe", []
    def table(x, y, w, name, cols, note=None, dashed=False):
        h = 30 + 17 * len(cols) + (20 if note else 6)
        d = ' stroke-dasharray="5 4"' if dashed else ""
        o = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="var(--surface)" stroke="currentColor" stroke-width="1.2"{d}/>',
             f'<text x="{x+14}" y="{y+21}" font-weight="600" font-family="IBM Plex Mono, monospace" font-size="12.5">{e(name)}</text>']
        for i, c in enumerate(cols):
            o.append(f'<text x="{x+14}" y="{y+41+i*17}" font-family="IBM Plex Mono, monospace" font-size="11.5">{e(c)}</text>')
        if note:
            o.append(f'<text x="{x+14}" y="{y+h-9}" font-size="11.5" fill="var(--muted)">{e(note)}</text>')
        b.append("\n".join(o)); return h
    cx, cy, cw = 400, 20, 300
    ch = table(cx, cy, cw, "change_requests", ["PK request_id", "cluster_id, namespace, env", "plugin, action, status", "plan (jsonb), plan_hash", "requirement (jsonb)", "requester (jsonb), requester_sub", "idempotency_key, _fingerprint", "pr (jsonb), merge_sha", "created_at … finished_at"], "one row for each write to a namespace")
    left = [("request_events", ["PK id", "FK request_id", "event, status, by, note", "at"], "each state change, in order"),
            ("approvals", ["PK id", "FK request_id", "approver_sub, username, groups", "UQ (request_id, approver_sub)"], "one for each person")]
    right = [("jobs", ["PK job_id", "FK request_id (optional)", "kind, run_after, attempts", "locked_until, lease_generation"], "the worker's queue, claimed by lease"),
             ("approval_notifications", ["PK id", "FK request_id", "channel, kind, recipients", "sent_at, used_at"], "what channel_notify recorded")]
    y = 20
    for name, cols, note in left:
        h = table(20, y, 300, name, cols, note); my = y + h // 2
        b.append(arrow([(320, my), (360, my), (360, cy + 60 + (0 if name == "request_events" else 60)), (396, cy + 60 + (0 if name == "request_events" else 60))], mid, "many to one", 326, my - 7 if name == "request_events" else my + 16))
        y += h + 28
    y = 20
    for name, cols, note in right:
        h = table(780, y, 300, name, cols, note); my = y + h // 2
        yy = cy + 60 + (0 if name == "jobs" else 60)
        b.append(arrow([(780, my), (740, my), (740, yy), (704, yy)], mid, "many to one", 774, my - 7 if name == "jobs" else my + 16, anchor="end"))
        y += h + 28
    by = max(cy + ch, y) + 30
    b.append(f'<text x="20" y="{by}" font-weight="600">No foreign key</text>')
    x = 20
    for name, cols, note, dashed in [("audit_events", ["PK id", "actor_sub, action, target", "at"], "who did what", False),
                                     ("jwks_keys", ["PK issuer", "keys (jsonb)", "fetched_at"], "last good signing keys", False),
                                     ("admin_switches", ["PK name", "value (jsonb)", "set_by, set_at"], "auto-approval pause", False),
                                     ("expiration_notices", ["PK id", "cluster_id, namespace", "expires_at, threshold_days"], "no code writes it yet", True)]:
        hh = table(x, by + 14, 250, name, cols, note, dashed); x += 270
    fy = by + 14 + hh + 34
    b.append(f'<text x="20" y="{fy}">Solid box = a table that built code writes. Dashed box = a table of migration 0001 that no built code writes yet.</text>')
    b.append(f'<text x="20" y="{fy+19}">Arrow = a foreign key on request_id. PK = primary key, FK = foreign key, UQ = unique index.</text>')
    b.append(f'<text x="20" y="{fy+38}" fill="var(--host)" font-weight="600">Read from the migrated test database at migration head 0003, on 2026-11-13.</text>')
    aria = ("The cmapi database has nine tables. change_requests is the centre: request_events, approvals, jobs and approval_notifications each "
            "refer to it by request_id. audit_events, jwks_keys, admin_switches and expiration_notices have no foreign key, and no built code writes expiration_notices yet.")
    cap = ("One request has many events, many approvals (one for each person), many jobs and many notices. A job can exist with no request. "
           "The four tables in the bottom row stand alone. The column lists are short: docs/16 has each column, index and constraint.")
    return ("The tables and their relations", (1100, fy + 54), aria, "\n".join(b), cap, mid)

out = Path(sys.argv[1])
(out / "authorization-decision").mkdir(parents=True, exist_ok=True); (out / "data-model").mkdir(parents=True, exist_ok=True)
(out / "authorization-decision" / "source.html").write_text(page("Authorization Decision", "cmapi · authorization · 2026-11-13", "How cmapi decides a request",
    "A request passes five checks in the order of the code. Each check that refuses ends the request with one problem code. <code>docs/14-authorization.md</code> gives the source of each step as <code>file:line</code>.",
    "Read from <code>cmapi/src/cmapi/core/auth.py</code>, <code>core/authz.py</code>, <code>core/approvals.py</code> and <code>routers/</code>, and measured with the service suite.", [authz()]))
(out / "data-model" / "source.html").write_text(page("Data Model", "cmapi · data model · 2026-11-13", "The nine tables of the cmapi database",
    "The request is the centre of the schema. Four tables refer to it, and four stand alone. <code>docs/16-data-model.md</code> lists each column, index and constraint from a live database.",
    "Read from the migrated test database (PostgreSQL 16) and from <code>cmapi/src/cmapi/core/db/</code>.", [er()]))
