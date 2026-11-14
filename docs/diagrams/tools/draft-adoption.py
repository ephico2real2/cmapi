#!/usr/bin/env python3
"""Draft generator for the adoption figure (story #26; docs/reviews/2026-11-14-issue-26-adoption/). The committed
source.html is the source.

    python docs/diagrams/tools/draft-adoption.py
    diagram-render docs/diagrams/adoption/source.html docs/diagrams/adoption adoption
"""
import html
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = (ROOT / "docs/diagrams/portal-architecture/source.html").read_text()
STYLE = SRC[SRC.index("<style>"):SRC.index("</style>") + 8]
FONTS = "\n".join(SRC.split("\n")[2:5])
e = html.escape
SANS = 'font-family="IBM Plex Sans, sans-serif" font-size="12.5" fill="currentColor"'
MONO = 'font-family="IBM Plex Mono, monospace"'


def box(x, y, w, h, tone, title, lines=(), dashed=False, mono=False):
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="7" fill="var(--{tone}-wash)" stroke="var(--{tone})" stroke-width="1.2"{dash}/>']
    font = f' {MONO} font-size="11.5"' if mono else ""
    out.append(f'<text x="{x + 12}" y="{y + 20}" font-weight="600" fill="var(--{tone})"{font}>{e(title)}</text>')
    for i, line in enumerate(lines):
        out.append(f'<text x="{x + 12}" y="{y + 38 + 16 * i}" font-size="11.5" fill="var(--muted)">{e(line)}</text>')
    return out


def arrow(x1, y1, x2, y2, label=None, lx=None, ly=None, anchor="middle", dashed=False, tone=None):
    stroke = f'var(--{tone})' if tone else ("var(--muted)" if dashed else "currentColor")
    dash = ' stroke-dasharray="4 4"' if dashed else ""
    out = [f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="1.2"{dash} marker-end="url(#ad)"/>']
    if label:
        out.append(f'<text x="{lx}" y="{ly}" text-anchor="{anchor}" font-size="11.5">{e(label)}</text>')
    return out


def body():
    out = []
    for x, name in ((20, "THE CLUSTER"), (300, "CMAPI (THE ADOPTION PLUGIN, NOT BUILT)"), (800, "GIT AND ARGO CD")):
        out.append(f'<text x="{x}" y="22" font-weight="600" font-size="11" fill="var(--muted)" {MONO}>{e(name)}</text>')
    for x in (282, 778):
        out.append(f'<line x1="{x}" y1="8" x2="{x}" y2="560" stroke="var(--rule)" stroke-width="1.2" stroke-dasharray="6 5"/>')

    # The live namespace, in the owner's shape.
    out += box(20, 40, 244, 218, "none", "Namespace abc-rnd", (
        "name: aao-rnd", "company.net/app-environment: rnd", "company.net/mnemonic: abc", "company.net/lob: amgsst",
        "company.net/cl: '1'", "company.net/provisioner: cluster-configs", "mnemonic-group-contact: ''",
        "mnemonic-confluence: ''", "cmapi.net/adopt: \"true\"  (opt-in)"), mono=False)
    out += box(20, 274, 244, 58, "none", "ResourceQuota, LimitRange", ("each one, whatever its keys",))
    out += box(20, 360, 244, 74, "none", "Not adopted", ("ServiceAccounts, RoleBindings,", "SCC grants: they stay unmanaged"))
    out += box(20, 470, 244, 74, "none", "The old cluster-configs repository", ("cmapi never reads or writes it",), dashed=True)

    # cmapi's steps.
    steps = [
        ("1  Candidate?", ("opt-in label; not excluded; not managed;", "not tracked by another Argo CD app")),
        ("2  Read the live objects", ("the Namespace, each ResourceQuota", "and LimitRange, from the cluster")),
        ("3  Drop, then add", ("drop server-set fields and skip prefixes;", "add cmapi's system keys, tier custom")),
        ("4  Findings, never changes", ("name: aao-rnd is not the namespace name;", "two empty values; made by another tool")),
    ]
    for i, (title, lines) in enumerate(steps):
        y = 40 + 92 * i
        out += box(300, y, 424, 74, "host", title, lines, dashed=True)
        if i:
            out += arrow(512, y - 18, 512, y - 2)
    out += box(300, 416, 424, 58, "remote", "5  Approval, as for any request (built)", ("approver-platform; one more when there are findings",))
    out += arrow(512, 390, 512, 412)
    out += box(300, 492, 424, 58, "host", "8  Verify after the sync", ("only cmapi's keys, the removed adopt label and", ), dashed=True)
    out.append('<text x="312" y="545" font-size="11.5" fill="var(--muted)">Argo CD\'s tracking annotation may differ</text>')

    out += arrow(264, 140, 296, 140, "read", 280, 132)
    out += arrow(264, 300, 296, 170)

    # Git and Argo CD.
    out += box(800, 40, 260, 92, "remote", "6  The bot's pull request (built)", ("cmapi-cluster-configs:", "clusters/<cluster>/namespaces/", "abc-rnd/: the raw YAML"))
    out += box(800, 160, 260, 108, "remote", "7  Argo CD applies the folder", ("to the cluster: only cmapi's keys", "change. ServerSideApply,", "FailOnSharedResource, Prune=confirm", "(Argo CD on CRC: Wave 5)"), dashed=True)
    out += arrow(724, 440, 796, 90, "approved", 734, 432, anchor="start")
    out += arrow(930, 132, 930, 156, "merged", 936, 149, anchor="start")
    # The worker waits for the state: down the right of the Git lane, then left into step 8, clear of the approval arrow.
    out.append('<path d="M 1040,268 L 1040,521 L 728,521" fill="none" stroke="var(--muted)" stroke-width="1.2" stroke-dasharray="4 4" marker-end="url(#ad)"/>')
    out.append('<text x="1032" y="400" text-anchor="end" font-size="11.5">Synced, Healthy</text>')
    return "\n".join(out), 570


def main():
    svg, height = body()
    aria = ("cmapi adopts a namespace that carries the opt-in label. It reads the live Namespace, ResourceQuota and LimitRange "
            "from the cluster, drops server-set fields and skipped keys, adds its system keys under tier custom, and lists "
            "each difference from the rules as a finding. After approval the bot opens a pull request with the raw YAML; Argo "
            "CD applies it, and cmapi checks that only its own keys changed. The old cluster-configs repository is never read.")
    page = "\n".join([
        "<!-- SPDX-License-Identifier: MIT-0. Started from the diagram-kit template, https://github.com/ephico2real2/diagram-kit -->",
        "<title>cmapi: adoption</title>", FONTS, STYLE, "", '<div class="page">', "  <header>",
        '    <div class="eyebrow">cmapi · story #26 · design</div>', "    <h1>Adoption: raw YAML, as it is, under tier custom</h1>",
        '    <p class="lede">An existing namespace goes under GitOps with no change but cmapi\'s own keys. Each difference from the rules is a finding, never a change.</p>',
        '    <p class="muted">Dashed: designed, not built (Wave 8). Solid: built. The namespace is the owner\'s sample of an existing one.</p>',
        "  </header>", "  <section>", "    <h2>The adoption flow</h2>", "    <figure>", '      <div class="fig-scroll">',
        f'        <svg viewBox="0 0 1080 {height}" role="img" aria-label="{e(aria)}">',
        '          <defs><marker id="ad" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="context-stroke"/></marker></defs>',
        f"          <g {SANS}>", svg, "          </g>", "        </svg>", "      </div>",
        "      <figcaption>Dashed boxes: designed, not built. Dashed arrow: a state that the worker waits for, no traffic. docs/reviews/2026-11-14-issue-26-adoption/ holds each decision.</figcaption>",
        "    </figure>", "  </section>", "</div>"]) + "\n"
    out = ROOT / "docs/diagrams/adoption/source.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)
    print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
