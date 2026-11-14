#!/usr/bin/env node
// Direct tests of the portal's sign-in settings, API client and config checks, with the real libraries and no browser.
// Reviewer 1 (Codex, gpt-6.1-sol) wrote them for its findings on #204: docs/reviews/2026-11-14-issue-204/README.md.
// Node runs the TypeScript sources as they are (type stripping, Node 22.18 or later).
import assert from "node:assert/strict";
const { createApi } = await import("../../src/api/client.ts");
const { oidcSettings } = await import("../../src/portal/auth.ts");
const { InMemoryWebStorage, UserManager, User } = await import("oidc-client-ts");
const defer = () => { let resolve; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve }; };
const tests = [];
const test = (name, run) => tests.push([name, run]);
const originalFetch = globalThis.fetch;
globalThis.window = { sessionStorage: new InMemoryWebStorage(), localStorage: new InMemoryWebStorage() };
globalThis.location = { origin: "https://portal.test", pathname: "/index.html" };
const config = { issuer: "https://issuer.test", apiUrl: "https://api.test", clientId: "portal", instance: "test" };
const managerFor = () => {
  const props = oidcSettings(config);
  const settings = props.userManager?.settings ?? props;
  const Manager = props.userManager?.constructor ?? UserManager;
  let url;
  const manager = new Manager({ ...settings, automaticSilentRenew: false,
    metadata: { issuer: config.issuer, authorization_endpoint: config.issuer + "/auth",
      token_endpoint: config.issuer + "/token", end_session_endpoint: config.issuer + "/logout" }
  }, { prepare: async () => ({ navigate: async (args) => { url = args.url; return { url }; }, close() {} }) });
  props.userManager?.stopSilentRenew();
  return { manager, url: () => url };
};
const oldUser = () => new User({ profile: { sub: "person-A" }, access_token: "access-A",
  refresh_token: "refresh-A", id_token: "id-A", token_type: "Bearer", scope: "openid" });

test("F1 logout: the ID token goes in the body of a POST, and no token is in a URL", async () => {
  const { manager, url } = managerFor();
  const left = [];
  manager.leave = async (endpoint, fields) => { left.push({ endpoint, fields }); };
  await manager.storeUser(oldUser());
  await manager.signoutRedirect();
  assert.equal(url(), undefined, "no redirect navigation: the library's GET with id_token_hint in the query did not run");
  assert.deepEqual(left, [{ endpoint: "https://issuer.test/logout", fields: { client_id: "portal", id_token_hint: "id-A", post_logout_redirect_uri: "https://portal.test/index.html" } }]);
  assert.ok(!/[?#]/.test(left[0].endpoint), "the endpoint has no query");
  assert.equal(await manager.getUser(), null);
});

test("F3 staggered 401s share the replacement token", async () => {
  let token = "old", renewals = 0;
  const late401 = defer(), secondStarted = defer();
  const sent = [];
  globalThis.fetch = async (request) => {
    const bearer = request.headers.get("authorization");
    sent.push(bearer);
    if (bearer === "Bearer old" && sent.length === 2) { secondStarted.resolve(); await late401.promise; }
    return bearer === "Bearer old" ? new Response("{}", { status: 401 }) : Response.json({});
  };
  const api = createApi(config.apiUrl, { token: () => token,
    renew: async () => { ++renewals; token = "new"; return token; }, signIn: async () => assert.fail("unexpected sign in") });
  const first = api.GET("/api/v1/me"), second = api.GET("/api/v1/me");
  await secondStarted.promise;
  await first;
  late401.resolve();
  await second;
  assert.equal(renewals, 1);
  assert.deepEqual(sent, ["Bearer old", "Bearer old", "Bearer new", "Bearer new"]);
});

test("F6 bearer insertion enforces credentials and redirect", async () => {
  let sent;
  globalThis.fetch = async (request) => { sent = request; return Response.json({}); };
  const api = createApi(config.apiUrl, { token: () => "token", renew: async () => undefined, signIn: async () => {} });
  await api.GET("/api/v1/me", { credentials: "include", redirect: "follow" });
  assert.equal(sent.credentials, "omit");
  assert.equal(sent.redirect, "error");
  await assert.rejects(api.GET("/api/v1/me", { baseUrl: "https://other.test" }), /not the API/);
});

test("F7 an in-flight renewal cannot restore a signed-out user", async () => {
  const { manager } = managerFor();
  const entered = defer(), release = defer();
  globalThis.fetch = async () => {
    entered.resolve(); await release.promise;
    return Response.json({ access_token: "access-B", refresh_token: "refresh-B", token_type: "Bearer", scope: "openid" });
  };
  manager.leave = async () => {};
  await manager.storeUser(oldUser());
  const renewal = manager.signinSilent();
  await entered.promise;
  const signout = manager.signoutRedirect();
  // removeUser is the exact boundary at which the unprotected implementation loses the race.
  // Give its asynchronous store operations a complete event-loop turn.
  await new Promise((resolve) => setImmediate(resolve));
  release.resolve();
  await Promise.all([renewal, signout]);
  assert.equal(await manager.getUser(), null);
});

test("F8 discovery cannot downgrade sign-in or token endpoints", async () => {
  const { parseConfig } = await import("../../src/portal/config.ts");
  const checked = parseConfig(config);
  for (const key of ["authorization_endpoint", "token_endpoint", "end_session_endpoint"]) {
    const props = oidcSettings(checked);
    const Manager = props.userManager?.constructor ?? UserManager;
    const settings = props.userManager?.settings ?? props;
    const manager = new Manager({ ...settings, automaticSilentRenew: false }, {
      prepare: async () => ({ navigate: async ({ url }) => ({ url }), close() {} })
    });
    props.userManager?.stopSilentRenew();
    globalThis.fetch = async () => Response.json({ issuer: checked.issuer,
      authorization_endpoint: checked.issuer + "/auth", token_endpoint: checked.issuer + "/token",
      end_session_endpoint: checked.issuer + "/logout", [key]: "http://insecure.example/endpoint" });
    await assert.rejects(manager.signinRedirect(), /https/);
  }
});

test("correct PKCE, transaction storage and callback cleanup", async () => {
  const { manager, url } = managerFor();
  window.sessionStorage.clear(); window.localStorage.clear();
  await manager.signinRedirect({ state: { hash: "#requests?q=pay" } });
  const q = new URL(url()).searchParams;
  assert.equal(q.get("response_type"), "code");
  assert.equal(q.get("code_challenge_method"), "S256");
  assert.match(q.get("code_challenge"), /^[A-Za-z0-9_-]{43}$/);
  assert.ok(q.get("state"));
  const stored = JSON.parse(window.sessionStorage.getItem("oidc." + q.get("state")));
  assert.equal(stored.id, q.get("state"));
  assert.equal(stored.request_type, "si:r");
  assert.equal(stored.code_verifier.length, 96);
  assert.deepEqual(stored.data, { hash: "#requests?q=pay" });
  const id = ["header", Buffer.from(JSON.stringify({ sub: "person-A" })).toString("base64url"), "signature"].join(".");
  globalThis.fetch = async () => Response.json({ access_token: "access-A", refresh_token: "refresh-A",
    id_token: id, token_type: "Bearer", scope: "openid", expires_in: 300 });
  await manager.signinRedirectCallback(`https://portal.test/index.html?code=single-use&state=${q.get("state")}`);
  assert.equal(window.sessionStorage.length, 0);
  assert.equal(window.localStorage.length, 0);
  const memory = await manager.settings.userStore.get(`user:${config.issuer}:portal`);
  for (const token of ["access-A", "refresh-A", id]) assert.ok(memory.includes(token));
  await manager.removeUser();
  const props = oidcSettings(config);
  const targets = [];
  globalThis.history = { replaceState: (_state, _title, target) => targets.push(target) };
  for (const hash of ["#requests?q=pay", "#//other.test/path", "#%0Ajavascript%3Aalert", "javascript:alert(1)", "https://other.test"]) {
    await props.onSigninCallback({ state: { hash } });
    const target = targets.at(-1);
    assert.equal(new URL(target, location.origin).origin, location.origin);
    assert.equal(new URL(target, location.origin).search, "");
    assert.equal(target, "/index.html" + (/^#[\w/?=&%.~+-]*$/.test(hash) ? hash : ""));
  }
  props.userManager?.stopSilentRenew();
});

test("correct config service URL boundaries", async () => {
  const { parseConfig } = await import("../../src/portal/config.ts");
  for (const apiUrl of ["http://api.example", "javascript:alert(1)", "https://u:p@api.test", "https://api.test/api", "https://api.test/?q=x", "https://api.test/#x"]) {
    assert.throws(() => parseConfig({ ...config, apiUrl }));
  }
  for (const issuer of ["http://issuer.example/realm", "ftp://issuer.example", "https://u@issuer.test", "https://issuer.test/?q=x", "https://issuer.test/#x"]) {
    assert.throws(() => parseConfig({ ...config, issuer }));
  }
  for (const apiUrl of ["http://localhost:1234", "http://127.0.0.1:1234", "http://[::1]:1234", "https://api.test"]) {
    assert.equal(parseConfig({ ...config, apiUrl }).apiUrl, apiUrl);
  }
});

test("F10 config rejects empty query and fragment delimiters", async () => {
  const { parseConfig } = await import("../../src/portal/config.ts");
  for (const suffix of ["?", "#"]) {
    assert.throws(() => parseConfig({ ...config, apiUrl: config.apiUrl + suffix }), /query or fragment/);
    assert.throws(() => parseConfig({ ...config, issuer: config.issuer + suffix }), /query or fragment/);
  }
});

let failed = 0;
for (const [name, run] of tests) {
  try { await run(); console.log(`ok - ${name}`); }
  catch (error) { ++failed; console.error(`FAIL - ${name}: ${error.message}`); }
  finally { globalThis.fetch = originalFetch; }
}
console.log(`${failed ? "FAIL" : "ok"} - direct: ${tests.length - failed} of ${tests.length}`);
process.exit(failed ? 1 : 0);

