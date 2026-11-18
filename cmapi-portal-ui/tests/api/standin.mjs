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
// GET /api/v1/metadata-keys (#336): the recorded answer of the reference file, and the company file's answer, which
// cmapi/tests/core/test_metadata_form_336.py holds equal to what the service serves for that file.
export const REFERENCE_KEYS = SAMPLES.operations.core_metadata_keys.response.body;
export const COMPANY_KEYS = JSON.parse(readFileSync(new URL("metadata-keys.company.json", import.meta.url), "utf8"));

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
  "cmapi-requester": SAMPLES.operations.core_me.response.body.access.permissions,
  "cmapi-operator": [...READ, "namespaces:create", "requests:cancel", "namespaces:write", "quotas:write", "serviceaccounts:write", "grants:write", "requests:retry",
    "adoption:write", "reports:read", "operations:run", "namespaces:protect"],
  // A requester limited to rnd (docs/14, "environments"): the API answers 403 environment-forbidden for its writes elsewhere.
  "cmapi-requester-rnd": SAMPLES.operations.core_me.response.body.access.permissions
};
// An operator limited to rnd (#366): /me says operator, with operatorEnvironments ["rnd"].
ROLE_PERMISSIONS["cmapi-operator-rnd"] = ROLE_PERMISSIONS["cmapi-operator"];
// The approval relay (docs/14): requests:read and approvals:relay, and no capacity:read, so no Capacity tab (#302).
ROLE_PERMISSIONS["cmapi-approval-relay"] = ["requests:read", "approvals:relay"];
// #366: the operator's permission, and the labels of approval-rules.yaml protected.labels (operator-only on every instance).
const PROTECT_PERMISSION = "namespaces:protect";
const PROTECT_KEY = "cmapi.net/protected";
const PROTECTION_LABELS = [PROTECT_KEY, "do-not-delete"];
/** The approval of a removal of the protection label, as the service plans it (cmapi.net/protected is a sensitiveKeys entry). */
const UNPROTECT_APPROVAL = { ...SAMPLES.operations["namespaces_update_namespace:dryRun"].response.body.approval, auto: null,
  reasons: ["dev change: 0 from approver-platform", "threshold sensitiveKeyChanged: +1 approver-platform"],
  slots: [{ count: 1, group: "approver-platform", reason: "Sensitive key changed" }], remaining: [{ group: "approver-platform", needed: 1 }] };
/** The environments of a role that is limited to some; every other role covers all. */
const ROLE_ENVIRONMENTS = { "cmapi-requester-rnd": ["rnd"], "cmapi-operator-rnd": ["rnd"] };
// The groups follow docs/14 ("The groups"): the default path template /cmapi/app-cmapi-rbac-<name>.
export const USERS = {
  viewer: { sub: "sub-viewer", username: "cmapi.viewer", role: "cmapi-viewer", groups: ["/cmapi/app-cmapi-rbac-viewer"] },
  approver: { sub: "sub-approver", username: "cmapi.approver", role: "cmapi-approver", groups: ["/cmapi/app-cmapi-rbac-approver-platform"], email: "cmapi.approver@ephico2real.com" },
  requester: { sub: "sub-ola", username: "ola", role: "cmapi-requester", groups: ["/cmapi/app-cmapi-rbac-requester"], email: "ola@ephico2real.com" },
  operator: { sub: "sub-operator", username: "cmapi.operator", role: "cmapi-operator", groups: ["/cmapi/app-cmapi-rbac-operator"], email: "cmapi.operator@ephico2real.com" },
  rndRequester: { sub: "sub-rnd", username: "rnd.requester", role: "cmapi-requester-rnd", groups: ["/cmapi/app-cmapi-rbac-requester-rnd"], email: "rnd.requester@ephico2real.com" },
  rndOperator: { sub: "sub-rnd-operator", username: "rnd.operator", role: "cmapi-operator-rnd", groups: ["/cmapi/app-cmapi-rbac-operator-rnd"], email: "rnd.operator@ephico2real.com" },
  relay: { sub: "sub-relay", username: "cmapi.relay", role: "cmapi-approval-relay", groups: [] }
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

// The quota list of the API (cmapi/src/cmapi/plugins/quotas and cmapi/src/cmapi/core/listquery.py): the same filters, sorts,
// keyset cursor bound to the filters, startsWith, letters and attention counts, so that the portal is held to its rules.
const QUOTA_SAMPLE = SAMPLES.operations.quotas_quotas.response.body.items[0];
const TEAMS = ["accounts", "billing", "catalog", "checkout", "data", "fraud", "gateway", "identity", "ledger", "orders", "payments", "search", "shipping", "tax", "vendor"];
const APPS = ["api", "worker", "batch", "web", "events"];
const SHARES = [0.1, 0.45, 0.82, 0.97, 0.3, 0.6, 0.05, 0.88];
const HARD = { small: [8, 16, 50], medium: [16, 32, 100], large: [32, 64, 200] };

/** `count` quota rows, each a copy of the recorded row with its own name, cluster, environment, tier and use. In name order of creation, not sorted. */
export function quotasFrom(count, { clusters = ["CRC"], envs = ["dev", "rnd"] } = {}) {
  return Array.from({ length: count }, (_, i) => {
    const team = TEAMS[i % TEAMS.length], app = APPS[Math.floor(i / TEAMS.length) % APPS.length], env = envs[i % envs.length];
    const tier = ["small", "medium", "large"][i % 3], [cpu, mem, pods] = HARD[tier], share = SHARES[i % SHARES.length];
    const memShare = SHARES[(i + 3) % SHARES.length] * 0.9;
    const used = { cpu: cpu * share, mem: mem * memShare, pods: Math.round(pods * 0.3) };
    return { ...QUOTA_SAMPLE, name: `${team}-${app}-${env}`, team, app, env, tier, clusterId: clusters[i % clusters.length],
      cpu: [`${Math.round(used.cpu * 1000)}m`, String(cpu)], memory: [`${Math.round(used.mem * 1024)}Mi`, `${mem}Gi`], pods: [String(used.pods), String(pods)],
      used: Math.max(Math.round(used.cpu * 1000) / 1000 / cpu, Math.round(used.mem * 1024) / 1024 / mem, used.pods / pods),
      tierOutdated: i % 7 === 3, openRequest: i % 11 === 5 ? `req-20261115-${String(5000 + i)}` : null, expiresAt: null };
  });
}

const QUOTA_FACETS = { "near-limit": (r) => r.used >= 0.8, "tier-outdated": (r) => r.tierOutdated, "open-request": (r) => Boolean(r.openRequest) };
const severityOf = (used) => (used >= 0.95 ? 3 : used >= 0.8 ? 2 : 0);
const QUOTA_SORTS = { name: (r) => ["", r.name, r.clusterId], used: (r) => [-r.used, r.name, r.clusterId], severity: (r) => [-severityOf(r.used), r.name, r.clusterId] };
const compareKeys = (a, b) => { for (let i = 0; i < a.length; i++) { if (a[i] < b[i]) return -1; if (a[i] > b[i]) return 1; } return 0; };
function matchRank(r, text) {
  const t = text.toLowerCase(), name = r.name.toLowerCase();
  if (name.startsWith(t)) return [0, "name starts with"];
  if (name.includes(t)) return [1, "name contains"];
  for (const label of ["team", "app"]) {
    const v = String(r[label] ?? "").toLowerCase();
    if (v && v.includes(t)) return [2, `${label} ${r[label]}`];
  }
  return null;
}
/** The rows of the filters and the search, in the order of the sort; `null` when the sort is not one of the API's. */
function quotaOrder(rows, q) {
  const key = QUOTA_SORTS[q.sort];
  if (!key) return null;
  const filters = [["env", q.env], ["clusterId", q.clusterId], ["team", q.team], ["tier", q.tier]].filter(([, v]) => v);
  return rows.filter((r) => filters.every(([k, v]) => String(r[k]) === v) && (!q.q || matchRank(r, q.q))).sort((a, b) => compareKeys(key(a), key(b)));
}
export function quotaQueryOf(params) {
  const get = (k) => params.get(k) || "";
  return { q: get("q"), env: get("env"), clusterId: get("clusterId"), team: get("team"), tier: get("tier"), state: get("state"), sort: get("sort") || "name",
    limit: Number(params.get("limit") ?? 50), cursor: params.get("cursor"), startsWith: params.get("startsWith") };
}
const quotaHash = (q) => JSON.stringify([q.q.toLowerCase(), q.env, q.clusterId, q.team, q.tier, q.state, q.sort]);
/** GET /api/v1/quotas: a page, or a problem as [status, code, detail]. */
export function quotaPage(rows, q) {
  if (q.state && !QUOTA_FACETS[q.state]) return [422, "validation-failed", `state is one of ${Object.keys(QUOTA_FACETS).sort()}, not ${q.state}`];
  if (![25, 50, 100].includes(q.limit) && !(q.limit > 0 && q.limit <= 200)) return [400, "invalid-limit", "limit is one of (25, 50, 100), at most 200"];
  const others = quotaOrder(rows, q);
  if (!others) return [400, "invalid-sort", `Unknown sort ${q.sort}`];
  const ordered = q.state ? others.filter(QUOTA_FACETS[q.state]) : others;
  const keys = ordered.map(QUOTA_SORTS[q.sort]), total = ordered.length;
  let start = 0, end = Math.min(total, q.limit);
  if (q.cursor) {
    let c = null;
    try { c = JSON.parse(Buffer.from(q.cursor, "base64url").toString()); } catch { /* refused below */ }
    if (!c || c.h !== quotaHash(q)) return [400, "invalid-cursor", "Filters or sort changed since this cursor was issued"];
    if (c.d === "next") { start = keys.findIndex((k) => compareKeys(k, c.k) > 0); if (start < 0) start = total; end = Math.min(total, start + q.limit); }
    else { end = keys.findIndex((k) => compareKeys(k, c.k) >= 0); if (end < 0) end = total; start = Math.max(0, end - q.limit); }
  } else if (q.startsWith && q.sort === "name") {
    start = ordered.findIndex((r) => r.name.toLowerCase() >= q.startsWith.toLowerCase());
    if (start < 0) start = total;
    end = Math.min(total, start + q.limit);
  }
  const items = ordered.slice(start, end);
  const sign = (k, d) => Buffer.from(JSON.stringify({ k, d, h: quotaHash(q) })).toString("base64url");
  const letters = {};
  for (const r of ordered) letters[r.name[0].toUpperCase()] = (letters[r.name[0].toUpperCase()] ?? 0) + 1;
  // The attention counts are over the other filters, not over the chosen state: each chip keeps its number.
  const facets = Object.fromEntries(Object.entries(QUOTA_FACETS).map(([name, test]) => [name, others.filter(test).length]));
  return { items, letters, facets, page: { limit: q.limit, total, from: items.length ? start + 1 : 0, to: end,
    nextCursor: items.length && end < total ? sign(keys[end - 1], "next") : null, prevCursor: items.length && start > 0 ? sign(keys[start], "prev") : null } };
}
export function quotaSuggest(rows, text) {
  if (text.trim().length < 2) return [];
  return rows.flatMap((r) => { const m = matchRank(r, text.trim()); return m ? [[m[0], r.name, r.clusterId, m[1]]] : []; })
    .sort((a, b) => compareKeys(a, b)).slice(0, 10).map(([, name, clusterId, why]) => ({ name, clusterId, why }));
}
const QUOTA_COLUMNS = ["name", "clusterId", "env", "team", "tier", "cpuUsed", "cpuHard", "memoryUsed", "memoryHard", "podsUsed", "podsHard", "used", "expiresAt", "tierOutdated"];
/** GET /api/v1/quotas:export: the CSV of Python's csv module, with its \r\n and its True and False. */
export function quotaCsv(rows, q) {
  const others = quotaOrder(rows, q) ?? [];
  const ordered = q.state ? others.filter(QUOTA_FACETS[q.state] ?? (() => true)) : others;
  const cell = (v) => (v === null || v === undefined ? "" : v === true ? "True" : v === false ? "False" : typeof v === "number" && Number.isInteger(v) ? `${v}.0` : String(v));
  const line = (r) => QUOTA_COLUMNS.map((c) => cell({ ...r, cpuUsed: r.cpu[0], cpuHard: r.cpu[1], memoryUsed: r.memory[0], memoryHard: r.memory[1], podsUsed: r.pods[0], podsHard: r.pods[1] }[c])).join(",");
  return [QUOTA_COLUMNS.join(","), ...ordered.slice(0, 10_000).map(line)].map((l) => `${l}\r\n`).join("");
}


// The expiration list of the API (cmapi/src/cmapi/plugins/expiration/router.py): the same states, filters, sorts, counts and
// keyset cursor bound to the filters and the state, counted from one fixed day, so that the portal is held to its rules.
const EXP_SAMPLE = SAMPLES.operations.expiration_expirations.response.body;
export const EXP_RULES = EXP_SAMPLE.rules;
const URGENCY = { grace: 0, expiring: 1, pending_delete: 2, active: 3, permanent: 4 };
const EXP_STATES = { attention: (r) => ["expiring", "grace", "pending_delete"].includes(r.state), expiring: (r) => r.state === "expiring", grace: (r) => r.state === "grace",
  pending_delete: (r) => r.state === "pending_delete", active: (r) => r.state === "active", permanent: (r) => r.state === "permanent" };
const EXP_SORTS = { urgency: (r) => [URGENCY[r.state] * 1_000_000 + (r.daysLeft ?? 99_999), r.name, r.clusterId], name: (r) => ["", r.name, r.clusterId] };
const isoPlus = (iso, days) => new Date(Date.parse(iso) + days * 864e5).toISOString().slice(0, 10);
/** The state of a date counted from `today`, as rules.py decides it (notices at 14 days, grace of 7). */
export function expiryState(expiresAt, today, rules = EXP_RULES.dev) {
  if (!expiresAt) return "permanent";
  const left = Math.round((Date.parse(expiresAt) - Date.parse(today)) / 864e5);
  return left > Math.max(...rules.notifyDaysBefore) ? "active" : left > 0 ? "expiring" : -left < rules.graceDays ? "grace" : "pending_delete";
}
/** One row of the list for a namespace, its date and its creation day, counted from `today`. */
export function expiryRow({ name, clusterId = "CRC", env = "dev", team = "payments", created, expiresAt = null, today, noticesSent = 0, openRequest = null }) {
  const rules = EXP_RULES.dev, daysLeft = expiresAt ? Math.round((Date.parse(expiresAt) - Date.parse(today)) / 864e5) : null;
  return { ...EXP_SAMPLE.items[0], name, clusterId, env, team, app: null, created, expiresAt, daysLeft, state: expiryState(expiresAt, today),
    graceEnds: expiresAt ? isoPlus(expiresAt, rules.graceDays) : null, lifetimeDays: expiresAt && created ? Math.round((Date.parse(expiresAt) - Date.parse(created)) / 864e5) : null,
    noticesSent, openRequest };
}
/** `count` rows over every state: permanent, active, expiring, in grace and past grace. Not sorted. */
export function expirationsFrom(count, today, { envs = ["dev", "rnd"] } = {}) {
  const offsets = [null, 40, 9, 1, 0, -3, -6, -9, 20, null, 14, 15];
  return Array.from({ length: count }, (_, i) => {
    const team = TEAMS[i % TEAMS.length], env = envs[i % envs.length], offset = offsets[i % offsets.length];
    return expiryRow({ name: `${team}-${APPS[Math.floor(i / TEAMS.length) % APPS.length]}-${env}`, env, team, created: isoPlus(today, -30 - (i % 50)),
      expiresAt: offset === null ? null : isoPlus(today, offset), today, noticesSent: offset !== null && offset <= 7 ? 2 : 0 });
  });
}
export function expiryQueryOf(params) {
  const get = (k) => params.get(k) || "";
  return { q: get("q"), env: get("env"), clusterId: get("clusterId"), team: get("team"), state: get("state"), sort: get("sort") || "urgency",
    limit: Number(params.get("limit") ?? 50), cursor: params.get("cursor") };
}
const expiryHash = (q) => JSON.stringify([q.q.toLowerCase(), q.env, q.clusterId, q.team, q.state, q.sort]);
/** GET /api/v1/expirations: a page, or a problem as [status, code, detail]. */
export function expirationPage(rows, q, today) {
  if (q.state && !EXP_STATES[q.state]) return [422, "validation-failed", `state is one of ${Object.keys(EXP_STATES).sort()}, not ${q.state}`];
  if (![25, 50, 100].includes(q.limit) && !(q.limit > 0 && q.limit <= 200)) return [400, "invalid-limit", "limit is one of (25, 50, 100), at most 200"];
  const key = EXP_SORTS[q.sort];
  if (!key) return [400, "invalid-sort", `Unknown sort ${q.sort}`];
  const filters = [["env", q.env], ["clusterId", q.clusterId], ["team", q.team]].filter(([, v]) => v);
  const others = rows.filter((r) => filters.every(([k, v]) => String(r[k]) === v) && (!q.q || matchRank(r, q.q))).sort((a, b) => compareKeys(key(a), key(b)));
  const ordered = q.state ? others.filter(EXP_STATES[q.state]) : others;
  const keys = ordered.map(key), total = ordered.length;
  let start = 0, end = Math.min(total, q.limit);
  if (q.cursor) {
    let c = null;
    try { c = JSON.parse(Buffer.from(q.cursor, "base64url").toString()); } catch { /* refused below */ }
    if (!c || c.h !== expiryHash(q)) return [400, "invalid-cursor", "Filters or sort changed since this cursor was issued"];
    if (c.d === "next") { start = keys.findIndex((k) => compareKeys(k, c.k) > 0); if (start < 0) start = total; end = Math.min(total, start + q.limit); }
    else { end = keys.findIndex((k) => compareKeys(k, c.k) >= 0); if (end < 0) end = total; start = Math.max(0, end - q.limit); }
  }
  const items = ordered.slice(start, end);
  const sign = (k, d) => Buffer.from(JSON.stringify({ k, d, h: expiryHash(q) })).toString("base64url");
  const letters = {};
  for (const r of ordered) letters[r.name[0].toUpperCase()] = (letters[r.name[0].toUpperCase()] ?? 0) + 1;
  const facets = Object.fromEntries(Object.entries(EXP_STATES).map(([name, test]) => [name, others.filter(test).length]));
  const envs = [...new Set(rows.map((r) => r.env))].sort();
  return { items, letters, facets, rules: rows.length ? Object.fromEntries(envs.map((e) => [e, EXP_RULES.dev])) : {}, today,
    page: { limit: q.limit, total, from: items.length ? start + 1 : 0, to: end,
      nextCursor: items.length && end < total ? sign(keys[end - 1], "next") : null, prevCursor: items.length && start > 0 ? sign(keys[start], "prev") : null } };
}

// The Policies tab's API (cmapi/src/cmapi/plugins/policies/router.py): the recorded answers of GET /api/v1/policies/results and
// /rejections, and a fleet built from them with each state of a cluster, for the states and the paging. The keyset cursor is bound
// to the filters, as the API's; the counts of `policies` follow clusterId, as the API's.
export const POLICY_SAMPLE = SAMPLES.operations.policies_results.response.body;
export const REJECTION_SAMPLE = SAMPLES.operations.policies_rejections.response.body;
const VERDICTS = ["pass", "fail", "warn", "error", "skip"];
const zero = () => Object.fromEntries(VERDICTS.map((v) => [v, 0]));
/** A cluster of the recorded answer, in another state: the API's null counts, never zeros, for what is not known. */
export function policyCluster(base, { clusterId, env = base.env, state = "ok", stateDetail = null, counts = base.counts, asOf = base.asOf, bundle = base.bundle, dropped = 0,
  hidden = base.hidden, liveActions = base.liveActions, mode = base.mode }) {
  const unknown = ["loading", "not-installed", "forbidden", "unreachable", "mode-off", "engine-off"].includes(state);
  return { ...base, clusterId, env, mode, state, stateDetail, asOf, liveActions: unknown ? [] : liveActions, bundle: unknown ? null : bundle,
    counts: unknown ? null : counts, hidden: unknown ? null : hidden, dropped: unknown ? null : dropped };
}
/** `count` failing rows over the recorded row's policy and a second one, on CRC, each namespace its own. */
export function policyRowsFrom(count, { clusterId = "CRC" } = {}) {
  const row = POLICY_SAMPLE.items[0];
  const second = POLICY_SAMPLE.policies.find((p) => p.name !== row.policy && p.check?.rule === "pattern") ?? POLICY_SAMPLE.policies[1];
  return Array.from({ length: count }, (_, i) => {
    const ns = `${TEAMS[i % TEAMS.length]}-${APPS[Math.floor(i / TEAMS.length) % APPS.length]}-dev`;
    const odd = i % 3 === 2;
    return { ...row, clusterId, namespace: ns, resource: { ...row.resource, name: ns }, policy: odd ? second.name : row.policy, rule: odd ? second.check.rule : row.rule,
      result: ["fail", "fail", "warn", "error"][i % 4], message: `${row.message} (${ns})` };
  });
}
/** The fleet of the Policies checks: CRC with rows, and a cluster in each other state of the API. */
export function policyFleet(rows = policyRowsFrom(30)) {
  const base = POLICY_SAMPLE.clusters[0];
  const fails = (cid, v) => rows.filter((r) => r.clusterId === cid && r.result === v).length;
  const crc = { ...base, counts: { ...base.counts, fail: fails("CRC", "fail"), warn: fails("CRC", "warn"), error: fails("CRC", "error") }, hidden: { unmanaged: 1840, otherPolicies: 41, stale: 2 } };
  const clusters = [crc,
    policyCluster(base, { clusterId: "OCP_GF6", env: "rnd", state: "drift", stateDetail: "1 missing, 3 differ from the render, 0 without the actions Audit, Warn of mode audit",
      bundle: { ...base.bundle, live: 30, current: 27, missing: [POLICY_SAMPLE.policies[0].name], differing: POLICY_SAMPLE.policies.slice(1, 4).map((p) => p.name) }, counts: zero() }),
    policyCluster(base, { clusterId: "OCP_GF7", env: "rnd", state: "unreachable", stateDetail: "the cluster is unreachable: fake cluster down", asOf: "2026-11-17T15:30:00Z" }),
    policyCluster(base, { clusterId: "OCP_GF9", env: "rnd", state: "not-installed", stateDetail: "wgpolicyk8s.io/v1alpha2 is not served: Kyverno is not installed on the cluster", asOf: null }),
    policyCluster(base, { clusterId: "OCP_GF8", env: "rnd", state: "forbidden", stateDetail: "cmapi-reader may not list clusterpolicyreports: the reader's ClusterRole needs get, list and watch on them", asOf: null }),
    policyCluster(base, { clusterId: "OCP_GF10", env: "rnd", state: "capped", stateDetail: "140 rows past policy.reports.maxResultsPerCluster (20000) are counted and not listed", dropped: 140, counts: zero() }),
    policyCluster(base, { clusterId: "OCP_GF11", env: "rnd", mode: "enforce", liveActions: ["Deny"], state: "stale", stateDetail: "no good read of the reports for 30 minutes: the counts are the last ones read", counts: zero() })];
  const perCluster = { CRC: Object.fromEntries(POLICY_SAMPLE.policies.map((p) => [p.name, { ...zero(), pass: p.counts.pass + 3,
    fail: rows.filter((r) => r.policy === p.name && r.result === "fail").length, warn: rows.filter((r) => r.policy === p.name && r.result === "warn").length,
    error: rows.filter((r) => r.policy === p.name && r.result === "error").length }])) };
  return { policy: POLICY_SAMPLE.policy, clusters, policies: POLICY_SAMPLE.policies, perCluster, items: rows };
}
const policyKey = (r) => [r.namespace, r.resource.kind, r.resource.name, r.policy, r.kyvernoRule ?? ""].join("/");
/** GET /api/v1/policies/results: a page, or a problem as [status, code, detail]. */
export function policyResultsPage(fleet, params) {
  const result = (params.get("result") || "fail,warn,error").split(",").map((v) => v.trim()).filter(Boolean);
  if (!result.length || result.some((v) => !["fail", "warn", "error"].includes(v))) return [422, "validation-failed", `result is a comma-separated list of ['fail', 'warn', 'error'], not '${params.get("result")}'`];
  const clusterId = params.get("clusterId") || "", policy = params.get("policy") || "", limit = Number(params.get("limit") ?? 50), cursor = params.get("cursor");
  const hash = JSON.stringify([clusterId, policy, [...result].sort().join(",")]);
  const ordered = fleet.items.filter((r) => (!clusterId || r.clusterId === clusterId) && (!policy || r.policy === policy) && result.includes(r.result))
    .sort((a, b) => compareKeys([policyKey(a), a.clusterId], [policyKey(b), b.clusterId]));
  const keys = ordered.map((r) => [policyKey(r), r.clusterId]), total = ordered.length;
  let start = 0, end = Math.min(total, limit);
  if (cursor) {
    let c = null;
    try { c = JSON.parse(Buffer.from(cursor, "base64url").toString()); } catch { /* refused below */ }
    if (!c || c.h !== hash) return [400, "invalid-cursor", "Filters or sort changed since this cursor was issued"];
    if (c.d === "next") { start = keys.findIndex((k) => compareKeys(k, c.k) > 0); if (start < 0) start = total; end = Math.min(total, start + limit); }
    else { end = keys.findIndex((k) => compareKeys(k, c.k) >= 0); if (end < 0) end = total; start = Math.max(0, end - limit); }
  }
  const items = ordered.slice(start, end);
  const sign = (k, d) => Buffer.from(JSON.stringify({ k, d, h: hash })).toString("base64url");
  const letters = {};
  for (const r of ordered) letters[r.namespace[0].toUpperCase()] = (letters[r.namespace[0].toUpperCase()] ?? 0) + 1;
  const scoped = fleet.clusters.filter((c) => c.counts !== null && (!clusterId || c.clusterId === clusterId)).map((c) => c.clusterId);
  // As the API's: a policy's counts sum the scoped clusters that run it with known counts, and are null, never zero, with none.
  const policies = fleet.policies.map((p) => {
    const runs = scoped.filter((cid) => fleet.perCluster[cid]?.[p.name]);
    return { ...p, counts: runs.length ? VERDICTS.reduce((acc, v) => ({ ...acc, [v]: runs.reduce((n, cid) => n + fleet.perCluster[cid][p.name][v], 0) }), {}) : null };
  });
  return { policy: fleet.policy, clusters: fleet.clusters, policies: clusterId && !scoped.length ? [] : policies, items, letters,
    page: { limit, total, from: items.length ? start + 1 : 0, to: end, nextCursor: items.length && end < total ? sign(keys[end - 1], "next") : null,
      prevCursor: items.length && start > 0 ? sign(keys[start], "prev") : null } };
}
/** `count` refusals, newest first: the recorded plan refusal, a warned plan with its request and a CI refusal, in turn. */
export function rejectionsFrom(count, now = Date.parse(REJECTION_SAMPLE.from) + 7 * 864e5) {
  const [plan, ci] = [REJECTION_SAMPLE.items.find((r) => r.stage === "plan") ?? REJECTION_SAMPLE.items[0], REJECTION_SAMPLE.items.find((r) => r.stage === "ci") ?? REJECTION_SAMPLE.items[0]];
  const kyverno = { source: "kyverno", policy: POLICY_SAMPLE.items[0].policy, rule: POLICY_SAMPLE.items[0].rule, kyvernoRule: "validation", path: "clusters/CRC/namespaces/checkout-dev/namespace.yaml",
    severity: "warning", message: "the label keys kubernetes.io/team are not declared in metadata-keys.yaml" };
  return Array.from({ length: count }, (_, i) => {
    const at = new Date(now - (i + 1) * 3_600_000).toISOString();
    const kind = i % 3, namespace = `${TEAMS[i % TEAMS.length]}-dev`;
    const common = { id: `rej-${1000 - i}`, firstAt: at, lastAt: at, count: i === 0 ? 2 : 1, namespace, username: i % 2 ? "cmapi.requester" : "ola" };
    if (kind === 0) return { ...plan, ...common, problem: "policy-violation", findings: [{ source: "cmapi", policy: "metadata-keys", rule: "reserved_key", kyvernoRule: null,
      path: "labels/kubernetes.io/team", severity: "error", message: "kubernetes.io/team is reserved; use cmapi.net/team" }, kyverno] };
    if (kind === 1) return { ...plan, ...common, outcome: "warned", problem: null, requestId: `req-20261117-${String(100 + i).padStart(4, "0")}`, findings: [kyverno] };
    return { ...ci, ...common };
  });
}
/** GET /api/v1/policies/rejections: a page, or a problem. */
export function rejectionsPage(rows, params) {
  const since = params.get("since") || "7d", limit = Number(params.get("limit") ?? 50), cursor = params.get("cursor");
  const days = /^(\d{1,4})d$/.exec(since)?.[1];
  if (!days || Number(days) < 1 || Number(days) > 90) return [422, "validation-failed", `since is 1d to 90d, not '${since}'`];
  const ordered = [...rows].sort((a, b) => compareKeys([-Date.parse(a.firstAt), a.namespace, a.id], [-Date.parse(b.firstAt), b.namespace, b.id]));
  let start = 0;
  if (cursor) {
    let c = null;
    try { c = JSON.parse(Buffer.from(cursor, "base64url").toString()); } catch { /* refused below */ }
    if (!c || c.since !== since) return [400, "invalid-cursor", "Filters or sort changed since this cursor was issued"];
    start = c.at;
  }
  const items = ordered.slice(start, start + limit);
  const at = (n) => Buffer.from(JSON.stringify({ at: n, since })).toString("base64url");
  const letters = {};
  for (const r of ordered) letters[r.namespace[0].toUpperCase()] = (letters[r.namespace[0].toUpperCase()] ?? 0) + 1;
  return { since, from: new Date(Date.now() - Number(days) * 864e5).toISOString(), truncated: false, items, letters,
    page: { limit, total: ordered.length, from: items.length ? start + 1 : 0, to: start + items.length, nextCursor: start + limit < ordered.length ? at(start + limit) : null,
      prevCursor: start > 0 ? at(Math.max(0, start - limit)) : null } };
}

// The Capacity tab's API (cmapi/src/cmapi/plugins/capacity/router.py, #302): the recorded answer of GET /api/v1/capacity, and a
// fleet built from it with a cluster in each state. capacityGroups is a test fixture of the API's group rules (core/capacity.py,
// group_figures): the page sums nothing, so the fixture gives it the figures the API would.
export const CAPACITY_SAMPLE = SAMPLES.operations.capacity_capacity.response.body;
const GIB = 2 ** 30;
const STATUS_ORDER = ["ok", "warn", "critical", "over"];
const levelOf = (r, warn = 0.85, critical = 0.95) => (r > 1 ? "over" : r >= critical ? "critical" : r >= warn ? "warn" : "ok");
const boundOf = (c, m) => (c === null || m === null ? null : Math.round(c * 1000) === Math.round(m * 1000) ? "both" : c > m ? "cpu" : "memory");
const worstOf = (statuses) => statuses.filter(Boolean).sort((a, b) => STATUS_ORDER.indexOf(b) - STATUS_ORDER.indexOf(a))[0] ?? null;
/** One resource as the API gives it: unit, size, limit = basis × overcommit, and the figures that follow, null when unknown. */
function capResource(base, { committed, simulated, allocatable, basis, overcommit }) {
  const size = basis === "simulated" ? simulated : basis === "allocatable" ? allocatable : null;
  const limit = size === null ? null : Math.floor(size * overcommit);
  const known = committed !== null && limit !== null;
  const commitment = known ? Math.round((committed / limit) * 1e4) / 1e4 : null;
  return { ...base, simulated, allocatable, overcommit, limit, committed, quotaUsed: committed === null ? null : 0, quotaUsedMissing: committed === null ? null : 0,
    headroom: known ? limit - committed : null, commitment, status: commitment === null ? null : levelOf(commitment), requested: null, usedAvg: null, usedPeak: null };
}
/** A cluster of the recorded answer in another state, with its figures: millicores and bytes, null when the API does not know them. */
export function capacityCluster(base, { clusterId, env = "rnd", region = "us-central", writes = true, state = "ok", stateDetail = null, asOf = "2026-11-18T09:14:00Z",
  basis = "allocatable", nodesState = "ok", nodesDetail = null, zones = ["us-central-1a", "us-central-1b", "us-central-1c"], cpu = 0, memory = 0,
  simulated = null, allocatable = { cpu: 96000, memory: 384 * GIB }, overcommit = { cpu: 2, memory: 1.25 } }) {
  const committedKnown = ["ok", "stale", "no-size"].includes(state);
  const nodesKnown = ["ok", "stale"].includes(nodesState);
  const resource = (r) => capResource(base[r], { committed: committedKnown ? (r === "cpu" ? cpu : memory) : null, simulated: simulated ? simulated[r] : null,
    allocatable: nodesKnown ? allocatable[r] : null, basis: state === "no-size" ? null : basis, overcommit: overcommit[r] });
  const c = resource("cpu"), m = resource("memory");
  return { ...base, clusterId, env, region, writes, state, stateDetail, asOf: state === "loading" || state === "forbidden" ? null : asOf,
    basis: state === "no-size" ? null : basis, nodesState, nodesDetail, nodes: nodesKnown ? { total: 3, counted: 3, notReady: 0, cordoned: 0, tainted: 0 } : null,
    zones: nodesKnown ? zones : null, managedNamespaces: committedKnown ? 12 : null, scopedQuotas: committedKnown ? 0 : null,
    status: worstOf([c.status, m.status]), boundBy: boundOf(c.commitment, m.commitment), cpu: c, memory: m, history: null };
}
/** The groups of a set of clusters by region and environment, by the API's rules: included when ok and writable; the ratio from the
 * summed figures; headroom floored at 0 per cluster; the largest placement per resource with its cluster; the worst status. */
export function capacityGroups(clusters) {
  const keyOf = (c) => `${c.region ?? "—"} · ${c.env}`;
  const names = [...new Set(clusters.map(keyOf))].sort();
  return names.map((name) => {
    const members = clusters.filter((c) => keyOf(c) === name);
    const included = members.filter((c) => c.state === "ok" && c.writes);
    const excluded = members.filter((c) => !included.includes(c)).map((c) => ({ clusterId: c.clusterId, reason: c.state !== "ok" ? c.state : "not-writable", asOf: c.asOf }));
    const sum = (r) => {
      if (!included.length) return null;
      const committed = included.reduce((n, c) => n + c[r].committed, 0), limit = included.reduce((n, c) => n + c[r].limit, 0);
      const floored = included.map((c) => [Math.max(c[r].headroom, 0), c.clusterId]).sort((a, b) => b[0] - a[0] || (a[1] < b[1] ? -1 : 1));
      return { unit: r === "cpu" ? "millicores" : "bytes", committed, limit, commitment: Math.round((committed / limit) * 1e4) / 1e4,
        headroom: floored.reduce((n, [h]) => n + h, 0), largestPlacement: { value: floored[0][0], clusterId: floored[0][1] } };
    };
    const cpu = sum("cpu"), memory = sum("memory"), status = worstOf(included.map((c) => c.status));
    return { key: { region: members[0].region, environment: members[0].env }, name, clusterIds: members.map((c) => c.clusterId), matching: members.length,
      included: included.length, coverage: Math.round((included.length / members.length) * 1e4) / 1e4, excluded, status,
      statusCounts: Object.fromEntries(STATUS_ORDER.map((s) => [s, included.filter((c) => c.status === s).length])),
      boundBy: cpu && memory ? boundOf(cpu.commitment, memory.commitment) : null, cpu, memory };
  });
}
/** The fleet of the Capacity checks: CRC as the arbitration says it must show, a second dev cluster whose memory has the most room, and a
 * cluster in each other state of the API. rnd's overcommit is 1.5 and 1.1, so the footnote cannot come from one constant. */
export function capacityFleet() {
  const base = CAPACITY_SAMPLE.clusters[0];
  const rnd = { cpu: 1.5, memory: 1.1 };
  const forbiddenNodes = { nodesState: "forbidden", nodesDetail: "cmapi-reader may not list nodes (403): its ClusterRole needs get, list and watch on nodes" };
  const clusters = [
    capacityCluster(base, { clusterId: "CRC", env: "dev", basis: "simulated", zones: [], cpu: 72000, memory: 144 * GIB, simulated: { cpu: 64000, memory: 256 * GIB },
      allocatable: { cpu: 7800, memory: 20013044 * 1024 } }),
    capacityCluster(base, { clusterId: "OCP_GF15", env: "dev", zones: ["us-central-1a", "us-central-1b"], cpu: 170000, memory: 100 * GIB }),
    capacityCluster(base, { clusterId: "OCP_GF6", overcommit: rnd, cpu: 126000, memory: 300 * GIB }),
    capacityCluster(base, { clusterId: "OCP_GF7", overcommit: rnd, state: "stale", stateDetail: "the ResourceQuota watch is stale: no good read for over 1800s",
      asOf: "2026-11-18T07:30:00Z", cpu: 90000, memory: 300 * GIB }),
    capacityCluster(base, { clusterId: "OCP_GF8", overcommit: rnd, cpu: 886200, memory: 1600 * GIB }),
    capacityCluster(base, { clusterId: "OCP_GF9", overcommit: rnd, state: "unreachable", stateDetail: "the cluster is unreachable: OCP_GF9: ConnectError",
      nodesState: "unreachable", nodesDetail: "the cluster is unreachable", asOf: "2026-11-18T06:02:00Z" }),
    capacityCluster(base, { clusterId: "OCP_GF10", region: "eu-west", overcommit: rnd, state: "loading", stateDetail: "the cluster's ResourceQuotas have not listed yet",
      nodesState: "loading", nodesDetail: "the nodes are being listed" }),
    capacityCluster(base, { clusterId: "OCP_GF11", region: "eu-west", overcommit: rnd, state: "forbidden",
      stateDetail: "the API server refuses the reader's ResourceQuota reads (403): 403 on /api/v1/resourcequotas: forbidden" }),
    capacityCluster(base, { clusterId: "OCP_GF12", region: "eu-west", overcommit: rnd, state: "no-size", ...forbiddenNodes,
      stateDetail: `no simulatedCapacity in clusters.yaml, and the nodes' allocatable is not known: ${forbiddenNodes.nodesDetail}`, cpu: 12000, memory: 24 * GIB }),
    capacityCluster(base, { clusterId: "OCP_GF14", region: "eu-west", overcommit: rnd, writes: false, basis: "simulated", simulated: { cpu: 32000, memory: 128 * GIB },
      ...forbiddenNodes, cpu: 8000, memory: 16 * GIB })
  ].sort((a, b) => (a.clusterId < b.clusterId ? -1 : 1));
  const targets = CAPACITY_SAMPLE.targets.map((t) => (t.env === "rnd" ? { ...t, overcommit: rnd } : t));
  // Two clusters of an environment that the caller cannot read: the API counts them and names none.
  return { ...CAPACITY_SAMPLE, hiddenClusters: 2, targets, clusters, groups: capacityGroups(clusters) };
}

const QUANTITY = { "": 1, m: 1e-3, k: 1e3, M: 1e6, G: 1e9, Ki: 2 ** 10, Mi: 2 ** 20, Gi: 2 ** 30, Ti: 2 ** 40 };
/** A Kubernetes quantity as a number ("500m" is 0.5), or null. */
const quantity = (text) => { const m = /^(\d+(?:\.\d+)?)(m|k|M|G|Ki|Mi|Gi|Ti)?$/.exec(String(text ?? "")); return m ? Number(m[1]) * QUANTITY[m[2] ?? ""] : null; };
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
    created: 0,
    /** The namespaces of GET /api/v1/quotas, each with the etag of its folder in Git. */
    quotas: SAMPLES.operations.quotas_quotas.response.body.items,
    etags: new Map(),
    kpi: SAMPLES.operations.admin_kpi.response.body,
    planUpdate: SAMPLES.operations["namespaces_update_namespace:dryRun"].response.body,
    updated: SAMPLES.operations.namespaces_update_namespace.response.body,
    /** The namespaces of GET /api/v1/expirations, and the day that the API counts from. */
    expirations: [], today: EXP_SAMPLE.today, never: false,
    /** The answer of GET /api/v1/metadata-keys: the instance's rules of labels and annotations. */
    metadataKeys: REFERENCE_KEYS,
    /** "cluster/namespace" → its protectedBy, the protected.labels entries that its labels in Git match (#366). */
    protection: new Map(),
    /** GET /api/v1/policies/results (policyFleet) and the rows of GET /api/v1/policies/rejections (#302). */
    policies: policyFleet(), rejections: rejectionsFrom(3),
    /** GET /api/v1/capacity (capacityFleet), and how many of its reads were answered 304 Not Modified (#302). */
    capacity: capacityFleet(), notModified: 0
  };
  const problem = (res, body, cors) => {
    res.writeHead(body.status, { ...cors, "content-type": "application/problem+json" });
    res.end(JSON.stringify(body));
  };
  const refuse = (status, code, detail) => ({ type: `https://cmapi.ephico2real.com/problems/${code}`, title: code, status, code, detail });
  const server = createServer(async (req, res) => {
    const url = new URL(req.url, "http://api");
    // The API allows the portal's origin and no other, and takes no cookie. The headers are cmapi/src/cmapi/core/cors.py's.
    const cors = { "access-control-allow-origin": portalOrigin(), "access-control-allow-headers": "authorization, content-type, idempotency-key, if-match",
      "access-control-allow-methods": "GET, POST, PATCH", "access-control-expose-headers": "etag", vary: "origin" };
    if (req.method === "OPTIONS") {
      res.writeHead(204, cors);
      return res.end();
    }
    const bearer = /^Bearer (.+)$/.exec(req.headers.authorization ?? "")?.[1];
    const user = bearer ? issuer.whoHas(bearer) : null;
    const body = req.method === "POST" || req.method === "PATCH" ? await bodyOf(req) : null;
    const call = { method: req.method, path: url.pathname, query: Object.fromEntries(url.searchParams), user: user?.username ?? null, cookie: req.headers.cookie ?? null,
      origin: req.headers.origin ?? null, key: req.headers["idempotency-key"] ?? null, ifMatch: req.headers["if-match"] ?? null,
      ifNoneMatch: req.headers["if-none-match"] ?? null, body };
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
    // cmapi/src/cmapi/core/metadata.py check() and pipeline.py _metadata_refusal(): an operator-only label from anyone else
    // is 403; from an operator, a protection label takes "true", or null to remove it (#366).
    const protectionRefusal = (labels) => {
      const sent = Object.keys(labels ?? {}).filter((k) => PROTECTION_LABELS.includes(k));
      if (!sent.length) return null;
      if (!permissions.includes(PROTECT_PERMISSION)) return refuse(403, "forbidden", `Only an operator (namespaces:protect) may set ${sent.join(", ")}`);
      const errors = sent.filter((k) => labels[k] !== null && labels[k] !== "true")
        .map((key) => ({ code: "invalid_value", key, kind: "label", detail: "only 'true', the value that protects; null removes it" }));
      return errors.length ? { ...SAMPLES.problems["policy-violation"].response.body, errors } : null;
    };
    const find = (id) => state.items.find((r) => r.requestId === id);
    // A decision makes a new copy: the recorded samples are shared by every check and stay as they were recorded.
    const replace = (r, fields) => {
      const next = { ...r, ...fields };
      state.items = state.items.map((x) => (x === r ? next : x));
      return next;
    };

    if (url.pathname === "/api/v1/me") {
      const me = SAMPLES.operations.core_me.response.body;
      // cmapi/src/cmapi/core/authz.py, is_operator and operator_environments: an operator holds namespaces:protect (#366).
      const operator = permissions.includes(PROTECT_PERMISSION);
      return ok({ ...me, username: user.username, roles: [user.role], groups: user.groups, identity: { ...me.identity, username: user.username, sub: user.sub, email: user.email ?? null },
        access: { permissions, roles: [{ role: user.role, permissions, environments: ROLE_ENVIRONMENTS[user.role] ?? "all" }] },
        operator, operatorEnvironments: operator ? ROLE_ENVIRONMENTS[user.role] ?? "all" : [] });
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
    if (url.pathname === "/api/v1/metadata-keys") {
      // cmapi/src/cmapi/routers/me.py: objects:read; a strong ETag over the bytes, private, no-cache; 304 on If-None-Match
      // by the weak comparison (RFC 9110, 13.1.2).
      const denied = lacks("objects:read");
      if (denied) return problem(res, denied, cors);
      const text = JSON.stringify(state.metadataKeys);
      const etag = `"${createHash("sha256").update(text).digest("hex").slice(0, 32)}"`;
      const headers = { ...cors, etag, "cache-control": "private, no-cache" };
      const tags = (call.ifNoneMatch ?? "").split(",").map((t) => t.trim().replace(/^W\//, ""));
      if (tags.includes(etag) || tags.includes("*")) {
        res.writeHead(304, headers);
        return res.end();
      }
      res.writeHead(200, { ...headers, "content-type": "application/json" });
      return res.end(text);
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
      // cmapi/src/cmapi/core/metadata.py, validate(): each required key of the instance's rules, in the shape of the recorded
      // refusal. The stand-in runs no configured pattern: an operator's pattern can backtrack, and cmapi matches with RE2.
      const missing = ["labels", "annotations"].flatMap((map) => (state.metadataKeys[map].required ?? [])
        .filter((key) => !body[map]?.[key])
        .map((key) => ({ code: "missing_required_key", key, kind: map.slice(0, -1), detail: state.metadataKeys[map].properties[key]["x-cmapi-rule"] })));
      if (missing.length) return problem(res, { ...SAMPLES.problems["policy-violation"].response.body, errors: missing }, cors);
      const protection = protectionRefusal(body.labels);
      if (protection) return problem(res, protection, cors);
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

    if (url.pathname === "/api/v1/quotas" || url.pathname === "/api/v1/quotas:suggest" || url.pathname === "/api/v1/quotas:export") {
      const denied = lacks("objects:read");
      if (denied) return problem(res, denied, cors);
      const rows = state.mode === "empty" ? [] : state.quotas;
      if (url.pathname === "/api/v1/quotas:suggest") return ok({ items: quotaSuggest(rows, url.searchParams.get("q") ?? "") });
      const q = quotaQueryOf(url.searchParams);
      if (url.pathname === "/api/v1/quotas:export") {
        if (state.lose.has(route)) return req.socket.destroy();
        res.writeHead(200, { ...cors, "content-type": "text/csv; charset=utf-8", "content-disposition": 'attachment; filename="quotas.csv"' });
        return res.end(quotaCsv(rows, q));
      }
      const page = quotaPage(rows, q);
      if (Array.isArray(page)) return problem(res, refuse(...page), cors);
      return ok(page);
    }
    if (url.pathname === "/api/v1/expirations") {
      const denied = lacks("objects:read");
      if (denied) return problem(res, denied, cors);
      const rows = state.mode === "empty" || state.never ? [] : state.expirations;
      const page = expirationPage(rows, expiryQueryOf(url.searchParams), state.today);
      if (Array.isArray(page)) return problem(res, refuse(...page), cors);
      if (state.mode === "empty" && !state.never) page.rules = { dev: EXP_RULES.dev, rnd: EXP_RULES.dev };
      return ok(page);
    }
    if (url.pathname === "/api/v1/policies/results") {
      const denied = lacks("objects:read");
      if (denied) return problem(res, denied, cors);
      const fleet = state.mode === "empty" ? { ...state.policies, items: [] } : state.policies;
      const page = policyResultsPage(fleet, url.searchParams);
      return Array.isArray(page) ? problem(res, refuse(...page), cors) : ok(page);
    }
    if (url.pathname === "/api/v1/capacity") {
      const denied = lacks("capacity:read");
      if (denied) return problem(res, denied, cors);
      const page = state.mode === "empty" ? { ...state.capacity, clusters: [], groups: [] } : state.capacity;
      // As the API's: a strong ETag over the exact bytes and private, no-cache; an If-None-Match that matches is a 304 with no body.
      const text = JSON.stringify(page), etag = `"${createHash("sha256").update(text).digest("hex").slice(0, 32)}"`;
      const headers = { ...cors, etag, "cache-control": "private, no-cache" };
      if ((call.ifNoneMatch ?? "").split(",").map((t) => t.trim().replace(/^W\//, "")).includes(etag)) {
        state.notModified++;
        res.writeHead(304, headers);
        return res.end();
      }
      res.writeHead(200, { ...headers, "content-type": "application/json" });
      return res.end(text);
    }
    if (url.pathname === "/api/v1/policies/rejections") {
      const denied = lacks("requests:read");
      if (denied) return problem(res, denied, cors);
      const page = rejectionsPage(state.mode === "empty" ? [] : state.rejections, url.searchParams);
      return Array.isArray(page) ? problem(res, refuse(...page), cors) : ok(page);
    }
    const expiry = /^\/api\/v1\/clusters\/([^/]+)\/namespaces\/([^/:]+)\/expiration:(extend|set|makePermanent)$/.exec(url.pathname);
    if (expiry && req.method === "POST") {
      const [, clusterId, ns, route] = expiry;
      const denied = lacks("namespaces:write");
      if (denied) return problem(res, denied, cors);
      const row = state.expirations.find((r) => r.clusterId === clusterId && r.name === ns);
      if (!row) return problem(res, refuse(404, "object-not-found", `${ns} is not managed on ${clusterId}`), cors);
      const dry = url.searchParams.get("dryRun") === "true";
      if (!dry && !call.key) return problem(res, SAMPLES.problems["idempotency-key-required"].response.body, cors);
      // The API's replay comes first: the same key and caller with the same route and body is the first answer again.
      const print = fingerprint({ ...body, route, clusterId, namespace: ns });
      const held = dry ? null : state.keys.get(`${user.sub} ${call.key}`);
      if (held) return held.fingerprint === print ? ok(held.request, 202) : problem(res, refuse(409, "idempotency-replay", "Idempotency-Key was used for a different request"), cors);
      const etag = state.etags.get(`${clusterId}/${ns}`) ?? createHash("sha256").update(`${clusterId}/${ns}`).digest("hex").slice(0, 16);
      state.etags.set(`${clusterId}/${ns}`, etag);
      if (!call.ifMatch) return problem(res, SAMPLES.problems["precondition-required"].response.body, cors);
      if (call.ifMatch.replace(/^"|"$/g, "") !== etag) return problem(res, { ...SAMPLES.problems["precondition-failed"].response.body, etag }, cors);
      // cmapi/src/cmapi/plugins/expiration/rules.py: plan_extend, plan_set and plan_make_permanent.
      const max = EXP_RULES.dev.maxExtensionDays;
      let date = null;
      if (route === "extend") {
        if (!row.expiresAt) return problem(res, refuse(422, "expiration-not-set", "The namespace is permanent; use :set"), cors);
        if (!Number.isInteger(body?.days) || body.days < 1) return problem(res, refuse(422, "validation-failed", "Send days or until"), cors);
        if (body.days > max) return problem(res, refuse(422, "expiration-limit", `One extension adds at most ${max} days`), cors);
        date = isoPlus(row.expiresAt > state.today ? row.expiresAt : state.today, body.days);
      } else if (route === "set") {
        if (row.expiresAt) return problem(res, SAMPLES.problems["expiration-already-set"].response.body, cors);
        if (typeof body?.until !== "string" || body.until <= state.today) return problem(res, refuse(422, "expiration-in-past", "The expiry must be after today"), cors);
        if (Math.round((Date.parse(body.until) - Date.parse(state.today)) / 864e5) > max) return problem(res, refuse(422, "expiration-limit", `A new date is at most ${max} days out`), cors);
        date = body.until;
      } else if (!row.expiresAt) {
        return problem(res, refuse(422, "expiration-not-set", "The namespace is already permanent"), cors);
      }
      const sample = SAMPLES.operations[`namespaces_${route === "extend" ? "extend" : route === "set" ? "set_expiry" : "make_permanent"}:dryRun`].response.body;
      const approval = sample.approval;
      if (dry) {
        const [[path, text]] = Object.entries(sample.files);
        const file = text.replaceAll(/(sprint|notes)-dev/g, ns).replace(/cmapi\.net\/expires-at: '\d{4}-\d{2}-\d{2}'/, `cmapi.net/expires-at: '${date}'`);
        const where = path.replace(/namespaces\/[^/]+\//, `namespaces/${ns}/`).replace(/^clusters\/[^/]+\//, `clusters/${clusterId}/`);
        return ok({ ...sample, etag, changes: { [where]: "changed" }, files: { [where]: file }, capacity: { ...sample.capacity, clusterId } });
      }
      // cmapi/src/cmapi/core/db/repo.py: one open request for each namespace.
      if (row.openRequest) return problem(res, refuse(409, "change-pending", `${row.openRequest} holds ${ns}`), cors);
      const now = new Date().toISOString();
      const requestId = `req-${now.slice(0, 10).replaceAll("-", "")}-7${String(++state.created).padStart(3, "0")}`;
      const pending = approval.slots.length > 0;
      const request = requestWith(state.updated, { requestId, namespace: ns, status: pending ? "pending_approval" : "approved", pr: null, mergeSha: null,
        events: [{ at: now, by: user.username, event: pending ? "plan_needs_approval" : "plan_auto_approved", note: "", status: pending ? "pending_approval" : "approved" }] });
      Object.assign(request, { clusterId, approval, reason: `expiration:${route}`, justification: body?.justification ?? null });
      state.items = [request, ...state.items];
      state.expirations = state.expirations.map((r) => (r === row ? { ...r, openRequest: requestId } : r));
      state.keys.set(`${user.sub} ${call.key}`, { fingerprint: print, request });
      return ok(request, 202);
    }
    const nsPath = /^\/api\/v1\/clusters\/([^/]+)\/namespaces\/([^/:]+)$/.exec(url.pathname);
    if (nsPath && (req.method === "GET" || req.method === "PATCH")) {
      const [, clusterId, ns] = nsPath;
      const denied = lacks(req.method === "GET" ? "objects:read" : "namespaces:write");
      if (denied) return problem(res, denied, cors);
      const row = state.quotas.find((r) => r.clusterId === clusterId && r.name === ns) ?? (req.method === "GET" ? state.expirations.find((r) => r.clusterId === clusterId && r.name === ns) : undefined);
      if (!row) return problem(res, refuse(404, "object-not-found", `No managed namespace ${ns} on ${clusterId}`), cors);
      const etag = state.etags.get(`${clusterId}/${ns}`) ?? createHash("sha256").update(`${clusterId}/${ns}`).digest("hex").slice(0, 16);
      state.etags.set(`${clusterId}/${ns}`, etag);
      if (req.method === "GET") {
        const view = SAMPLES.operations.namespaces_get_namespace.response.body;
        res.writeHead(200, { ...cors, "content-type": "application/json", etag: `"${etag}"` });
        // protectedBy: the entries of protected.labels that the labels in Git match (cmapi/src/cmapi/plugins/namespaces/router.py).
        const protectedBy = state.protection.get(`${clusterId}/${ns}`) ?? [];
        return res.end(JSON.stringify({ ...view, name: ns, clusterId, env: row.env, team: row.team, tier: row.tier, etag, openRequest: row.openRequest ?? null,
          expiresAt: row.expiresAt ?? null, protected: protectedBy.length > 0, protectedBy,
          labels: { ...view.labels, "cmapi.net/cluster-id": clusterId, "cmapi.net/env": row.env, "cmapi.net/team": row.team, "cmapi.net/tier": row.tier } }));
      }
      // cmapi/src/cmapi/core/pipeline.py: If-Match is required, and it must be the folder's etag now (quotes are taken off).
      if (!call.ifMatch) return problem(res, SAMPLES.problems["precondition-required"].response.body, cors);
      if (call.ifMatch.replace(/^"|"$/g, "") !== etag) return problem(res, { ...SAMPLES.problems["precondition-failed"].response.body, etag }, cors);
      const tiers = state.tiers.environments[row.env]?.tiers ?? [];
      const named = tiers.find((t) => t.name === body?.tier);
      if (!body || (body.tier !== undefined && !named)) return problem(res, refuse(422, "validation-failed", `${JSON.stringify(body?.tier)} is not a tier of ${row.env}`), cors);
      const bounds = state.tiers.environments[row.env]?.custom;
      for (const k of ["requests.cpu", "requests.memory"]) {
        const v = body.quota?.[k];
        if (v === undefined) continue;
        const n = quantity(v), lo = quantity(bounds?.min?.[k]), hi = quantity(bounds?.max?.[k]);
        if (n === null || (lo !== null && n < lo) || (hi !== null && n > hi)) return problem(res, refuse(422, "quota-out-of-bounds", `${k} ${v} is outside ${bounds?.min?.[k]} to ${bounds?.max?.[k]}`), cors);
      }
      const protection = protectionRefusal(body.labels);
      if (protection) return problem(res, protection, cors);
      const newCpu = quantity(body.quota?.["requests.cpu"] ?? named?.quota?.["requests.cpu"]) ?? 0, hardCpu = quantity(row.cpu[1]) ?? 0;
      // A larger CPU quota waits for the platform group (the recorded change); another change needs no approval (the recorded dry run).
      // Removing the protection label is a sensitiveKeys change: one approver-platform (test_protected_366.py, measured).
      const unprotect = body.labels && PROTECT_KEY in body.labels && body.labels[PROTECT_KEY] === null;
      const approval = unprotect ? UNPROTECT_APPROVAL : newCpu > hardCpu ? state.updated.approval : state.planUpdate.approval;
      if (url.searchParams.get("dryRun") === "true") {
        const changes = Object.fromEntries(Object.entries(state.planUpdate.changes).map(([path, what]) => [path.replace(/namespaces\/[^/]+\//, `namespaces/${ns}/`).replaceAll("payments-dev", ns).replace(/^clusters\/[^/]+\//, `clusters/${clusterId}/`), what]));
        return ok({ ...state.planUpdate, etag, changes, approval, capacity: { ...state.planUpdate.capacity, clusterId } });
      }
      const key = call.key;
      if (!key) return problem(res, SAMPLES.problems["idempotency-key-required"].response.body, cors);
      const held = state.keys.get(`${user.sub} ${key}`);
      const print = fingerprint({ ...body, clusterId, namespace: ns });
      if (held) return held.fingerprint === print ? ok(held.request, 202) : problem(res, refuse(409, "idempotency-replay", "Idempotency-Key was used for a different request"), cors);
      // cmapi/src/cmapi/core/db/repo.py: one open request for each namespace.
      if (row.openRequest) return problem(res, refuse(409, "change-pending", `${row.openRequest} holds ${ns}`), cors);
      const now = new Date().toISOString();
      const requestId = `req-${now.slice(0, 10).replaceAll("-", "")}-8${String(++state.created).padStart(3, "0")}`;
      const pending = approval.slots.length > 0;
      const request = requestWith(state.updated, { requestId, namespace: ns, status: pending ? "pending_approval" : "approved", pr: null, mergeSha: null,
        events: [{ at: now, by: user.username, event: pending ? "plan_needs_approval" : "plan_auto_approved", note: "", status: pending ? "pending_approval" : "approved" }] });
      Object.assign(request, { clusterId, approval, justification: body.justification ?? null });
      state.items = [request, ...state.items];
      state.quotas = state.quotas.map((r) => (r === row ? { ...r, openRequest: requestId } : r));
      state.keys.set(`${user.sub} ${key}`, { fingerprint: print, request });
      return ok(request, 202);
    }
    if (url.pathname === "/api/v1/admin/kpi") {
      const denied = lacks("reports:read");
      if (denied) return problem(res, denied, cors);
      return ok(state.kpi);
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
