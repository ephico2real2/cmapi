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

// #336: the New namespace form's labels and annotations, from GET /api/v1/metadata-keys. The two answers are the service's:
// the recorded one of the reference file and the company file's (cmapi/tests/core/test_metadata_form_336.py holds both).
const { readFileSync } = await import("node:fs");
const SAMPLES = JSON.parse(readFileSync(new URL("../../../cmapi/src/cmapi/contract/samples.json", import.meta.url), "utf8"));
const RULES = { reference: SAMPLES.operations.core_metadata_keys.response.body,
  company: JSON.parse(readFileSync(new URL("metadata-keys.company.json", import.meta.url), "utf8")) };
const ecma = (pattern, value) => new RegExp(pattern, "u").test(value);

test("M1 the form never refuses a body that cmapi accepts: every case of the #328 corpus and design B's values, on both files", async () => {
  const { checkAll, fieldsOf, valueKey } = await import("../../src/portal/metadataForm.ts");
  const corpus = JSON.parse(readFileSync(new URL("metadata-corpus.json", import.meta.url), "utf8"));
  const seen = {};
  for (const [name, view] of Object.entries(RULES)) {
    const form = fieldsOf(view);
    const { namespace, environment, cases } = corpus[name];
    // The corpus's body is the required keys at their examples: the form's fields filled with the same examples.
    const base = Object.fromEntries(form.fields.filter((f) => f.required && f.derivedFrom === null).map((f) => [valueKey(f), f.example]));
    const stricter = [], tally = { cases: cases.length, accepted: 0, agree: 0, looser: 0 };
    for (const [kind, key, value, own, accepted] of cases) {
      const values = { ...base };
      if (value === null) delete values[`${kind}:${key}`];
      else values[`${kind}:${key}`] = value;
      const errors = await checkAll(form, values, own ? `${value}-${environment}` : namespace, ecma);
      const refused = Object.entries(errors).filter(([, e]) => e);
      tally.accepted += accepted;
      if (refused.length && accepted) stricter.push({ kind, key, value, own, refused });
      else if (!refused.length && !accepted) tally.looser++;
      else tally.agree++;
    }
    assert.deepEqual(stricter.slice(0, 5), [], `${name}: the form refuses what cmapi accepts`);
    assert.ok(tally.cases > 1000 && tally.accepted > 50 && tally.agree > 0.9 * tally.cases, `${name}: ${JSON.stringify(tally)}`);
    seen[name] = tally;
  }
  console.log(`  differential: ${JSON.stringify(seen)}`);
});

test("M2 the fields of each file: inputs in the order of required, then the keys cmapi sets, then the optional ones; no operator-only key", async () => {
  const { fieldsOf } = await import("../../src/portal/metadataForm.ts");
  // The recorded sample has its properties in alphabetical order (samples.json is written with sort_keys); the service
  // keeps the file's order. Only `required` is an order the form keeps; the optional keys are compared as a set.
  const groups = (view) => {
    const fields = fieldsOf(view).fields;
    for (const kind of ["label", "annotation"]) {
      assert.deepEqual(fields.filter((f) => f.kind === kind).map((f) => f.id), fields.filter((f) => f.kind === kind).map((_, i) => `ns-${kind}-${i}`), "ids by kind and position");
    }
    const row = (f) => [f.key, f.title, f.derivedFrom, f.enum !== null, f.format, f.example];
    return { required: fields.filter((f) => f.required).map(row), derived: fields.filter((f) => f.derivedFrom).map(row),
      optional: fields.filter((f) => !f.required && !f.derivedFrom).map(row).sort() };
  };
  assert.deepEqual(groups(RULES.reference), {
    required: [["cmapi.net/team", "Team", null, false, null, "payments"], ["cmapi.net/team-dl", "Team DL", null, false, "email-in-domains", "payments-team@ephico2real.com"]],
    derived: [],
    optional: [["cmapi.net/app", null, null, false, null, null], ["cmapi.net/cost-center", null, null, false, null, "cc-4410"], ["cmapi.net/rightsizing", null, null, false, null, null]] });
  assert.deepEqual(groups(RULES.company), {
    required: [["company.net/mnemonic", null, null, false, null, "abc"], ["company.net/lob", null, null, false, null, "amgsst"], ["company.net/cl", null, null, true, null, "1"]],
    derived: [["name", null, "namespace", false, null, null], ["company.net/app-environment", null, "environment", false, null, null],
      ["company.net/app-environment", null, "environment", false, null, null]],
    optional: [["company.net/mnemonic-confluence", null, null, false, "url", "https://wiki.company.net/abc"],
      ["company.net/mnemonic-group-contact", null, null, false, "email-in-domains", "abc-team@company.net"]] });
  assert.ok(!fieldsOf(RULES.company).fields.some((f) => f.key === "cmapi.net/protected"), "an operator-only key is not offered");
  // The label-value pattern is checked once, first, not again as a key's own pattern.
  const team = fieldsOf(RULES.reference).fields[0];
  assert.deepEqual(team.patterns, ["^(?:^[a-z0-9-]{2,40}$)$"]);
  assert.equal(fieldsOf(RULES.company).fields[1].patterns.length, 0, "lob: the label syntax only");
});

test("M3 an answer of another shape is the error state, never a form with fields missing", async () => {
  const { fieldsOf, RulesUnreadable } = await import("../../src/portal/metadataForm.ts");
  const bad = [null, [], { labels: [] }, { labels: RULES.reference.labels }, { ...RULES.reference, labels: { ...RULES.reference.labels, properties: { x: "text" } } },
    { ...RULES.reference, labels: { ...RULES.reference.labels, required: ["cmapi.net/owner"] } },
    { ...RULES.reference, labels: { ...RULES.reference.labels, properties: { x: { type: "string", enum: [1] } } } }];
  for (const view of bad) assert.throws(() => fieldsOf(view), (e) => e instanceof RulesUnreadable && /not in the form this portal reads/.test(e.message), JSON.stringify(view)?.slice(0, 80));
});

test("M4 the body: each field with a value; never an empty optional key, a key that cmapi sets, or an operator-only key", async () => {
  const { bodyOf, fieldsOf, nameSuggestion } = await import("../../src/portal/metadataForm.ts");
  const company = fieldsOf(RULES.company);
  const values = { "label:company.net/mnemonic": "abc", "label:company.net/lob": "amgsst", "label:company.net/cl": "1", "label:name": "abc-rnd",
    "annotation:company.net/mnemonic-group-contact": "", "annotation:company.net/mnemonic-confluence": "https://wiki.company.net/abc", "label:cmapi.net/protected": "yes" };
  assert.deepEqual(bodyOf(company, values), { labels: { "company.net/mnemonic": "abc", "company.net/lob": "amgsst", "company.net/cl": "1" },
    annotations: { "company.net/mnemonic-confluence": "https://wiki.company.net/abc" } });
  assert.equal(nameSuggestion(company, values, "rnd"), "abc-rnd", "the namespacePrefix key starts the name");
  const reference = fieldsOf(RULES.reference);
  assert.equal(nameSuggestion(reference, { "label:cmapi.net/team": "payments" }, "dev"), "payments-dev", "no namespacePrefix key: the first required label");
  assert.equal(nameSuggestion(reference, {}, "dev"), "", "nothing typed, nothing suggested");
});

test("M5 a field's check: the validator's order and words, characters as code points, and a pattern not checked here counts as passed", async () => {
  const { checkField, fieldsOf } = await import("../../src/portal/metadataForm.ts");
  const company = fieldsOf(RULES.company);
  const [mnemonic, lob, cl] = company.fields;
  const ctx = { namespace: "abc-rnd", labelValue: company.labelValue };
  assert.equal(await checkField(mnemonic, "", ctx, ecma), "Required: must match ^[a-z]{3,4}$; the start of the namespace name, before its first '-'");
  assert.equal(await checkField(mnemonic, "ABC", ctx, ecma), "Not valid: must match ^[a-z]{3,4}$; the start of the namespace name, before its first '-'");
  assert.equal(await checkField(mnemonic, "a b", ctx, ecma), "Not a valid label value", "the label syntax first, as _syntax");
  assert.equal(await checkField(mnemonic, "xyz", ctx, ecma), "abc-rnd does not start with xyz-");
  assert.equal(await checkField(mnemonic, "abc", ctx, ecma), null);
  assert.equal(await checkField(lob, "amg sst", ctx, ecma), "Not a valid label value");
  assert.equal(await checkField(cl, "9", ctx, ecma), "Not valid: one of ['0', '1', '2', '3', '4', '5', '6']");
  assert.equal(await checkField(mnemonic, "ABC", { ...ctx, namespace: "ABC-rnd" }, () => null), null, "a pattern that ran out of time: no error here, cmapi decides");
  // JSON Schema counts characters (RFC 8259: code points), as Python and cmapi do: three emoji are three, not six.
  const short = { ...company.fields[6], kind: "annotation", patterns: [], maxLength: 3, minLength: 3 };
  assert.equal(await checkField(short, "\u{1F600}\u{1F600}\u{1F600}", ctx, ecma), null);
  assert.equal(await checkField(short, "\u{1F600}\u{1F600}\u{1F600}\u{1F600}", ctx, ecma), "At most 3 characters");
});

test("M6 a refusal's errors: each on the field that it names, the others in the summary; a key the form lacks reads the rules again", async () => {
  const { errorsByField, fieldsOf } = await import("../../src/portal/metadataForm.ts");
  const { itemsOf } = await import("../../src/api/problem.ts");
  const recorded = SAMPLES.problems["policy-violation"].response.body;
  const reference = fieldsOf(RULES.reference);
  const mapped = errorsByField(itemsOf(recorded.errors), reference);
  assert.deepEqual(mapped.byField, { "ns-label-0": "must match ^[a-z0-9-]{2,40}$", "ns-annotation-0": "an address in ['ephico2real.com']" });
  assert.equal(mapped.unknownKey, false);
  const other = errorsByField(itemsOf([{ code: "reserved_key", key: "cmapi.net/x" }, { code: "too_many_keys", kind: "label", detail: "at most 50 other labels" },
    { code: "missing_required_key", key: "cmapi.net/owner", kind: "label", detail: "must match ^[a-z]+$" }, "not an item", { key: "no code" }]), reference);
  assert.deepEqual(other.items.map((i) => [i.field?.id ?? null, i.text]), [[null, "cmapi.net/x: reserved_key"], [null, "label: at most 50 other labels"],
    [null, "cmapi.net/owner: must match ^[a-z]+$"]]);
  assert.equal(other.unknownKey, true);
  // A key that is a label and an annotation: the error's kind decides; with none, the label first.
  const company = fieldsOf(RULES.company);
  assert.deepEqual(errorsByField([{ code: "derived_key", key: "company.net/app-environment", kind: "annotation", detail: "d" }], company).byField, { "ns-annotation-0": "d" });
  assert.deepEqual(errorsByField([{ code: "invalid_value", key: "company.net/app-environment", detail: "d" }], company).byField, { "ns-label-4": "d" });
});

let failed = 0;
for (const [name, run] of tests) {
  try { await run(); console.log(`ok - ${name}`); }
  catch (error) { ++failed; console.error(`FAIL - ${name}: ${error.message}`); }
  finally { globalThis.fetch = originalFetch; }
}
console.log(`${failed ? "FAIL" : "ok"} - direct: ${tests.length - failed} of ${tests.length}`);
process.exit(failed ? 1 : 0);

