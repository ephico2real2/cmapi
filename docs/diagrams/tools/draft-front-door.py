#!/usr/bin/env python3
"""Draft generator for the front door figure (docs/02, "The front door"; #226). The committed source.html is the source.

    python docs/diagrams/tools/draft-front-door.py
    diagram-render docs/diagrams/front-door/source.html docs/diagrams/front-door front-door
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


def box(x, y, w, h, tone, title, lines=(), mono_title=False, dashed=False):
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="7" fill="var(--{tone}-wash)" stroke="var(--{tone})" stroke-width="1.2"{dash}/>']
    font = f' {MONO} font-size="12"' if mono_title else ""
    out.append(f'<text x="{x + 12}" y="{y + 20}" font-weight="600" fill="var(--{tone})"{font}>{e(title)}</text>')
    for i, line in enumerate(lines):
        out.append(f'<text x="{x + 12}" y="{y + 38 + 16 * i}" font-size="11.5" fill="var(--muted)">{e(line)}</text>')
    return out


def arrow(x1, y1, x2, y2, label=None, lx=None, ly=None, dashed=False, anchor="middle"):
    dash = ' stroke-dasharray="4 4" stroke="var(--muted)"' if dashed else ' stroke="currentColor"'
    out = [f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"{dash} stroke-width="1.2" marker-end="url(#fd)"/>']
    if label:
        out.append(f'<text x="{lx}" y="{ly}" text-anchor="{anchor}" font-size="11.5">{e(label)}</text>')
    return out


def curve(x1, y1, x2, y2):
    mx = (x1 + x2) / 2
    return [f'<path d="M {x1},{y1} C {mx},{y1} {mx},{y2} {x2},{y2}" fill="none" stroke="var(--remote)" stroke-width="1.2" marker-end="url(#fd)"/>']


def body():
    out = []
    # Lanes: outside the cluster | the router | namespace cmapi.
    for x, name in ((20, "OUTSIDE THE CLUSTER"), (262, "OPENSHIFT ROUTER"), (478, "NAMESPACE  cmapi")):
        out.append(f'<text x="{x}" y="22" font-weight="600" font-size="11" fill="var(--muted)" {MONO}>{e(name)}</text>')
    for x in (244, 462):
        out.append(f'<line x1="{x}" y1="8" x2="{x}" y2="520" stroke="var(--rule)" stroke-width="1.2" stroke-dasharray="6 5"/>')

    out += box(20, 40, 206, 74, "none", "Browser", ("the portal, Swagger UI, ReDoc,", "the problem pages"))
    out += box(20, 156, 206, 74, "none", "Keycloak, realm cmapi", ("sign-in and tokens, on its own", "host: not through the front door"))
    out += arrow(110, 114, 110, 152, "tokens", 118, 138, anchor="start")
    out += box(20, 400, 206, 58, "none", "CLI, SDK, pipelines", ("the same host, /api/v1",))

    out += box(262, 40, 184, 58, "none", "Route  cmapi-mockup", ("cmapi-mockup.apps-crc.testing",), mono_title=True)
    out += box(262, 130, 184, 92, "none", "Route  cmapi", ("cmapi.apps-crc.testing", "edge TLS; http goes to https", "no Route to the API"), mono_title=True)
    out += arrow(226, 66, 258, 66)
    out += arrow(226, 100, 258, 160)
    out += arrow(226, 420, 258, 200)

    # The front door and its locations.
    out.append('<rect x="478" y="40" width="330" height="420" rx="9" fill="var(--remote-wash)" stroke="var(--remote)" stroke-width="1.4"/>')
    out.append(f'<text x="492" y="62" font-weight="600" fill="var(--remote)" {MONO} font-size="12">cmapi-portal  ·  nginx 1.30.6</text>')
    out.append('<text x="492" y="80" font-size="11.5" fill="var(--muted)">the front door: one origin for the portal and the API</text>')
    rows = [
        ("/  /assets/  /config.json", "the portal's files: assets cached a year"),
        ("/api/  /openapi.json  .yaml", "to the API pods; CSP default-src 'none'"),
        ("/docs  /redoc  /problems", "to the API pods, with their bundles"),
        ("/healthz", "answered by nginx: the probes"),
        ("the mockup's host", "mockups/portal/dist/portal.html"),
    ]
    for i, (path, what) in enumerate(rows):
        y = 98 + 50 * i
        out.append(f'<rect x="492" y="{y}" width="302" height="40" rx="5" fill="var(--surface)" stroke="var(--rule)"/>')
        out.append(f'<text x="502" y="{y + 17}" {MONO} font-size="11.5">{e(path)}</text>')
        out.append(f'<text x="502" y="{y + 32}" font-size="11" fill="var(--muted)">{e(what)}</text>')
    notes = ["Every answer: the OWASP security headers, set once.",
             "One JSON log line per request: request id and",
             "traceparent, no query string. No rate limit here:",
             "the limits per caller stay in the API (#225)."]
    for i, line in enumerate(notes):
        out.append(f'<text x="492" y="{372 + 17 * i}" font-size="11.5">{e(line)}</text>')
    out += arrow(446, 69, 474, 69)
    out += arrow(446, 176, 474, 176)

    # The API pods, found through the headless Service.
    out += box(870, 40, 290, 74, "none", "Service  cmapi-api-pods", ("headless: its DNS answer lists", "the ready API pods only"), mono_title=True)
    out += arrow(808, 128, 866, 92, "resolve", 812, 104, dashed=True, anchor="start")
    for i in range(3):
        y = 176 + 74 * i
        detail = ("uvicorn, the API", "only the front door reaches 8080", "2 or 3 replicas: #225")[i]
        out += box(870, y, 290, 56, "remote", f"cmapi-api  pod {i + 1}", (detail,), mono_title=True)
        out += curve(808, 170 + 8 * i, 866, y + 28)
    out.append('<text x="870" y="420" font-size="11.5">A GET that fails on one pod goes to another.</text>')
    out.append('<text x="870" y="437" font-size="11.5">A POST, PATCH or LOCK is never sent twice.</text>')
    return "\n".join(out), 530


def main():
    svg, height = body()
    aria = ("The browser and the CLI reach one host, the Route cmapi, which goes to the front door, nginx in the cmapi-portal image. "
            "The front door serves the portal's files and sends the API's paths to the API pods, which it finds through the headless "
            "Service cmapi-api-pods. A failed GET goes to another pod; a POST is never sent twice. Keycloak is on its own host.")
    page = "\n".join([
        "<!-- SPDX-License-Identifier: MIT-0. Started from the diagram-kit template, https://github.com/ephico2real2/diagram-kit -->",
        "<title>cmapi: the front door</title>", FONTS, STYLE, "", '<div class="page">', "  <header>",
        '    <div class="eyebrow">cmapi · docs/02 · #226</div>', "    <h1>The front door: one origin for the portal and the API</h1>",
        '    <p class="lede">nginx in the <code>cmapi-portal</code> image serves the portal and sends the API\'s paths to the API pods, so the browser needs no CORS.</p>',
        '    <p class="muted">Built in the chart and tested on this Mac with nginx 1.30.6 and Chromium (<code>deploy/tests/front-door-test.py</code>, <code>cmapi-portal-ui/tests/front-door.test.mjs</code>). Not measured on a cluster (#157). The host names are CRC\'s.</p>',
        "  </header>", "  <section>", "    <h2>The request path</h2>", "    <figure>", '      <div class="fig-scroll">',
        f'        <svg viewBox="0 0 1180 {height}" role="img" aria-label="{e(aria)}">',
        '          <defs><marker id="fd" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="context-stroke"/></marker></defs>',
        f"          <g {SANS}>", svg, "          </g>", "        </svg>", "      </div>",
        "      <figcaption>Solid: built. Dashed arrow: a DNS lookup, no traffic. The NetworkPolicy lets only the router reach the front door, and only the front door reach the API port.</figcaption>",
        "    </figure>", "  </section>", "</div>"]) + "\n"
    out = ROOT / "docs/diagrams/front-door/source.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)
    print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
