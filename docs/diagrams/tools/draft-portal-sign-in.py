#!/usr/bin/env python3
"""Draft generator for the portal's sign-in sequence (docs/15). The committed source.html is the source.

    python docs/diagrams/tools/draft-portal-sign-in.py
    diagram-render docs/diagrams/portal-sign-in/source.html docs/diagrams/portal-sign-in portal-sign-in
"""
import html
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = (ROOT / "docs/diagrams/portal-architecture/source.html").read_text()
STYLE = SRC[SRC.index("<style>"):SRC.index("</style>") + 8]
FONTS = "\n".join(SRC.split("\n")[2:5])
e = html.escape
SANS = 'font-family="IBM Plex Sans, sans-serif" font-size="12.5" fill="currentColor"'
MONO = 'font-family="IBM Plex Mono, monospace" font-size="11.5"'
P, K, A = 190, 600, 990          # the three lifelines: portal, Keycloak, cmapi-api
STEP, TOP = 50, 96

# (from, to, label, detail). from == to is a step inside one part.
STEPS = [
    (P, P, "1  Read config.json", "apiUrl, issuer, clientId: none is in the build"),
    (P, K, "2  GET /.well-known/openid-configuration", "the endpoints of the realm"),
    (P, P, "3  Make code_verifier, code_challenge = S256(verifier), state", "kept in sessionStorage of this tab until step 7"),
    (P, K, "4  Redirect: GET /auth  response_type=code, client_id=cmapi-portal", "code_challenge, code_challenge_method=S256, state, redirect_uri"),
    (K, K, "5  Sign-in page: Keycloak binds to LDAP", "skipped when the browser has a session"),
    (K, P, "6  Redirect to the page: code, state", "the portal checks that the state is its own"),
    (P, K, "7  POST /token: code, code_verifier", "no client secret, no password"),
    (K, P, "8  Access token (5 min), refresh token, ID token", "kept in the page's memory only"),
    (P, P, "9  Remove code and state from the address", "history.replaceState; the view comes back"),
    (P, A, "10  GET /api/v1/me   Authorization: Bearer", "to the API of config.json and to no other origin"),
    (A, P, "11  200: username, roles, access.permissions", "a tab shows only with its permission"),
    (P, A, "12  GET /api/v1/requests?limit=25", "q, state and cursor are parameters of the API"),
    (A, P, "13  200: one page  ·  403: the detail  ·  401: step 14", "5xx: the detail, and Try again"),
    (P, K, "14  POST /token: refresh_token, one time", "refused: Sign in again, then step 4"),
]


def body():
    h = TOP + STEP * len(STEPS) + 30
    out = []
    for x, name, sub, tone in ((P, "PORTAL  ·  browser", "cmapi-portal-ui", "none"), (K, "KEYCLOAK  ·  realm cmapi", "public client cmapi-portal", "remote"), (A, "CMAPI-API", "verifies the token offline", "remote")):
        out.append(f'<rect x="{x - 150}" y="14" width="300" height="46" rx="8" fill="var(--{tone}-wash)" stroke="var(--{tone})" stroke-width="1.2"/>')
        out.append(f'<text x="{x}" y="34" text-anchor="middle" font-weight="600" {MONO} fill="var(--{tone})">{e(name)}</text>')
        out.append(f'<text x="{x}" y="51" text-anchor="middle" font-size="11" fill="var(--muted)">{e(sub)}</text>')
        out.append(f'<line x1="{x}" y1="60" x2="{x}" y2="{h}" stroke="var(--muted)" stroke-width="1" stroke-dasharray="2 4"/>')
    for i, (a, b, label, detail) in enumerate(STEPS):
        y = TOP + STEP * i
        if a == b:
            x = a - 140 if a != A else a - 160
            out.append(f'<rect x="{x}" y="{y - 16}" width="{300 if a != P else 330}" height="38" rx="6" fill="var(--surface)" stroke="currentColor" stroke-width="1"/>')
            out.append(f'<text x="{x + 10}" y="{y}" font-weight="600" font-size="11.5">{e(label)}</text>')
            out.append(f'<text x="{x + 10}" y="{y + 15}" font-size="11" fill="var(--muted)">{e(detail)}</text>')
            continue
        lo, hi = min(a, b), max(a, b)
        out.append(f'<line x1="{a}" y1="{y + 8}" x2="{b + (6 if b < a else -6)}" y2="{y + 8}" stroke="currentColor" stroke-width="1.2" marker-end="url(#psi)"/>')
        # A label of a call to the API sits between the first two lifelines, so that Keycloak's lifeline does not cross it.
        mid = (P + K) / 2 if hi == A else (lo + hi) / 2
        out.append(f'<text x="{mid}" y="{y}" text-anchor="middle" font-weight="600" font-size="11.5">{e(label)}</text>')
        out.append(f'<text x="{mid}" y="{y + 23}" text-anchor="middle" font-size="11" fill="var(--muted)">{e(detail)}</text>')
    return "\n".join(out), h + 10


def main():
    svg, height = body()
    aria = ("The portal reads config.json, then sends the browser to Keycloak with a PKCE challenge and a state. Keycloak signs the person in "
            "and sends a code back. The portal exchanges the code and its verifier for tokens, keeps them in memory, and calls the API "
            "with the access token. On a 401 it renews one time with the refresh token. If Keycloak refuses, the person clicks Sign in again.")
    page = "\n".join([
        "<!-- SPDX-License-Identifier: MIT-0. Started from the diagram-kit template, https://github.com/ephico2real2/diagram-kit -->",
        "<title>cmapi portal: sign-in to a permitted call</title>", FONTS, STYLE, "", '<div class="page">', "  <header>",
        '    <div class="eyebrow">cmapi · docs/15</div>', "    <h1>The portal: from sign-in to a permitted call</h1>",
        '    <p class="lede">OpenID Connect Authorization Code with PKCE, through the public client <code>cmapi-portal</code>. The portal keeps its tokens in memory and takes each permission from <code>GET /api/v1/me</code>.</p>',
        '    <p class="muted">Each step is built in <code>cmapi-portal-ui</code> and tested against a stand-in issuer and a stand-in API (<code>tests/api</code>). No step was measured on a real Keycloak or on CRC.</p>',
        "  </header>", "  <section>", "    <h2>Sign-in sequence</h2>", "    <figure>", '      <div class="fig-scroll">',
        f'        <svg viewBox="0 0 1180 {height}" role="img" aria-label="{e(aria)}">',
        '          <defs><marker id="psi" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="context-stroke"/></marker></defs>',
        f"          <g {SANS}>", svg, "          </g>", "        </svg>", "      </div>",
        "      <figcaption>Solid: built and tested against stand-ins. The sign-in page of step 5 is Keycloak's own.</figcaption>",
        "    </figure>", "  </section>", "</div>"]) + "\n"
    out = ROOT / "docs/diagrams/portal-sign-in/source.html"
    out.write_text(page)
    print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
