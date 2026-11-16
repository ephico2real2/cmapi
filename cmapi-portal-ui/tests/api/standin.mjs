// Stand-ins for the two services that the portal talks to: the OIDC issuer (Keycloak) and the cmapi API.
// Each keeps the rules of the real service that the portal must follow, and records each request it gets.
// The issuer follows deploy/tests/oidc-login-test.py: the verifier must hash to the challenge (RFC 7636, S256), the
// state comes back unchanged, and the token endpoint takes a code once, from a public client, with no secret.
// The API answers from the recorded samples of the service (cmapi/src/cmapi/contract/samples.json).
// Loopback HTTP only, with no container and no Keycloak. A sign-in on a real Keycloak is not proven here.
import { createHash, createSign, generateKeyPairSync, randomBytes } from "node:crypto";
import { readFileSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const repo = fileURLToPath(new URL("../../..", import.meta.url));
export const SAMPLES = JSON.parse(readFileSync(join(repo, "cmapi", "src", "cmapi", "contract", "samples.json"), "utf8"));

const b64url = (data) => Buffer.from(data).toString("base64url");
const token = (kind) => `${kind}-${randomBytes(24).toString("base64url")}`;
const listen = (server) => new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(server.address().port)));
const formOf = (req) => new Promise((resolve) => {
  let body = "";
  req.on("data", (chunk) => { body += chunk; });
  req.on("end", () => resolve(new URLSearchParams(body)));
});

// The permissions of each role, from the table of docs/14-authorization.md ("Roles").
const READ = ["capacity:read", "clusters:read", "objects:read", "requests:read"];
const ROLE_PERMISSIONS = {
  "cmapi-viewer": READ,
  "cmapi-approver": [...READ, "requests:approve", "requests:reject"],
  "cmapi-requester": SAMPLES.operations.core_me.response.body.access.permissions
};
// The groups follow docs/14 ("The groups"): the default path template /cmapi/app-cmapi-rbac-<name>.
export const USERS = {
  viewer: { sub: "sub-viewer", username: "cmapi.viewer", role: "cmapi-viewer", groups: ["/cmapi/app-cmapi-rbac-viewer"] },
  approver: { sub: "sub-approver", username: "cmapi.approver", role: "cmapi-approver", groups: ["/cmapi/app-cmapi-rbac-approver-platform"], email: "cmapi.approver@ephico2real.com" },
  requester: { sub: "sub-ola", username: "ola", role: "cmapi-requester", groups: ["/cmapi/app-cmapi-rbac-requester"], email: "ola@ephico2real.com" }
};

/** One realm, `cmapi`, with one public client that must use PKCE with S256. */
export async function startIssuer({ clientId = "cmapi-portal", redirectUris }) {
  const { publicKey, privateKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
  const jwk = { ...publicKey.export({ format: "jwk" }), kid: "standin", alg: "RS256", use: "sig" };
  const state = {
    /** The person that the next authorization request signs in. With none, the issuer shows its login page. */
    user: null,
    /** Seconds that an access token lives. */
    lifetime: 300,
    /** When false, the token endpoint refuses each refresh token, as after the session ended. */
    sessions: true,
    seen: [],
    codes: new Map(),
    refresh: new Map(),
    access: new Map()
  };
  let base = "";

  const idToken = (user) => {
    const now = Math.floor(Date.now() / 1000);
    const head = b64url(JSON.stringify({ alg: "RS256", typ: "JWT", kid: jwk.kid }));
    const body = b64url(JSON.stringify({ iss: base, aud: clientId, sub: user.sub, iat: now, exp: now + state.lifetime, preferred_username: user.username }));
    return `${head}.${body}.${createSign("RSA-SHA256").update(`${head}.${body}`).sign(privateKey).toString("base64url")}`;
  };
  const issue = (user) => {
    const access = token("at"), refresh = token("rt");
    state.access.set(access, { user, expires: Date.now() + state.lifetime * 1000 });
    state.refresh.set(refresh, user);
    return { access_token: access, refresh_token: refresh, id_token: idToken(user), token_type: "Bearer", expires_in: state.lifetime, scope: "openid" };
  };

  const server = createServer(async (req, res) => {
    const url = new URL(req.url, base);
    const path = url.pathname.replace("/realms/cmapi", "");
    const send = (status, body, headers = {}) => {
      // The discovery document, the keys and the token endpoint answer a browser on another origin, as Keycloak does.
      res.writeHead(status, { "access-control-allow-origin": "*", "cache-control": "no-store", ...headers });
      res.end(typeof body === "string" ? body : JSON.stringify(body));
    };
    const json = { "content-type": "application/json" };

    if (path === "/.well-known/openid-configuration") {
      state.seen.push({ what: "discovery", url: req.url });
      return send(200, {
        issuer: base, authorization_endpoint: `${base}/protocol/openid-connect/auth`, token_endpoint: `${base}/protocol/openid-connect/token`,
        jwks_uri: `${base}/protocol/openid-connect/certs`, end_session_endpoint: `${base}/protocol/openid-connect/logout`,
        response_types_supported: ["code"], grant_types_supported: ["authorization_code", "refresh_token"],
        code_challenge_methods_supported: ["S256"], subject_types_supported: ["public"], id_token_signing_alg_values_supported: ["RS256"]
      }, json);
    }
    if (path === "/protocol/openid-connect/certs") return send(200, { keys: [jwk] }, json);

    if (path === "/protocol/openid-connect/auth") {
      const q = Object.fromEntries(url.searchParams);
      state.seen.push({ what: "auth", url: req.url, query: q });
      // An exact match, and no redirect to an address that is not on the list (RFC 10017, section 6.3.3.2.1).
      if (q.client_id !== clientId || !redirectUris().includes(q.redirect_uri)) return send(400, "invalid client or redirect_uri", { "content-type": "text/plain" });
      const refuse = (why) => send(302, "", { location: `${q.redirect_uri}?${new URLSearchParams({ error: "invalid_request", error_description: why, state: q.state ?? "" })}` });
      if (q.response_type !== "code") return refuse("response_type must be code");
      if (!q.state) return refuse("Missing parameter: state");
      if (!q.code_challenge || q.code_challenge_method !== "S256") return refuse("Missing parameter: code_challenge_method");
      if (!state.user) return send(200, '<!doctype html><title>Sign in to cmapi</title><link rel="icon" href="data:,"><h1>Sign in to cmapi</h1>', { "content-type": "text/html" });
      const code = token("code");
      state.codes.set(code, { challenge: q.code_challenge, redirectUri: q.redirect_uri, user: state.user });
      return send(302, "", { location: `${q.redirect_uri}?${new URLSearchParams({ code, state: q.state, iss: base })}` });
    }

    if (path === "/protocol/openid-connect/token" && req.method === "POST") {
      const form = await formOf(req);
      state.seen.push({ what: "token", grant: form.get("grant_type") });
      const refuse = (error, why) => send(400, { error, error_description: why }, json);
      if (form.get("client_id") !== clientId) return refuse("invalid_client", "unknown client");
      if (form.has("client_secret") || form.has("password")) return refuse("invalid_request", "a public client sends no secret and no password");
      if (form.get("grant_type") === "authorization_code") {
        const grant = state.codes.get(form.get("code"));
        state.codes.delete(form.get("code"));
        if (!grant) return refuse("invalid_grant", "Code not valid");
        if (grant.redirectUri !== form.get("redirect_uri")) return refuse("invalid_grant", "Incorrect redirect_uri");
        const verifier = form.get("code_verifier") ?? "";
        if (createHash("sha256").update(verifier).digest("base64url") !== grant.challenge) return refuse("invalid_grant", "PKCE verification failed");
        return send(200, issue(grant.user), json);
      }
      if (form.get("grant_type") === "refresh_token") {
        const user = state.refresh.get(form.get("refresh_token"));
        // Rotation with no reuse, as the realm sets it: each refresh token works one time.
        state.refresh.delete(form.get("refresh_token"));
        if (!user || !state.sessions) return refuse("invalid_grant", "Session not active");
        return send(200, issue(user), json);
      }
      return refuse("unsupported_grant_type", "only authorization_code and refresh_token");
    }

    if (path === "/protocol/openid-connect/logout") {
      // GET with a query, or POST with a form: OpenID Connect RP-Initiated Logout 1.0 requires both of the issuer.
      const q = req.method === "POST" ? Object.fromEntries(await formOf(req)) : Object.fromEntries(url.searchParams);
      state.seen.push({ what: "logout", method: req.method, url: req.url, query: q });
      state.user = null;
      state.sessions = false;
      return redirectUris().includes(q.post_logout_redirect_uri) ? send(302, "", { location: q.post_logout_redirect_uri }) : send(200, "signed out", { "content-type": "text/plain" });
    }
    return send(404, "");
  });
  const port = await listen(server);
  base = `http://127.0.0.1:${port}/realms/cmapi`;
  return {
    url: base, state, close: () => server.close(),
    /** The person behind an access token that is still valid. */
    whoHas(accessToken) {
      const held = state.access.get(accessToken);
      return held && held.expires > Date.now() ? held.user : null;
    },
    /** Each token that the issuer gave out, to prove that none is in a URL or in storage. */
    tokens: () => [...state.access.keys(), ...state.refresh.keys()]
  };
}

// The list contract's state=open (cmapi/contract/openapi.json, GET /api/v1/requests, `state`).
const OPEN = new Set(["pending_approval", "approved", "pr_open", "applied", "merge_failed", "merged", "awaiting_prune", "sync_failed"]);
const STATUSES = ["pending_approval", "approved", "pr_open", "merged", "awaiting_prune", "synced", "rejected", "failed", "sync_failed", "cancelled"];
const pad = (n) => String(n).padStart(4, "0");

/** `count` requests, each a copy of the recorded request with its own ID, namespace, status and time. Newest first. */
export function requestsFrom(sample, count, now = Date.now()) {
  return Array.from({ length: count }, (_, i) => {
    const n = count - i;
    const at = new Date(now - i * 60_000).toISOString();
    return { ...sample, requestId: `req-20261113-${pad(n)}`, namespace: `${i % 2 ? "ledger" : "payments"}-${pad(n)}-dev`, status: STATUSES[i % STATUSES.length], updatedAt: at, createdAt: at };
  });
}

/** A copy of a recorded request with its own ID, namespace, status and events: what the Workflow tab is shown. */
export function requestWith(sample, { requestId, namespace = sample.namespace, status, events, pr = sample.pr, mergeSha = sample.mergeSha }) {
  const at = events.at(-1)?.at ?? sample.updatedAt;
  return { ...sample, requestId, namespace, status, events, pr, mergeSha, createdAt: events[0]?.at ?? sample.createdAt, updatedAt: at,
    links: { self: `/api/v1/requests/${requestId}`, events: `/api/v1/requests/${requestId}/events` } };
}

const NAME = /^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$/;
const RESERVED = /^(default|openshift(-.*)?|kube-.*|cmapi-system|ocp-.*)$/;
// The body's fingerprint, with the keys of each object in order, as the API compares two bodies of one key.
const sorted = (v) => (Array.isArray(v) ? v.map(sorted) : v && typeof v === "object" ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, sorted(v[k])])) : v);
const fingerprint = (value) => JSON.stringify(sorted(value));
const bodyOf = (req) => new Promise((resolve) => {
  let text = "";
  req.on("data", (chunk) => { text += chunk; });
  req.on("end", () => { try { resolve(text ? JSON.parse(text) : null); } catch { resolve(undefined); } });
});

/**
 * The cmapi API: GET /api/v1/me, the requests (list, one, its events, approve, reject), the tiers, the clusters and the
 * namespace create with its dry run. It keeps the rules that the portal must follow: the list contract (q, state,
 * limit, cursor), the Idempotency-Key of a write (400 without it, the first answer again for the same key and body, 409
 * for the same key and another body), the reason that a rejection needs, and the refusal of a self-approval.
 * `mode` changes one answer, to show what the portal does with it; `answers` overrides the next answers of one route.
 */
export async function startApi({ issuer, portalOrigin }) {
  const recorded = SAMPLES.operations.requests_list_requests.response.body;
  const created = SAMPLES.operations.namespaces_create_namespace.response.body;
  const state = {
    mode: "ok", items: recorded.items, delayMs: 0, seen: [], refuseOnce: new Set(),
    clusters: SAMPLES.operations.core_clusters.response.body.items,
    tiers: SAMPLES.operations.tiers_tiers.response.body,
    plan: SAMPLES.operations["namespaces_create_namespace:dryRun"].response.body,
    /** The next answers of a route, first one first: [{ route: "POST /api/v1/clusters/CRC/namespaces", status, body }]. */
    answers: [],
    /**
     * Routes whose answers are lost on the way after the API did the work, as when the network fails after a write.
     * It holds until the test clears it: a browser may send a POST again by itself when a reused connection closes.
     */
    lose: new Set(),
    /** Idempotency-Key and caller → the body's fingerprint and the request that it made. */
    keys: new Map(),
    created: 0
  };
  const problem = (res, body, cors) => {
    res.writeHead(body.status, { ...cors, "content-type": "application/problem+json" });
    res.end(JSON.stringify(body));
  };
  const refuse = (status, code, detail) => ({ type: `https://cmapi.ephico2real.com/problems/${code}`, title: code, status, code, detail });
  const server = createServer(async (req, res) => {
    const url = new URL(req.url, "http://api");
    // The API allows the portal's origin and no other, and takes no cookie. The headers are cmapi/src/cmapi/core/cors.py's.
    const cors = { "access-control-allow-origin": portalOrigin(), "access-control-allow-headers": "authorization, content-type, idempotency-key", "access-control-allow-methods": "GET, POST", vary: "origin" };
    if (req.method === "OPTIONS") {
      res.writeHead(204, cors);
      return res.end();
    }
    const bearer = /^Bearer (.+)$/.exec(req.headers.authorization ?? "")?.[1];
    const user = bearer ? issuer.whoHas(bearer) : null;
    const body = req.method === "POST" ? await bodyOf(req) : null;
    const call = { method: req.method, path: url.pathname, query: Object.fromEntries(url.searchParams), user: user?.username ?? null, cookie: req.headers.cookie ?? null,
      origin: req.headers.origin ?? null, key: req.headers["idempotency-key"] ?? null, body };
    state.seen.push(call);
    if (state.delayMs) await new Promise((resolve) => setTimeout(resolve, state.delayMs));
    const unauthenticated = SAMPLES.problems.unauthenticated.response.body;
    if (!user || state.mode === "always401") return problem(res, unauthenticated, cors);
    // "expire-once": the API refuses each token one time, as it refuses a token that just ended.
    if (state.mode === "expire-once" && !state.refuseOnce.has(bearer)) {
      state.refuseOnce.add(bearer);
      state.mode = "ok";
      return problem(res, unauthenticated, cors);
    }
    const route = `${req.method} ${url.pathname}`;
    const next = state.answers.findIndex((a) => a.route === route);
    const answer = next >= 0 ? state.answers.splice(next, 1)[0] : null;
    const ok = (value, status = 200) => {
      if (state.lose.has(route)) return req.socket.destroy();
      res.writeHead(status, { ...cors, "content-type": "application/json" });
      res.end(JSON.stringify(value));
    };
    if (answer) return answer.status >= 400 ? problem(res, answer.body, cors) : ok(answer.body, answer.status);
    const permissions = ROLE_PERMISSIONS[user.role];
    const lacks = (permission) => (permissions.includes(permission) ? null
      : refuse(403, "forbidden", `Missing permission ${permission}: no role in your token grants it (roles: ['${user.role}'])`));
    const find = (id) => state.items.find((r) => r.requestId === id);
    // A decision makes a new copy: the recorded samples are shared by every check and stay as they were recorded.
    const replace = (r, fields) => {
      const next = { ...r, ...fields };
      state.items = state.items.map((x) => (x === r ? next : x));
      return next;
    };

    if (url.pathname === "/api/v1/me") {
      const me = SAMPLES.operations.core_me.response.body;
      return ok({ ...me, username: user.username, roles: [user.role], groups: user.groups, identity: { ...me.identity, username: user.username, sub: user.sub, email: user.email ?? null },
        access: { permissions, roles: [{ role: user.role, permissions, environments: "all" }] } });
    }
    if (url.pathname === "/api/v1/requests") {
      if (state.mode === "forbidden") return problem(res, { ...SAMPLES.problems.forbidden.response.body, detail: "Missing permission requests:read: no role in your token grants it (roles: ['cmapi-none'])" }, cors);
      if (state.mode === "error500") return problem(res, { type: "https://cmapi.ephico2real.com/problems/internal-error", title: "internal-error", status: 500, code: "internal-error", detail: "The database did not answer." }, cors);
      const q = (url.searchParams.get("q") ?? "").toLowerCase(), group = url.searchParams.get("state"), limit = Number(url.searchParams.get("limit") ?? 50);
      const status = url.searchParams.get("status"), approver = url.searchParams.get("approver") === "me";
      // approver=me: the pending requests that still need an approval from one of the caller's groups.
      const mine = (r) => r.approval?.remaining.some((slot) => user.groups.some((g) => g.endsWith(`-${slot.group}`)));
      const rows = (state.mode === "empty" ? [] : state.items).filter((r) =>
        (!q || `${r.requestId} ${r.namespace} ${r.clusterId}`.toLowerCase().includes(q)) && (!group || (group === "open") === OPEN.has(r.status))
        && (!status || r.status === status) && (!approver || (r.status === "pending_approval" && mine(r))));
      // The cursor holds the filters that made it. A cursor of other filters is refused, as the list contract says.
      const filters = JSON.stringify([q, group, limit, status, approver]);
      let start = 0;
      const cursor = url.searchParams.get("cursor");
      if (cursor) {
        let parsed = null;
        try { parsed = JSON.parse(Buffer.from(cursor, "base64url").toString()); } catch { /* refused below */ }
        if (!parsed || parsed.f !== filters) return problem(res, { type: "https://cmapi.ephico2real.com/problems/invalid-cursor", title: "The cursor is not valid", status: 400, code: "invalid-cursor", detail: "The cursor does not belong to these filters." }, cors);
        start = parsed.at;
      }
      const items = rows.slice(start, start + limit);
      const cursorAt = (at) => Buffer.from(JSON.stringify({ at, f: filters })).toString("base64url");
      return ok({ items, letters: recorded.letters, page: {
        limit, total: rows.length, from: items.length ? start + 1 : 0, to: start + items.length,
        nextCursor: start + limit < rows.length ? cursorAt(start + limit) : null, prevCursor: start > 0 ? cursorAt(Math.max(0, start - limit)) : null } });
    }
    const one = /^\/api\/v1\/requests\/([^/:]+)(\/events|:approve|:reject)?$/.exec(url.pathname);
    if (one) {
      const [, id, what = ""] = one;
      const r = find(id);
      const denied = lacks(what === ":approve" ? "requests:approve" : what === ":reject" ? "requests:reject" : "requests:read");
      if (denied) return problem(res, denied, cors);
      if (!r) return problem(res, refuse(404, "object-not-found", `No request ${id}`), cors);
      if (req.method === "GET" && what === "") return ok(r);
      if (req.method === "GET" && what === "/events") return ok({ requestId: r.requestId, status: r.status, events: r.events });
      if (req.method === "POST" && r.status !== "pending_approval") return problem(res, refuse(409, "not-pending", `Request ${id} is ${r.status}, not pending_approval`), cors);
      const now = new Date().toISOString();
      if (req.method === "POST" && what === ":approve") {
        // cmapi/src/cmapi/core/approvals.py: a requester approves their own request only where the rule allows it.
        if (r.requester.requester.sub === user.sub && !r.approval.selfApproval) return problem(res, refuse(409, "self-approval", "Requesters cannot approve their own request here"), cors);
        const remaining = r.approval.remaining.map((slot) => (user.groups.some((g) => g.endsWith(`-${slot.group}`)) ? { ...slot, needed: slot.needed - 1 } : slot)).filter((slot) => slot.needed > 0);
        const done = remaining.length === 0;
        return ok(replace(r, { status: done ? "approved" : r.status, updatedAt: now,
          approval: { ...r.approval, remaining, approvals: [...r.approval.approvals, { username: user.username, sub: user.sub, at: now, comment: body?.comment ?? "", relayedBy: null }] },
          events: [...r.events, { at: now, by: user.username, event: "approval", note: body?.comment ?? "", status: "pending_approval" },
            ...(done ? [{ at: now, by: user.username, event: "approved", note: "approval count met", status: "approved" }] : [])] }));
      }
      if (req.method === "POST" && what === ":reject") {
        if (!body?.comment?.trim()) return problem(res, refuse(422, "validation-failed", "A comment is required for a rejection"), cors);
        return ok(replace(r, { status: "rejected", updatedAt: now, events: [...r.events, { at: now, by: user.username, event: "rejected", note: body.comment, status: "rejected" }] }));
      }
    }
    if (url.pathname === "/api/v1/tiers") {
      const denied = lacks("objects:read");
      if (denied) return problem(res, denied, cors);
      const env = url.searchParams.get("environment");
      return ok({ ...state.tiers, environments: env ? Object.fromEntries(Object.entries(state.tiers.environments).filter(([k]) => k === env)) : state.tiers.environments });
    }
    if (url.pathname === "/api/v1/clusters") {
      const denied = lacks("clusters:read");
      if (denied) return problem(res, denied, cors);
      return ok({ items: state.clusters });
    }
    const create = /^\/api\/v1\/clusters\/([^/]+)\/namespaces$/.exec(url.pathname);
    if (create && req.method === "POST") {
      const denied = lacks("namespaces:create");
      if (denied) return problem(res, denied, cors);
      const clusterId = create[1];
      if (!state.clusters.some((c) => c.clusterId === clusterId)) return problem(res, refuse(404, "cluster-not-found", `Unknown cluster ${clusterId}`), cors);
      if (!body || typeof body.namespace !== "string" || !NAME.test(body.namespace)) return problem(res, refuse(422, "invalid-namespace-name", `${JSON.stringify(body?.namespace)} is not a DNS-1123 name`), cors);
      if (RESERVED.test(body.namespace)) return problem(res, refuse(422, "reserved-namespace", `${body.namespace} is reserved`), cors);
      if (url.searchParams.get("dryRun") === "true") {
        const changes = Object.fromEntries(Object.keys(state.plan.changes).map((path) => [path.replace(/namespaces\/[^/]+\//, `namespaces/${body.namespace}/`).replace(/^clusters\/[^/]+\//, `clusters/${clusterId}/`), "added"]));
        return ok({ ...state.plan, changes, capacity: { ...state.plan.capacity, clusterId } });
      }
      const key = call.key;
      if (!key) return problem(res, SAMPLES.problems["idempotency-key-required"].response.body, cors);
      const held = state.keys.get(`${user.sub} ${key}`);
      if (held) return held.fingerprint === fingerprint(body) ? ok(held.request, 202) : problem(res, refuse(409, "idempotency-replay", "Idempotency-Key was used for a different request"), cors);
      const now = new Date().toISOString();
      const requestId = `req-${now.slice(0, 10).replaceAll("-", "")}-9${String(++state.created).padStart(3, "0")}`;
      const request = requestWith(created, { requestId, namespace: body.namespace, status: "approved", pr: null, mergeSha: null,
        events: [{ at: now, by: user.username, event: "plan_auto_approved", note: created.approval.auto, status: "approved" }] });
      request.clusterId = clusterId;
      state.items = [request, ...state.items];
      state.keys.set(`${user.sub} ${key}`, { fingerprint: fingerprint(body), request });
      return ok(request, 202);
    }
    return problem(res, { type: "https://cmapi.ephico2real.com/problems/not-found", title: "not-found", status: 404, code: "not-found", detail: "No such route." }, cors);
  });
  const port = await listen(server);
  return { url: `http://127.0.0.1:${port}`, state, close: () => server.close() };
}

const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".json": "application/json", ".css": "text/css", ".svg": "image/svg+xml", ".woff2": "font/woff2" };

/** A strict static server for a built portal. `config` gives config.json, or null for a deployment that has none. */
export async function servePortal(dir, config) {
  const server = createServer((req, res) => {
    const path = normalize(decodeURIComponent(new URL(req.url, "http://x").pathname)).replace(/^(\.\.[/\\])+/, "");
    if (path === "/config.json") {
      const body = config();
      res.writeHead(body === null ? 404 : 200, { "content-type": "application/json" });
      return res.end(body === null ? "" : typeof body === "string" ? body : JSON.stringify(body));
    }
    try {
      const body = readFileSync(join(dir, path));
      res.writeHead(200, { "content-type": TYPES[extname(path)] || "application/octet-stream" });
      res.end(body);
    } catch {
      res.writeHead(404);
      res.end();
    }
  });
  const port = await listen(server);
  const origin = `http://127.0.0.1:${port}`;
  return { origin, page: `${origin}/index.html`, close: () => server.close() };
}
