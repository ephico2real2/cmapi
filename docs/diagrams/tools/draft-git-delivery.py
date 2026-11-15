#!/usr/bin/env python3
"""Draft generator for the Git delivery figures (#286; docs/reviews/2026-11-15-issue-286/). The committed source.html is
the source; this script writes it, then runs diagram-kit's renderer, which writes the PNGs only when its checks pass:

    DIAGRAM_RENDER=<diagram-kit venv>/bin/diagram-render python docs/diagrams/tools/draft-git-delivery.py

Each label is what the code of PR-A does; the file names say where.
"""
import html
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = (ROOT / "docs/diagrams/portal-architecture/source.html").read_text()
STYLE = SRC[SRC.index("<style>"):SRC.index("</style>") + 8]
FONTS = "\n".join(SRC.split("\n")[2:5])
e = html.escape
SANS = 'font-family="IBM Plex Sans, sans-serif" font-size="12.5" fill="currentColor"'
MONO = 'font-family="IBM Plex Mono, monospace"'


def box(x, y, w, h, tone, title, lines=(), dashed=False, tag=None):
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="7" fill="var(--{tone}-wash)" stroke="var(--{tone})" stroke-width="1.2"{dash}/>',
           f'<text x="{x + 12}" y="{y + 20}" font-weight="600" fill="var(--{tone})">{e(title)}</text>']
    if tag:
        out.append(f'<text x="{x + w - 10}" y="{y + 20}" text-anchor="end" font-size="11" {MONO} fill="var(--{tone})">{e(tag)}</text>')
    for i, line in enumerate(lines):
        out.append(f'<text x="{x + 12}" y="{y + 38 + 16 * i}" font-size="11.5" fill="var(--muted)">{e(line)}</text>')
    return out


def frame(x, y, w, h, title):
    return [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="9" fill="none" stroke="var(--rule)" stroke-width="1.2"/>',
            f'<text x="{x + 12}" y="{y + 20}" font-weight="600" font-size="12" {MONO}>{e(title)}</text>']


def line(x1, y1, x2, y2, label=None, lx=None, ly=None, anchor="middle", dashed=False, tone=None, marker="gd"):
    stroke = f"var(--{tone})" if tone else ("var(--muted)" if dashed else "currentColor")
    dash = ' stroke-dasharray="4 4"' if dashed else ""
    out = [f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="1.2"{dash} marker-end="url(#{marker})"/>']
    if label:
        out.append(f'<text x="{lx}" y="{ly}" text-anchor="{anchor}" font-size="11.5">{e(label)}</text>')
    return out


def path(d, label=None, lx=None, ly=None, anchor="middle", dashed=False, tone=None, marker="gd"):
    stroke = f"var(--{tone})" if tone else ("var(--muted)" if dashed else "currentColor")
    dash = ' stroke-dasharray="4 4"' if dashed else ""
    out = [f'<path d="{d}" fill="none" stroke="{stroke}" stroke-width="1.2"{dash} marker-end="url(#{marker})"/>']
    if label:
        out.append(f'<text x="{lx}" y="{ly}" text-anchor="{anchor}" font-size="11.5">{e(label)}</text>')
    return out


def lane_label(x, y, text):
    return [f'<text x="{x}" y="{y}" font-weight="600" font-size="11" fill="var(--muted)" {MONO}>{e(text)}</text>']


# --------------------------------------------------------------------------- figure 1: the architecture

def architecture():
    out = lane_label(20, 22, "THE CMAPI NAMESPACE") + lane_label(800, 22, "OUTSIDE THE NAMESPACE")
    out.append('<line x1="780" y1="8" x2="780" y2="610" stroke="var(--rule)" stroke-width="1.2" stroke-dasharray="6 5"/>')
    out += box(20, 36, 250, 104, "remote", "cmapi-api", (
        "plans read a folder through the host's", "API (contents, branches, commits)", "no Git layer: the SSH key is worker-only",
        "github.py with no workspace"))
    out += box(290, 36, 200, 104, "host", "Secret cmapi-git-bot", (
        "Opaque, key token", "the bot account's API token", "mounted in the api and the worker", "HTTPS Git reads it too (CRC now)"))
    out += box(510, 36, 250, 50, "host", "Secret cmapi-git-bot-ssh", ("ssh-auth: ssh-privatekey; worker only",))
    out += box(510, 92, 250, 48, "host", "ConfigMap cmapi-git-bot-known-hosts", ("known_hosts, pinned; worker only",))

    out += frame(20, 172, 740, 450, "cmapi-worker  (one job at a time: worker.py)")
    out += box(36, 206, 200, 266, "none", "Jobs (jobs/)", (
        "push_branch", "open_pr", "pr_checks", "apply (apply mode)", "merge", "git_cleanup", "git_reconcile, every 15 min",
        "watch_sync, prune", "", "one external effect each"))
    out += box(256, 206, 488, 176, "remote", "Git layer: core/git/workspace.py, transport.py")
    out += box(272, 236, 456, 136, "none", "emptyDir /var/cache/cmapi/git, sizeLimit 1Gi", (
        "repo.git: git init --bare, --filter=blob:none", "fetch refspec: +refs/heads/main:refs/remotes/origin/main only",
        "<workdir>/<cluster>/<requestId>: one worktree per request,", "on branch cmapi/<cluster>/<requestId>, cut from origin/main",
        "one lock per process; .lock: one process per workdir"))
    out += box(256, 394, 488, 78, "remote", "PR adapter (thin): core/git/github.py, gitea.py", (
        "open, state, merge pinned to a sha, comment, close, list", "no Checks API; host CI off by default (hostChecks)"))
    out += box(36, 512, 340, 94, "none", "Sweeper (worker.py, Worker.sweep)", (
        "between jobs, every 300 s; skips when the Git lock is held", "removes worktrees of requests that are not open",
        "worktree prune, gc --auto; above 80 %: fetch again"))
    out += box(396, 512, 348, 94, "none", "git_reconcile (jobs/git_reconcile.py)", (
        "lists cmapi/<cluster>/ PRs and branches on the host", "closes and deletes orphans, with a lease",
        "hands off applied, merge_failed, sync_failed"))
    out += line(236, 290, 252, 290) + line(236, 432, 252, 432)

    out += box(800, 206, 270, 120, "remote", "Any Git host: the Git protocol", (
        "fetch main; push cmapi/<cluster>/<requestId>", "with a lease; delete it with a lease", "SSH: the bot's key, known_hosts pinned",
        "HTTPS: the token through a helper", "never a push to main"))
    out += box(800, 346, 270, 70, "remote", "The host's PR API", ("GitHub REST (github.py)", "Gitea REST (gitea.py): the chart's stand-in"))
    out += box(800, 426, 270, 46, "host", "Proposed: GitLab, Bitbucket", ("adapters of PR-B and PR-C; not built",), dashed=True)
    out += box(800, 512, 125, 94, "none", "The cluster", ("apply mode:", "server-side apply", "by the worker"))
    out += box(945, 512, 125, 94, "none", "Argo CD", ("argocd mode:", "applies main", "after the merge"))
    out += line(744, 300, 796, 300) + line(744, 405, 796, 405)
    out += path("M 150,140 L 150,156 L 776,156 L 776,370 L 796,370", "REST reads by the api, at plan time", 470, 151)
    out += path("M 130,472 L 130,494 L 790,494 L 790,555 L 796,555", "apply job: server-side apply, then read back", 272, 489, anchor="start")
    out += path("M 1070,540 L 1078,540 L 1078,300 L 1072,300", "reads main", 1074, 504, anchor="end", dashed=True)
    return "\n".join(out), 632


# --------------------------------------------------------------------------- figure 2: the request states

def states():
    out = []
    lock = "lock"
    out += box(440, 30, 220, 56, "remote", "approved", ("push_branch, then open_pr",), tag=lock)
    out += box(440, 122, 220, 56, "remote", "pr_open", ("pr_checks; then the merge check",), tag=lock)
    out += line(550, 86, 550, 118, "PR_OPENED", 556, 106, anchor="start")
    out += box(20, 30, 330, 112, "none", "Ends with nothing applied: no lock", (
        "failed: a check failed, the PR was closed, or", "a foreign head on the branch; :retry: approved",
        "superseded: the folder on main moved, or a conflict", "cancelled: :cancel before apply_started",
        "(routers/requests.py takes the row lock first)"))
    out += line(440, 58, 354, 72) + line(440, 150, 354, 120)

    # merge first: argocd, and every delete
    out += lane_label(80, 224, "ARGOCD MODE, AND EVERY DELETE: MERGE FIRST")
    out += box(40, 236, 300, 72, "remote", "merged", ("the merge job, pinned to the checked head;", "then watch_sync; a delete waits for the prune"), tag=lock)
    out += box(40, 338, 300, 56, "remote", "awaiting_prune", ("a delete: until POST /admin/prune:confirm",), tag=lock)
    out += path("M 440,164 L 60,164 L 60,232", "merge", 300, 158)
    out += line(190, 308, 190, 334, "a delete", 198, 326, anchor="start")

    # apply before merge
    out += lane_label(570, 224, "APPLY MODE, A CREATE OR A CHANGE: APPLY BEFORE MERGE")
    out += box(420, 236, 280, 52, "host", "apply_started (an event)", ("own transaction, under the row lock",))
    out += box(420, 318, 280, 56, "remote", "applied", ("applied and confirmed by a read",), tag=lock)
    out += box(420, 404, 280, 56, "none", "merged, then synced: no lock", ("one transaction: the read already confirmed",))
    out += line(550, 178, 550, 232, "apply job", 556, 198, anchor="start")
    out += line(550, 288, 550, 314, "APPLIED", 556, 306, anchor="start")
    out += line(550, 374, 550, 400, "merge, pinned to the applied head", 556, 392, anchor="start")
    out += box(760, 236, 300, 72, "gap", "sync_failed", ("the apply or its read did not finish;", "PR and branch kept; :retry: the apply again"), tag=lock)
    out += box(760, 338, 300, 72, "gap", "merge_failed", ("a check refused, or 5 attempts spent;", "PR and branch kept; CmapiMergeFailed"), tag=lock)
    out += line(700, 262, 756, 262, tone="gap")
    out += line(700, 352, 756, 360, tone="gap")
    out += path("M 820,410 L 820,432 L 704,432", ":retry", 828, 426, anchor="start")
    out += box(420, 490, 640, 70, "none", "No path out of applied or merge_failed but the merge (core/lifecycle.py)", (
        "CANCEL, PR_FAILED and BASE_CHANGED have no row from them; :revert is refused with no merge sha;",
        "never a rollback, never an automatic close of the PR"))
    out += box(40, 424, 300, 136, "none", "synced: no lock", (
        "argocd: watch_sync saw Argo CD sync main", "and a read confirmed the plan", "a delete: prune:confirm, then a read",
        "", "not synced within syncTimeout: sync_failed,", "which holds the lock; :retry or :revert"))
    out += line(190, 394, 190, 420, "confirmed", 198, 412, anchor="start")
    out.append(f'<text x="700" y="590" text-anchor="middle" font-size="11.5" fill="var(--muted)">{e("lock: the state is in OPEN_STATES (core/db/models.py), so a second request for the namespace is 409 change-pending")}</text>')
    return "\n".join(out), 604


# --------------------------------------------------------------------------- figure 3: one request in apply mode

def sequence():
    lanes = [("worker job", 500), ("repo.git, worktree", 630), ("Git host", 760), ("PR API", 890), ("cluster", 1020)]
    out = []
    for name, x in lanes:
        out.append(f'<text x="{x}" y="28" text-anchor="middle" font-weight="600" font-size="11.5">{e(name)}</text>')
        out.append(f'<line x1="{x}" y1="38" x2="{x}" y2="556" stroke="var(--rule)" stroke-width="1.2"/>')
    X = dict((n, x) for n, x in lanes)
    steps = [
        ("push_branch", "1", "fetch origin main into refs/remotes/origin/main", "repo.git, worktree", "Git host"),
        ("", "2", "worktree add -b cmapi/<cluster>/<requestId> at origin/main", "repo.git, worktree", None),
        ("", "3", "commit: trailers, both dates the approval's (reproducible)", "repo.git, worktree", None),
        ("", "4", "push the branch alone; lease: it must not exist yet", "repo.git, worktree", "Git host"),
        ("open_pr", "5", "open the PR, or adopt the open one; its head is step 4's", "worker job", "PR API"),
        ("pr_checks", "6", "kubeconform, Kyverno, the cmapi check on the PR head", "worker job", None),
        ("", "7", "fetch main; merge-tree --write-tree; folder on main = plan's prev", "repo.git, worktree", "Git host"),
        ("apply", "8", "check again (7), then apply_started in its own transaction", "worker job", None),
        ("", "9", "server-side apply of the branch head's folder (deliverer)", "worker job", "cluster"),
        ("", "10", "confirmed_by_read: the namespace and its quota as planned", "cluster", "worker job"),
        ("merge", "11", "check again (7) against a fresh main", "repo.git, worktree", "Git host"),
        ("", "12", "merge pinned to the applied head (PUT .../merge, sha)", "worker job", "PR API"),
        ("git_cleanup", "13", "delete the branch, lease on its head; worktree remove", "repo.git, worktree", "Git host"),
    ]
    y = 64
    for job, n, text, frm, to in steps:
        if job:
            out.append(f'<line x1="20" y1="{y - 18}" x2="440" y2="{y - 18}" stroke="var(--rule)" stroke-width="1"/>')
            out.append(f'<text x="20" y="{y}" font-weight="600" font-size="11.5" {MONO} fill="var(--remote)">{e(job)}</text>')
        out.append(f'<text x="120" y="{y}" font-size="11.5" font-weight="600">{e(n)}</text>')
        out.append(f'<text x="142" y="{y}" font-size="11.5">{e(text)}</text>')
        x1 = X[frm]
        if to:
            x2 = X[to]
            out += line(x1 + (6 if x2 > x1 else -6), y - 4, x2 + (-6 if x2 > x1 else 6), y - 4,
                        n, (x1 + x2) / 2, y - 9)
        else:
            out.append(f'<circle cx="{x1}" cy="{y - 4}" r="9" fill="var(--surface)" stroke="currentColor" stroke-width="1.2"/>')
            out.append(f'<text x="{x1}" y="{y}" text-anchor="middle" font-size="10.5" font-weight="600">{e(n)}</text>')
        y += 40
    # outcome boxes
    out += box(20, 596, 420, 92, "remote", "Merged: merged, then synced in one transaction", (
        "the folder at the merge sha is the plan's (merge_verified)", "then git_cleanup (13); the sweeper on every pod",
        "jobs/merge.py, jobs/git_cleanup.py"))
    out += box(470, 596, 600, 92, "gap", "Not merged after the apply: merge_failed", (
        "11 refused (a conflict, a moved folder), the host refused, or 5 attempts spent",
        "PR and branch kept, the reason on the PR and the timeline; the lock held; CmapiMergeFailed",
        ":retry runs 11 and 12 again, pinned to the same head; never a rollback"))
    out += line(520, 510, 520, 592, "11 or 12 refused", 528, 525, anchor="start", tone="gap")
    out.append(f'<text x="20" y="580" font-size="11.5" fill="var(--muted)">{e("Before 8, a failure closes the PR with nothing applied: failed or superseded.")}</text>')
    return "\n".join(out), 700


BUILT = "Built in PR #288 (#286 PR-A); not merged, not deployed"
RENDERER = os.environ.get("DIAGRAM_RENDER") or shutil.which("diagram-render")

FIGURES = [
    ("The architecture", architecture, 1090,
     "Two layers in the worker: a Git layer with one bare partial mirror and one worktree per request in an emptyDir, and a thin "
     "PR adapter. The API reads through the host's API. The bot's token is in both pods; its SSH key and known hosts only in the "
     "worker. Git goes to any host over SSH or HTTPS; the PR goes to GitHub, and to GitLab and Bitbucket in later pull requests. "
     "The worker applies in apply mode; Argo CD applies main in argocd mode. A sweeper between jobs and git_reconcile clean up.",
     "Solid: a call or traffic. Dashed arrow: a relationship, no traffic. Dashed box: proposed, not built (GitLab and Bitbucket, PR-B and PR-C)."),
    ("The request states, both modes", states, 1080,
     "From approved, a request opens its PR. Before any apply it can end failed, superseded or cancelled with no lock. In argocd "
     "mode and for every delete it merges first, then syncs or waits for the prune. In apply mode it records apply_started, becomes "
     "applied after a confirming read, then merged and synced; a merge that does not happen is merge_failed, which keeps the lock, "
     "the PR and the branch until :retry merges it.",
     "lock: the state holds the namespace's lock. Red: a state that waits for an operator."),
    ("One request in apply mode", sequence, 1080,
     "One request in apply mode: fetch main, a worktree on the request branch, one reproducible commit, a push of the branch with a "
     "lease, the PR, the checks, the merge check, apply_started, the apply and its confirming read, the merge check again, the merge "
     "pinned to the applied head, and the cleanup. A merge refused after the apply is merge_failed.",
     "Each numbered step is one Git or host operation, logged as one git_op event (core/git/oplog.py)."),
]


def main():
    sections = []
    for i, (title, fn, width, aria, caption) in enumerate(FIGURES):
        svg, height = fn()
        # /visual §1.2: true today, or marked. All three show PR #288's behaviour, not main's or CRC's.
        svg += f'\n<text x="20" y="{height + 18}" font-size="11.5" font-weight="600" fill="var(--host)">{e(BUILT)}</text>'
        height += 30
        mid = f"gd{i}"
        svg = svg.replace("url(#gd)", f"url(#{mid})")
        sections += ["  <section>", f"    <h2>{e(title)}</h2>", "    <figure>", '      <div class="fig-scroll">',
                     f'        <svg viewBox="0 0 {width} {height}" role="img" aria-label="{e(aria)}">',
                     f'          <defs><marker id="{mid}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="context-stroke"/></marker></defs>',
                     f"          <g {SANS}>", svg, "          </g>", "        </svg>", "      </div>",
                     f"      <figcaption>{e(BUILT)}. {e(caption)}</figcaption>", "    </figure>", "  </section>"]
    page = "\n".join([
        "<!-- SPDX-License-Identifier: MIT-0. Started from the diagram-kit template, https://github.com/ephico2real2/diagram-kit -->",
        "<title>cmapi: Git delivery</title>", FONTS, STYLE, "", '<div class="page">', "  <header>",
        '    <div class="eyebrow">cmapi · #286 · PR-A</div>', "    <h1>Git delivery: a Git layer and a thin PR adapter</h1>",
        '    <p class="lede">Every change is a request branch and a PR; nothing is pushed to main. In apply mode the worker applies the branch, confirms it, and only then merges.</p>',
        '    <p class="muted">Drawn from the code of PR-A (#288). docs/reviews/2026-11-15-issue-286/ holds each decision.</p>',
        "  </header>", *sections, "</div>"]) + "\n"
    out = ROOT / "docs/diagrams/git-delivery/source.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)
    print(f"wrote {out.relative_to(ROOT)}")
    # The kit's renderer writes the PNGs only when every check passes (diagram-kit STANDARD.md §5).
    if not RENDERER:
        sys.exit("diagram-render not found: set DIAGRAM_RENDER, or install diagram-kit (its README)")
    subprocess.run([RENDERER, str(out), str(out.parent), "architecture,states,apply-sequence"], check=True)


if __name__ == "__main__":
    main()
