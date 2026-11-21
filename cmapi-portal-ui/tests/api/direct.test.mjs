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

test("540 review: call the React and mockup pageSlots functions directly, including every boundary through 200 pages", async () => {
  const { stripTypeScriptTypes } = await import("node:module");
  const source = readFileSync(new URL("../../src/components/ui.tsx", import.meta.url), "utf8");
  const declaration = source.match(/^export function pageSlots\([\s\S]*?^\}/m)?.[0];
  assert.ok(declaration, "test the production function, not a copy of its algorithm");
  const js = stripTypeScriptTypes(declaration.replace(/^export /, ""));
  const reactSlots = new Function(`${js}; return pageSlots;`)();
  const mockup = readFileSync(new URL("../../../mockups/portal/Main.dc.html", import.meta.url), "utf8");
  const script = mockup.slice(mockup.indexOf(">", mockup.indexOf("data-dc-script")) + 1, mockup.lastIndexOf("</script>"));
  const mockSlots = new Function("DCLogic", `${script}; return pageSlots;`)(class {});
  assert.deepEqual(reactSlots(1, 0), []);
  for (let last = 1; last <= 200; last++) {
    for (let page = 1; page <= last; page++) {
      const slots = reactSlots(page, last);
      assert.deepEqual(slots, mockSlots(page, last), `${page}/${last}: mockup parity`);
      assert.ok(slots.length <= 7);
      const pages = slots.filter(Boolean);
      assert.deepEqual(pages, [...new Set(pages)].sort((a, b) => a - b));
      for (const n of [1, last, page, page - 1, page + 1].filter((n) => n >= 1 && n <= last)) assert.ok(pages.includes(n), `${page}/${last}: missing ${n}`);
      if (last <= 7) assert.deepEqual(pages, Array.from({ length: last }, (_, i) => i + 1));
      slots.forEach((n, i) => {
        if (n === 0) assert.ok(slots[i - 1] > 0 && slots[i + 1] - slots[i - 1] > 2, `${page}/${last}: a real gap`);
        else if (i && slots[i - 1]) assert.equal(n, slots[i - 1] + 1, `${page}/${last}: no hidden gap`);
      });
    }
  }
  for (const [page, want] of [[1, [1, 2, 3, 4, 5, 0, 10]], [5, [1, 0, 4, 5, 6, 0, 10]], [10, [1, 0, 6, 7, 8, 9, 10]]]) {
    assert.deepEqual(reactSlots(page, 10), want);
  }
});

test("540 review: mockup page counts, short and empty pages, clamping, and filter/size resets", () => {
  const source = readFileSync(new URL("../../../mockups/portal/Main.dc.html", import.meta.url), "utf8");
  const script = source.slice(source.indexOf(">", source.indexOf("data-dc-script")) + 1, source.lastIndexOf("</script>"));
  class DCLogic {
    constructor(props) { this.props = props; }
    setState(patch) { this.state = { ...this.state, ...patch }; }
  }
  for (const total of [0, 1, 24, 25, 26, 49, 50, 51, 80, 100, 101, 249, 250, 251]) {
    const Component = new Function("DCLogic", `${script}\nPOLICY_DEFS = Array.from({length: ${total}}, (_, i) => ({name: 'review-' + i, kind: 'ValidatingPolicy', what: 'Fixture'})); RENDERED_CHECKS = []; return Component;`)(DCLogic);
    const c = new Component({ instance: "nonprod", startTab: "policies" });
    const pol = () => c.renderVals().pol;
    for (const size of [25, 50, 100]) {
      pol().pg.setRows(size);
      assert.equal(c.state.ppage, 1);
      const last = Math.max(1, Math.ceil(total / size));
      assert.equal(pol().pg.slots.filter((s) => s.isPage).at(-1).text, String(last));
      for (let page = 1; page <= last; page++) {
        pol().pg.go(page);
        assert.deepEqual(pol().pageRows.map((p) => p.name), Array.from({ length: total }, (_, i) => `review-${i}`).slice((page - 1) * size, page * size));
        assert.equal(pol().pg.range, `${total ? (page - 1) * size + 1 : 0}–${Math.min(page * size, total)} of ${total}`);
        assert.equal(pol().pg.prevDis, String(page === 1));
        assert.equal(pol().pg.nextDis, String(page === last));
      }
      pol().pg.go(last + 10);
      assert.equal(pol().pg.page, last, "shrinking results clamp the displayed page");
      pol().clusterOpts[1].pick();
      assert.equal(c.state.ppage, 1);
      pol().clusterOpts[0].pick();
      assert.equal(c.state.ppage, 1, "returning to All clusters also resets");
    }
  }
});

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
  // #479 (A1): the keys that cmapi sets are required too, so they are in both groups; the form still orders them after
  // the inputs and never sends them (bodyOf).
  assert.deepEqual(groups(RULES.company), {
    required: [["company.net/mnemonic", null, null, false, null, "abc"], ["company.net/lob", null, null, false, null, "amgsst"], ["company.net/cl", null, null, true, null, "1"],
      ["name", null, "namespace", false, null, null], ["company.net/app-environment", null, "environment", false, null, null],
      ["company.net/app-environment", null, "environment", false, null, null]],
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
  assert.equal(await checkField(mnemonic, "", ctx, ecma), "Required: must match ^[a-z]{3,4}$; the namespace name starts with this value and '-'");
  assert.equal(await checkField(mnemonic, "ABC", ctx, ecma), "Not valid: must match ^[a-z]{3,4}$; the namespace name starts with this value and '-'");
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

test("407 retained rows have the same visible timestamps across UTC midnight", async () => {
  const { heldPageRows } = await import("./standin.mjs");
  const { whenOf } = await import("../../src/portal/format.ts");
  const before = new Date("2026-11-19T23:59:59.999Z");
  const after = new Date(before.getTime() + 1);
  const { items, rejections } = heldPageRows(before.getTime());
  for (const times of [items.map(r => r.updatedAt), rejections.map(r => r.firstAt)]) {
    const middle = times.slice(25, 50);
    assert.equal(middle.length, 25);
    assert.deepEqual(middle.map(t => whenOf(t, after)), middle.map(t => whenOf(t, before)));
  }
});

// #479 (Phase 4): the pure parts of the New namespace form, on the answer of the configuration of design section 3.1.
const KEYS_479 = JSON.parse(readFileSync(new URL("metadata-keys.company-479.json", import.meta.url), "utf8"));

test("512 the stand-in checks the desired middle on the suffix key", async () => {
  const { createMetadata } = await import("./standin.mjs");
  for (const [namespace, accepted] of [
    ["abc-dev", true], ["abc--dev", false], ["abc--x-dev", false], ["abc-x--dev", false],
    ["abc---dev", false], ["abc-x-y-dev", true], ["abc-x--y-dev", true], ["abc-1-dev", true],
  ]) {
    const { errors } = createMetadata(KEYS_479, { labels: { "company.net/mnemonic": "abc" } },
      { namespace, environment: "dev" });
    assert.deepEqual(errors.map(({ code, key, kind }) => ({ code, key, kind })), accepted ? [] : [
      { code: "invalid_value", key: "company.net/app-environment", kind: "label" },
    ], namespace);
  }
});

test("479-P2 the name's ends: the prefix and suffix keys of the answer, their values, the name and its checks", async () => {
  const { checkName, endValue, fieldsOf, joinName, nameEnds } = await import("../../src/portal/metadataForm.ts");
  const form = fieldsOf(KEYS_479);
  const { start, end } = nameEnds(form);
  assert.deepEqual([start?.key, end?.key, end?.derivedFrom], ["company.net/mnemonic", "company.net/app-environment", "environment"]);
  const target = { namespace: "", environment: "dev", cluster: "CRC", instance: "nonprod" };
  assert.equal(endValue(start, { "label:company.net/mnemonic": "abc" }, target), "abc");
  assert.equal(endValue(end, {}, target), "dev", "the end is the cluster's environment, which cmapi fills in");
  assert.equal(joinName("abc", "payments", "dev"), "abc-payments-dev");
  assert.equal(joinName("abc", "", "dev"), "abc-dev");
  assert.equal(joinName(null, "payments-dev", null), "payments-dev", "an instance with neither end: the whole name");
  assert.equal(checkName("abc", "payments", "dev"), null);
  assert.equal(checkName("abc", "", "dev"), null);
  assert.equal(checkName("abc", "", null), "Type the middle of the name.");
  assert.equal(checkName(null, "", "dev"), "Type the middle of the name.");
  assert.equal(checkName(null, "", null), "Required: a namespace name");
  assert.equal(checkName("a".repeat(60), "", "dev"), "The full name is longer than 63 characters.");
  assert.equal(checkName("abc", "x".repeat(56), "dev"), "The full name is longer than 63 characters.");
  assert.equal(checkName("abc", "x".repeat(55), "dev"), null, "63 characters is the limit, not past it");
  assert.match(checkName("abc", "Pay_ments", "dev"), /^The middle of the name: lowercase letters/);
  assert.equal(checkName("", "payments", "dev"), null, "a missing start: the start's own field says so");
  assert.equal(fieldsOf(RULES.reference).fields.some((f) => f.namespacePrefix || f.namespaceSuffix), false, "the reference file has neither end");
});

test("512 a desired middle starts and ends with a letter or digit", async () => {
  const { checkName } = await import("../../src/portal/metadataForm.ts");
  for (const desired of ["-x", "x-", "-"]) {
    assert.equal(checkName("abc", desired, "dev"), "Start and end with a letter or digit.", desired);
  }
  for (const desired of ["", "x", "1", "x-y", "x--y"]) {
    assert.equal(checkName("abc", desired, "dev"), null, desired);
  }
  assert.equal(checkName(null, "abc--x-dev", null), null, "without locked ends, only the whole name is checked");
  assert.equal(checkName("abc", "-x", null), null, "a prefix alone does not declare a middle");
  assert.equal(checkName(null, "x-", "dev"), null, "a suffix alone does not declare a middle");
});

test("479-P4 a default copies its source until the person edits it, and an unedited default is never sent", async () => {
  const { bodyOf, defaultSource, fieldsOf, shownValues } = await import("../../src/portal/metadataForm.ts");
  const form = fieldsOf(KEYS_479);
  const team = form.fields.find((f) => f.key === "cmapi.net/team");
  assert.equal(team.defaultFrom, "company.net/mnemonic");
  assert.equal(defaultSource(form, team).title, "Mnemonic");
  const typed = { "label:company.net/mnemonic": "abc" };
  assert.equal(shownValues(form, typed)["label:cmapi.net/team"], "abc", "copied from the mnemonic");
  assert.equal(bodyOf(form, typed).labels["cmapi.net/team"], undefined, "not sent: cmapi fills it in (source default:company.net/mnemonic)");
  const edited = { ...typed, "label:cmapi.net/team": "payments" };
  assert.equal(shownValues(form, { ...edited, "label:company.net/mnemonic": "xyz" })["label:cmapi.net/team"], "payments", "an edit is never written over (plan R5)");
  assert.equal(bodyOf(form, edited).labels["cmapi.net/team"], "payments");
  assert.equal(shownValues(form, { ...typed, "label:cmapi.net/team": "" })["label:cmapi.net/team"], "", "emptied is still edited");
});

test("479-P10 extra keys: the answer's propertyNames, additionalProperties and x-cmapi-other-keys, on their rows", async () => {
  const { checkExtras, fieldsOf, prefixWords } = await import("../../src/portal/metadataForm.ts");
  const form = fieldsOf(KEYS_479);
  assert.deepEqual(form.otherKeys.label.prefixes, ["", "*.company.net/"]);
  assert.deepEqual([form.otherKeys.annotation.max, form.otherKeys.annotation.maxValueBytes, form.otherKeys.annotation.maxBytesTotal], [50, 4096, 65536]);
  assert.equal(prefixWords(form.otherKeys.label.prefixes), "*.company.net/ (or none)");
  const rows = (pairs) => pairs.map(([key, value], id) => ({ id, key, value }));
  const keyOf = async (kind, pairs) => Object.values((await checkExtras(form, kind, rows(pairs), ecma)).rows).map((r) => r.key);
  assert.deepEqual(await keyOf("label", [["team.company.net/squad", "checkout"], ["squad", "x"], ["", ""], ["kubernetes.io/x", "a"], ["cmapi.net/team", "a"],
    ["cmapi.net/protected", "true"], ["Bad Key", "a"], ["other.example/x", "a"]]), [null, null, "Enter a key.", "The prefix must be *.company.net/ (or none).",
    "This key has its own field above.", "Only an operator sets this key.", "Not a valid key: an optional DNS prefix and '/', then up to 63 letters, digits, '-', '_' or '.'.",
    "The prefix must be *.company.net/ (or none)."]);
  assert.deepEqual(await keyOf("annotation", [["name", "x"]]), ["cmapi.net sets this key, or it has its own field in the other table.".replace("cmapi.net", "cmapi")],
    "a label's declared key is refused as an annotation (the not of propertyNames)");
  assert.deepEqual(await keyOf("label", [["squad", "a"], ["squad", "b"]]), ["This key is already in the table.", "This key is already in the table."]);
  const values = async (kind, value) => Object.values((await checkExtras(form, kind, rows([["squad", value]]), ecma)).rows)[0].value;
  assert.match(await values("label", "not a label value"), /^A label value: up to 63/);
  assert.equal(await values("label", ""), null, "an empty label value is a label value");
  assert.equal(await values("annotation", "é".repeat(2048)), null, "4096 bytes: the limit");
  assert.equal(await values("annotation", "é".repeat(2049)), "Up to 4096 bytes.", "counted in UTF-8 bytes, as cmapi counts them");
  const many = rows(Array.from({ length: 51 }, (_, i) => [`k${i}`, "v"]));
  assert.deepEqual((await checkExtras(form, "label", many, ecma)).table, ["At most 50 additional labels."]);
  const big = rows(Array.from({ length: 17 }, (_, i) => [`k${i}`, "x".repeat(4000)]));
  assert.deepEqual((await checkExtras(form, "annotation", big, ecma)).table, ["The additional annotations hold more than 65536 bytes in all."]);
});

test("479-P10 the form never refuses an extra key that the schema admits: every allowed shape of the answer's propertyNames", async () => {
  const { checkExtraKey, fieldsOf } = await import("../../src/portal/metadataForm.ts");
  // The admitted keys of the #328 corpus's shapes on this file: no prefix, *.company.net/ at depth one and two, the longest name.
  const form = fieldsOf(KEYS_479);
  for (const key of ["squad", "a", "a.b_c-d", "team.company.net/squad", "a.b.company.net/x", `team.company.net/${"n".repeat(63)}`]) {
    assert.equal(await checkExtraKey(form, "label", key, [{ id: 0, key, value: "" }], ecma), null, key);
    assert.equal(await checkExtraKey(form, "annotation", key, [{ id: 0, key, value: "" }], ecma), null, key);
  }
});

test("479-P11 extra keys go in the same maps as the named fields; a row with no key is not sent", async () => {
  const { bodyOf, fieldsOf } = await import("../../src/portal/metadataForm.ts");
  const form = fieldsOf(KEYS_479);
  const body = bodyOf(form, { "label:company.net/mnemonic": "abc" }, { label: [{ id: 1, key: "team.company.net/squad", value: "checkout" }, { id: 2, key: "", value: "x" }],
    annotation: [{ id: 3, key: "runbook.company.net/url", value: "https://wiki.company.net/abc/runbook" }] });
  assert.deepEqual(body, { labels: { "company.net/mnemonic": "abc", "team.company.net/squad": "checkout" }, annotations: { "runbook.company.net/url": "https://wiki.company.net/abc/runbook" } });
});

test("479-P12 the expiry rules of each environment come from x-cmapi-expiration; maxLifetimeDays warns and never sets a date", async () => {
  const { expiryInfo, expiryRulesOf, fieldsOf, listWords } = await import("../../src/portal/metadataForm.ts");
  const form = fieldsOf(KEYS_479);
  const dev = expiryRulesOf(form, "dev");
  assert.deepEqual(dev, { enabled: true, allowedAtCreate: true, maxLifetimeDays: 180, notifyDaysBefore: [14, 7, 1], graceDays: 7 });
  assert.equal(expiryRulesOf(form, "prod"), null, "an environment that is not listed takes no date");
  const off = fieldsOf({ ...KEYS_479, "x-cmapi-expiration": { environments: { dev: { enabled: false } } } });
  assert.equal(expiryRulesOf(off, "dev"), null, "enabled: false, whatever the environment's name");
  const later = fieldsOf({ ...KEYS_479, "x-cmapi-expiration": { environments: { dev: { ...KEYS_479["x-cmapi-expiration"].environments.dev, allowedAtCreate: false } } } });
  assert.equal(expiryRulesOf(later, "dev"), null, "allowedAtCreate: false takes no date at create");
  assert.deepEqual(expiryInfo("", "2026-11-20", dev), { state: "none" }, "empty: permanent, never a date from the limit (D15)");
  assert.deepEqual(expiryInfo("2026-12-15", "2026-11-20", dev), { state: "date", date: "2026-12-15", days: 25, beyond: false });
  assert.deepEqual(expiryInfo("2027-05-19", "2026-11-20", dev), { state: "date", date: "2027-05-19", days: 180, beyond: false }, "180 days: within the limit");
  assert.deepEqual(expiryInfo("2027-05-20", "2026-11-20", dev), { state: "date", date: "2027-05-20", days: 181, beyond: true }, "past it: one more approval, not a refusal");
  assert.deepEqual(expiryInfo("2026-11-20", "2026-11-20", dev), { state: "bad", error: "Pick a date after today." });
  assert.deepEqual(expiryInfo("2026-02-30", "2026-11-20", dev), { state: "bad", error: "Enter a date as YYYY-MM-DD." });
  assert.equal(listWords([14, 7, 1]), "14, 7 and 1");
  assert.throws(() => fieldsOf({ ...KEYS_479, "x-cmapi-expiration": { environments: { dev: { enabled: true } } } }), /not its limits/);
});

test("479-P1 nothing about a company is written in the portal's code: every key, domain and example comes from the API", async () => {
  const { readdirSync } = await import("node:fs");
  const contract = JSON.parse(readFileSync(new URL("../../../cmapi/contract/openapi.json", import.meta.url), "utf8"));
  const { schemas } = contract.components;
  assert.ok("mnemonic" in schemas.NamespaceView.properties && "mnemonics" in schemas.NamespaceFacets.properties
    && contract.paths["/api/v1/clusters/{cluster_id}/namespaces"].get.parameters.some((p) => p.name === "mnemonic"), "the contract's member names");
  const CONTRACT_MEMBER = /\.mnemonics?\b|\bmnemonics?(?=\??\s*:)/g;
  const src = new URL("../../src/", import.meta.url);
  const named = [];
  for (const entry of readdirSync(src, { recursive: true })) {
    // The demo build's model and tabs run the mockup's sample logic (MOCKUP-CONTRACT.md, "The demo build"); the generated
    // API types carry the contract's examples. The portal's code is the rest, read without its comments.
    if (!/\.(ts|tsx)$/.test(String(entry)) || /^(model|tabs)\//.test(String(entry)) || String(entry).includes("generated")) continue;
    // Since #481 the contract itself names the value of the namespacePrefix key `mnemonic` (NamespaceView.mnemonic, the
    // list's `mnemonic` parameter, NamespaceFacets.mnemonics): those member names are the API's, so a property access or
    // an object key of that name is not a company's word. Any other use, such as text on the page, still fails here.
    const text = readFileSync(new URL(String(entry), src), "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1")
      .replace(CONTRACT_MEMBER, "");
    for (const word of ["company.net", "ephico2real", "cnn.com", "amgsst", "mnemonic"]) if (text.toLowerCase().includes(word)) named.push(`${entry}: ${word}`);
  }
  assert.deepEqual(named, [], "the demo's model and the generated API types are the only sources that name one");
});

test("479-P6 the preview: each key with where its value comes from, the extra keys, and the date's two keys", async () => {
  const { fieldsOf, shownValues } = await import("../../src/portal/metadataForm.ts");
  const { previewLines, previewYaml, planNamespaceFile, sourceWords } = await import("../../src/portal/preview.ts");
  const form = fieldsOf(KEYS_479);
  const typed = { "label:company.net/mnemonic": "abc", "label:company.net/lob": "amgsst" };
  const lines = previewLines({ form, typed, shown: shownValues(form, typed), target: { namespace: "abc-payments-dev", environment: "dev", cluster: "CRC", instance: "nonprod" },
    extras: { label: [{ id: 1, key: "squad", value: "checkout" }], annotation: [] }, expiresAt: "2026-12-15", protect: null });
  const yaml = previewYaml("abc-payments-dev", lines);
  for (const line of ['name: "abc-payments-dev"   # automatic', 'company.net/app-environment: "dev"   # automatic', 'cmapi.net/team: "abc"   # from Mnemonic',
    'company.net/cl: ""   # required, not set yet', 'squad: "checkout"   # additional', 'cmapi.net/expiry: "managed"   # from Expires', 'cmapi.net/expires-at: "2026-12-15"   # from Expires']) {
    assert.ok(yaml.includes(line), `${line} in\n${yaml}`);
  }
  assert.ok(!yaml.includes("cmapi.net/cost-center"), "an empty optional key is not in the preview");
  assert.equal(planNamespaceFile({ "a/quota.yaml": "q", "a/namespace.yaml": "n" }).text, "n");
  assert.deepEqual(["request", "namespace", "default:company.net/mnemonic"].map(sourceWords), ["from the request", "from the namespace", "default from company.net/mnemonic"]);
});

// PR #506 review (reviewer 1 Codex gpt-6.2-astra, reviewer 2 Opus 5.5): the defects of findings 02, 05, 07, 08 and 09.
const with479 = (edit) => { const keys = structuredClone(KEYS_479); edit(keys); return keys; };
const TARGET = { namespace: "abc-pay-dev", environment: "dev", cluster: "CRC", instance: "nonprod" };

test("506-02 a default copied from a key that cmapi fills in shows that key's value, as cmapi fills it first (core/metadata.py steps 1, 2)", async () => {
  const { bodyOf, fieldsOf, shownValues } = await import("../../src/portal/metadataForm.ts");
  for (const [source, expected] of [["company.net/app-environment", "dev"], ["name", "abc-pay-dev"]]) {
    const form = fieldsOf(with479((k) => { k.labels.properties["cmapi.net/team"]["x-cmapi-default-from"] = source; }));
    assert.equal(shownValues(form, {}, TARGET)["label:cmapi.net/team"], expected, `Team from ${source}`);
    assert.equal(bodyOf(form, {}).labels["cmapi.net/team"], undefined, "unedited: not sent, cmapi fills it in");
    assert.equal(shownValues(form, { "label:cmapi.net/team": "ops" }, TARGET)["label:cmapi.net/team"], "ops", "an edit is kept");
  }
});

test("506-05 the name has at least 2 characters (core/naming.py), and an optional prefix key left empty is no end", async () => {
  const { checkName, endValue, fieldsOf, joinName, nameEnds } = await import("../../src/portal/metadataForm.ts");
  assert.equal(checkName(null, "a", null), "The name has at least 2 characters.");
  assert.equal(checkName(null, "ab", null), null);
  const optional = fieldsOf(with479((k) => { k.labels.required = k.labels.required.filter((key) => key !== "company.net/mnemonic"); }));
  const { start, end } = nameEnds(optional);
  assert.equal(start.required, false);
  assert.equal(endValue(start, {}, TARGET), null, "empty and optional: no start, as cmapi skips the prefix check (_check_prefix)");
  assert.equal(joinName(endValue(start, {}, TARGET), "pay", endValue(end, {}, TARGET)), "pay-dev");
  assert.equal(endValue(start, { "label:company.net/mnemonic": "abc" }, TARGET), "abc");
  const required = nameEnds(fieldsOf(KEYS_479)).start;
  assert.equal(endValue(required, {}, TARGET), "", "a required start not typed yet stays an end ('…')");
});

test("506-07 the preview's YAML keeps each key as text and an empty map as a map", async () => {
  const { previewYaml } = await import("../../src/portal/preview.ts");
  const yaml = previewYaml("yes", { label: [{ key: "on", value: "off", note: "" }, { key: "01", value: "1e3", note: "" }, { key: "app", value: "x", note: "" }], annotation: [] });
  for (const line of ['  name: "yes"', '    "on": "off"', '    "01": "1e3"', '    app: "x"', "  annotations: {}"]) assert.ok(yaml.split("\n").includes(line), `${line} in\n${yaml}`);
  assert.ok(previewYaml("ab", { label: [], annotation: [] }).split("\n").includes("  labels: {}"));
});

test("506-08 no table where cmapi takes no extra key (no allowOther prefix, or max 0); a glob's '*' in the placeholder is 'example'", async () => {
  const { fieldsOf, keyPlaceholder } = await import("../../src/portal/metadataForm.ts");
  const noPrefix = with479((k) => { k.labels.propertyNames.anyOf = k.labels.propertyNames.anyOf.filter((b) => b.enum); k.labels["x-cmapi-other-keys"].prefixes = []; });
  assert.equal(fieldsOf(noPrefix).otherKeys.label, null, "no allowOther prefix");
  assert.notEqual(fieldsOf(noPrefix).otherKeys.annotation, null);
  assert.equal(fieldsOf(with479((k) => { k.annotations["x-cmapi-other-keys"].max = 0; })).otherKeys.annotation, null, "max 0");
  const rules = fieldsOf(KEYS_479).otherKeys.label;
  assert.equal(keyPlaceholder(rules), "e.g. example.company.net/key");
  assert.equal(keyPlaceholder({ ...rules, prefixes: ["*/"] }), "e.g. example/key");
  assert.equal(keyPlaceholder({ ...rules, prefixes: [""] }), "e.g. key");
});

test("506-09 an emptied optional default is sent as \"\", checked by its rule and shown in the preview; left out, cmapi would copy its source", async () => {
  const { bodyOf, checkAll, fieldsOf, shownValues } = await import("../../src/portal/metadataForm.ts");
  const { previewLines } = await import("../../src/portal/preview.ts");
  const keys = with479((k) => { k.labels.properties.alias = { type: "string", "x-cmapi-default-from": "company.net/mnemonic", "x-cmapi-rule": "any value" }; });
  const form = fieldsOf(keys), alias = form.fields.find((f) => f.key === "alias");
  const typed = { "label:company.net/mnemonic": "abc", "label:alias": "" };
  const shown = shownValues(form, typed, TARGET);
  assert.equal(bodyOf(form, typed).labels.alias, "", "sent empty");
  assert.equal("alias" in bodyOf(form, { "label:company.net/mnemonic": "abc" }).labels, false, "unedited: not sent");
  assert.equal((await checkAll(form, shown, "abc-pay-dev", ecma, typed))[alias.id], null, "\"\" passes a key with no rule");
  assert.deepEqual(previewLines({ form, typed, shown, target: TARGET, extras: { label: [], annotation: [] }, expiresAt: null, protect: null }).label.find((l) => l.key === "alias"),
    { key: "alias", value: "", note: "" });
  alias.patterns = ["^[a-z]+$"];
  assert.match((await checkAll(form, shown, "abc-pay-dev", ecma, typed))[alias.id] ?? "", /^Not valid/, "\"\" breaks a pattern, as cmapi refuses it (_governed)");
  const team = form.fields.find((f) => f.key === "cmapi.net/team");
  assert.match((await checkAll(form, shownValues(form, { "label:cmapi.net/team": "" }, TARGET), "abc-pay-dev", ecma, { "label:cmapi.net/team": "" }))[team.id], /^Required/);
});

// #508: the pattern checker of patterns.ts on the real worker code (patternWorker.ts), in a stand-in Worker that holds
// each test until it has "started", as a module worker that is still loading holds the messages posted to it.
const workerScope = { onmessage: null, postMessage: (data) => workerScope.current?.answer(data) };
globalThis.self = workerScope;
await import("../../src/portal/patternWorker.ts");
/** A Worker that starts `startMs` after it is made; `hang` names a pattern whose verdict it never sends (a test that runs on). */
function standInWorker({ startMs = 0, hang = null } = {}) {
  const target = new EventTarget(), queued = [];
  let live = true, ready = false;
  const run = (data) => {
    workerScope.current = { answer: (reply) => {
      if (live && !(hang === data.pattern && "ok" in reply)) setTimeout(() => live && target.dispatchEvent(new MessageEvent("message", { data: reply })));
    } };
    workerScope.onmessage({ data });
  };
  if (startMs !== Infinity) setTimeout(() => { ready = true; queued.splice(0).forEach(run); }, startMs);
  return Object.assign(target, {
    postMessage: (data) => (ready ? setTimeout(() => live && run(data)) : queued.push(data)),
    terminate: () => { live = false; }
  });
}

test("508 a worker's start-up does not count against a pattern's time limit: a plain pattern is checked after a slow start", async () => {
  const { patternChecker } = await import("../../src/portal/patterns.ts");
  let spawned = 0;
  // Start-up past the 200 ms limit, as Chrome took on a loaded machine (CPU throttling 25: spawn 11880 ms, time-out 12118 ms).
  const { test: check, dispose } = patternChecker({ spawn: () => { spawned++; return standInWorker({ startMs: 400 }); } });
  try {
    assert.equal(await check("^[a-z]+$", "bad key"), false, "checked after the start: not 'not checked here'");
    assert.equal(await check("^[a-z]+$", "good"), true, "the pattern is not marked slow");
    assert.equal(spawned, 1, "one worker: none was ended");
  } finally { dispose(); }
});

test("508 the time limit still ends a test that runs on, and a worker that never starts is treated as none", async () => {
  const { patternChecker } = await import("../../src/portal/patterns.ts");
  const slow = "^(?:[a-z0-9]+-?)*[a-z0-9]$";
  let spawned = 0;
  const running = patternChecker({ limitMs: 50, spawn: () => { spawned++; return standInWorker({ hang: slow }); } });
  try {
    assert.equal(await running.test(slow, "aaaa"), null, "out of time: not checked here");
    assert.equal(await running.test(slow, "bbbb"), null, "marked slow for the session");
    assert.equal(await running.test("^[a-z]+$", "abc"), true, "another pattern is still checked, in a new worker");
    assert.equal(spawned, 2);
  } finally { running.dispose(); }
  let made = 0;
  const never = patternChecker({ startLimitMs: 50, spawn: () => { made++; return standInWorker({ startMs: Infinity }); } });
  const late = (ms) => new Promise((resolve) => setTimeout(() => resolve("no answer"), ms));
  assert.equal(await Promise.race([never.test("^[a-z]+$", "abc"), late(1000)]), null, "no start: not checked here, cmapi decides; the form does not wait without end");
  assert.equal(await Promise.race([never.test("^[0-9]+$", "1"), late(1000)]), null);
  assert.equal(made, 1, "and the page has no worker after it: no second wait for a start");
});

// #484, the Namespaces tab: its rows, its merge patch and the 412's per-key choice, written from the design of #481 (sections
// 3, 4.1 and 5) and the answer of GET /api/v1/metadata-keys, not from the tab's code.
const maps = (labels = {}, annotations = {}) => ({ label: labels, annotation: annotations });
test("484-T2 rows: the keys of x-cmapi-edit, locked where it fixes them or cmapi fills them in; an operator-only key only where Git holds it", async () => {
  const { fieldsOf } = await import("../../src/portal/metadataForm.ts");
  const { isEditable, rowsOf } = await import("../../src/portal/namespaceChange.ts");
  const form = fieldsOf(KEYS_479);
  assert.deepEqual(form.edits["label:company.net/mnemonic"], { mode: "fixed", reason: "Part of the namespace's fixed name.", sensitive: false });
  assert.deepEqual(form.edits["label:cmapi.net/protected"].mode, "optional", "operator-only keys have their x-cmapi-edit too");
  const git = maps({ name: "abc-payments-dev", "company.net/mnemonic": "abc", "company.net/cl": "1", "do-not-delete": "true", "team.company.net/squad": "checkout",
    "old.invalid/key": "legacy", "cmapi.net/managed": "true" });
  // The read's x-cmapi-edit of each undeclared or operator-only key of Git (#528, #532).
  const edits = { labels: { "cmapi.net/managed": { mode: "fixed", reason: "Managed by cmapi.", sensitive: false, removable: false },
    "do-not-delete": { ...form.edits["label:do-not-delete"], reason: "Needs namespaces:protect in dev. Changing this key needs one more approval." },
    "old.invalid/key": { mode: "fixed", reason: "Not allowed by this instance's rules.", sensitive: false, removable: true },
    "team.company.net/squad": { mode: "optional", reason: null, sensitive: false, removable: false } }, annotations: {} };
  const rows = rowsOf(form, git, maps(), edits, false);
  const labels = rows.filter((r) => r.kind === "label").map((r) => [r.key, r.access]);
  assert.deepEqual(labels, [["name", "locked"], ["company.net/app-environment", "locked"], ["company.net/mnemonic", "locked"], ["do-not-delete", "locked"],
    ["company.net/lob", "field"], ["company.net/cl", "field"], ["cmapi.net/team", "field"], ["cmapi.net/cost-center", "field"], ["cmapi.net/app", "field"],
    ["cmapi.net/rightsizing", "field"], ["cmapi.net/managed", "locked"], ["old.invalid/key", "remove"], ["team.company.net/squad", "value"]],
    "locked first, then required, optional and the undeclared keys; cmapi.net/protected is not in Git; cmapi's own key is locked");
  assert.equal(isEditable(rows.find((r) => r.key === "old.invalid/key")), false, "a key that no rule admits is removed, never typed in (#492 M2)");
  assert.equal(rows.find((r) => r.key === "do-not-delete").edit.reason,
    "Needs namespaces:protect in dev. Changing this key needs one more approval.", "the namespace read overrides the generic metadata-keys reason");
  // Design section 3, row 4: an operator-only key is a value to type for a caller with namespaces:protect, all of them.
  const operator = rowsOf(form, git, maps(), edits, true).filter((r) => r.kind === "label" && form.operatorOnly.label.includes(r.key)).map((r) => [r.key, r.access]);
  assert.deepEqual(operator, [["cmapi.net/protected", "value"], ["do-not-delete", "value"]]);
  assert.equal(rows.find((r) => r.key === "team.company.net/squad").extra, true);
  assert.equal(rows.find((r) => r.key === "company.net/cl").edit.sensitive, true);
});
test("484-T4 the draft is a merge patch over Git: a value sets, null removes, Git's own value or an emptied new key is no change", async () => {
  const { fieldsOf } = await import("../../src/portal/metadataForm.ts");
  const { changeLines, patchOf, rowsOf, withValue } = await import("../../src/portal/namespaceChange.ts");
  const form = fieldsOf(KEYS_479);
  const rows = rowsOf(form, maps({ "company.net/cl": "1", "cmapi.net/cost-center": "cc-4410" }), maps(), { labels: {}, annotations: {} }, false);
  const row = (key) => rows.find((r) => r.key === key);
  let draft = withValue({}, row("company.net/cl"), "2");
  draft = withValue(draft, row("cmapi.net/cost-center"), null);
  draft = withValue(draft, row("cmapi.net/app"), "");
  assert.deepEqual(draft, { "label:company.net/cl": "2", "label:cmapi.net/cost-center": null }, "an emptied key that Git lacks adds nothing");
  assert.deepEqual(withValue(draft, row("company.net/cl"), "1"), { "label:cmapi.net/cost-center": null }, "back to Git's value: no change");
  const added = { label: [], annotation: [{ id: 1, key: "runbook.company.net/url", value: "https://wiki.company.net/abc/runbook" }, { id: 2, key: "", value: "x" }] };
  assert.deepEqual(patchOf(draft, added), { labels: { "company.net/cl": "2", "cmapi.net/cost-center": null }, annotations: { "runbook.company.net/url": "https://wiki.company.net/abc/runbook" } });
  assert.deepEqual(changeLines(rows, draft, added, form.otherKeys).map((l) => [l.key, l.before, l.after, l.sensitive]),
    [["company.net/cl", "1", "2", true], ["cmapi.net/cost-center", "cc-4410", null, false], ["runbook.company.net/url", null, "https://wiki.company.net/abc/runbook", false]]);
});
test("484-T8 rebase after a 412: a key only I changed is kept; Git now holding my value is no change; a key both changed is asked about", async () => {
  const { rebase } = await import("../../src/portal/namespaceChange.ts");
  const before = maps({ "company.net/cl": "1", "cmapi.net/cost-center": "cc-4410", "company.net/lob": "amgsst" });
  const after = maps({ "company.net/cl": "3", "cmapi.net/cost-center": "cc-5000", "company.net/lob": "amgsst" });
  const draft = { "label:company.net/cl": "2", "label:cmapi.net/cost-center": "cc-5000", "label:company.net/lob": "retail" };
  assert.deepEqual(rebase(draft, before, after), { draft: { "label:company.net/cl": "2", "label:company.net/lob": "retail" }, conflicts: ["label:company.net/cl"] });
  assert.deepEqual(rebase({ "label:cmapi.net/cost-center": null }, before, maps({ "company.net/cl": "1" })), { draft: {}, conflicts: [] }, "removed meanwhile: no change left");
  assert.deepEqual(rebase({ "label:company.net/cl": null }, before, after), { draft: { "label:company.net/cl": null }, conflicts: ["label:company.net/cl"] }, "a removal of a key Git changed is asked about");
});

test("484-T8 a choice not yet made stays asked after another read, until Git has my value", async () => {
  const { rebase } = await import("../../src/portal/namespaceChange.ts");
  const mine = { "label:company.net/cl": "2" };
  const first = rebase(mine, maps({ "company.net/cl": "1" }), maps({ "company.net/cl": "3" }));
  assert.deepEqual(first, { draft: mine, conflicts: ["label:company.net/cl"] });
  // The next read's `before` is the other person's Git: both Gits hold 3, and the question is still open.
  const again = rebase(first.draft, maps({ "company.net/cl": "3" }), maps({ "company.net/cl": "3", "cmapi.net/app": "web" }), first.conflicts);
  assert.deepEqual(again, { draft: mine, conflicts: ["label:company.net/cl"] }, "another read keeps the question");
  const met = rebase(first.draft, maps({ "company.net/cl": "3" }), maps({ "company.net/cl": "2" }), first.conflicts);
  assert.deepEqual(met, { draft: {}, conflicts: [] }, "Git reaching my value answers it");
});

test("484-T3 every reported drift has a row, including a cluster-only extra", async () => {
  const { rowsOf } = await import("../../src/portal/namespaceChange.ts");
  const { fieldsOf } = await import("../../src/portal/metadataForm.ts");
  const live = maps({ "team.company.net/owner": "old", "kubernetes.io/metadata.name": "demo" });
  const drift = [{ kind: "label", key: "team.company.net/owner", git: null, live: "old" }];
  const rows = rowsOf(fieldsOf(KEYS_479), maps(), live, { labels: {}, annotations: {} }, false, drift);
  assert.deepEqual(rows.filter((r) => r.live !== null).map((r) => [r.kind, r.key, r.git, r.live]),
    [["label", "team.company.net/owner", null, "old"]]);
});

async function namespaceApi() {
  const { Readable } = await import("node:stream");
  const { apiHandler, namespacesOfMockup, USERS } = await import("./standin.mjs");
  const { handle, state } = apiHandler({ issuer: { whoHas: (role) => USERS[role] }, portalOrigin: () => "https://portal.test" });
  state.metadataKeys = KEYS_479;
  state.namespaces = namespacesOfMockup();
  const record = state.namespaces[0];
  async function call(method, body, headers = {}, query = "", role = "requester") {
    const req = Object.assign(Readable.from(body ? [JSON.stringify(body)] : []), { method,
      url: `/api/v1/clusters/CRC/namespaces/${record.name}${query}`, headers: { authorization: `Bearer ${role}`, ...headers } });
    const response = {};
    await handle(req, { writeHead(status, headers) { Object.assign(response, { status, headers }); },
      end(text) { response.body = JSON.parse(text); } });
    return response;
  }
  return { record, call };
}

test("484 stand-in refuses operator annotations and forbidden echoes, even beside an effective edit", async () => {
  const { record, call } = await namespaceApi();
  const { headers } = await call("GET");
  const dry = (value, role) => call("PATCH", { labels: { "company.net/lob": "retail" }, annotations: { "do-not-delete": value } },
    { "if-match": headers.etag }, "?dryRun=true", role);
  assert.equal((await dry("x")).status, 403);
  const operator = await dry("x", "operator");
  assert.equal(operator.status, 200);
  assert.ok(!operator.body.approval.slots.some((s) => s.reason === "Sensitive key changed"));
  for (const [map, key] of [["labels", "cmapi.net/managed"], ["labels", "old.invalid/key"]]) {
    if (key === "old.invalid/key") record.git.labels[key] = "old";
    const { headers: latest } = await call("GET");
    const r = await call("PATCH", { labels: { "company.net/lob": "retail", [key]: record.git[map][key] } },
      { "if-match": latest.etag }, "?dryRun=true");
    assert.deepEqual([r.status, r.body.errors?.[0]?.key], [422, key]);
  }
});

test("484 stand-in pins the whole Git folder and returns the router's 409, 412 and replay details", async () => {
  const { record, call } = await namespaceApi();
  const body = { labels: { "company.net/lob": "retail" } };
  const first = await call("GET");
  assert.equal(first.headers.etag, `"${first.body.etag}"`);
  record.otherFiles = { "quota.yaml": "spec: changed" };
  const current = await call("GET");
  assert.notEqual(current.headers.etag, first.headers.etag, "a sibling file changed the folder ETag");
  assert.equal((await call("PATCH", body, {}, "?dryRun=true")).status, 428);
  const stale = await call("PATCH", body, { "if-match": first.headers.etag }, "?dryRun=true");
  assert.deepEqual([stale.status, stale.body.etag], [412, current.body.etag]);
  const h = { "if-match": current.headers.etag, "idempotency-key": "one" };
  const write = await call("PATCH", body, h);
  assert.equal(write.status, 202);
  const conflict = await call("PATCH", body, { ...h, "idempotency-key": "two" });
  assert.deepEqual([conflict.status, conflict.body.code, conflict.body.requestId], [409, "change-pending", write.body.requestId]);
  assert.equal((await call("PATCH", body, h, "?dryRun=true")).status, 200, "dry run takes no lock");
  const replay = await call("PATCH", { ...body, justification: null }, { ...h, "if-match": first.headers.etag });
  assert.deepEqual([replay.status, replay.body.requestId], [202, write.body.requestId]);
  const different = await call("PATCH", { labels: { "company.net/lob": "finance" } }, h);
  assert.deepEqual([different.status, different.body.code, different.body.requestId], [409, "idempotency-replay", write.body.requestId]);
});

test("484-T6 the reference configuration marks a new allowOther zone sensitive", async () => {
  const { REFERENCE_KEYS } = await import("./standin.mjs");
  const { fieldsOf } = await import("../../src/portal/metadataForm.ts");
  const { changeLines } = await import("../../src/portal/namespaceChange.ts");
  const added = { label: [{ id: 1, key: "network.ephico2real.com/zone", value: "local" }], annotation: [] };
  assert.equal(changeLines([], {}, added, fieldsOf(REFERENCE_KEYS).otherKeys)[0].sensitive, true);
});

test("484-T6 an edit kept for an additional key that Git no longer holds is still listed", async () => {
  const { fieldsOf } = await import("../../src/portal/metadataForm.ts");
  const { changeLines, rowsOf } = await import("../../src/portal/namespaceChange.ts");
  const form = fieldsOf(KEYS_479);
  // After a 412 and "Keep my edit": Git dropped team.company.net/squad, so no row holds the drafted value.
  const rows = rowsOf(form, maps(), maps(), { labels: {}, annotations: {} }, false);
  const lines = changeLines(rows, { "label:team.company.net/squad": "mine" }, { label: [], annotation: [] }, form.otherKeys);
  assert.deepEqual(lines.map((l) => [l.kind, l.key, l.before, l.after]), [["label", "team.company.net/squad", null, "mine"]]);
});

test("484-T3 a fresh watch missing the namespace differs from an unavailable watch", async () => {
  const { namespaceViewOf, namespacesOfMockup } = await import("./standin.mjs");
  const rec = namespacesOfMockup()[0];
  rec.live = null;
  const view = () => namespaceViewOf(KEYS_479, rec, true);
  assert.equal(view().sync.state, "drift");
  assert.ok(view().sync.driftedKeys.some((d) => d.kind === "label" && d.key === "company.net/lob" && d.git === "amgsst" && d.live === null));
  rec.liveFresh = false;
  assert.deepEqual(view().sync, { state: "unknown", openRequest: null, driftedKeys: [] });
});

let failed = 0;
for (const [name, run] of tests) {
  try { await run(); console.log(`ok - ${name}`); }
  catch (error) { ++failed; console.error(`FAIL - ${name}: ${error.message}`); }
  finally { globalThis.fetch = originalFetch; }
}
console.log(`${failed ? "FAIL" : "ok"} - direct: ${tests.length - failed} of ${tests.length}`);
process.exit(failed ? 1 : 0);

