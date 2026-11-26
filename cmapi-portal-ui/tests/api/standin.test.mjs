// The stand-in API's Idempotency-Key replays against the API's (#595). cmapi/src/cmapi/plugins/namespaces/router.py: _replay
// returns request_view of the stored row, so a replay answers the request in its current state, never the first answer. A
// replay of a change, a delete or an expiry write still requires If-Match, and `*` is 428 there too (require_if_match,
// core/pipeline.py; #495). A held key with another body is 409 naming its request, and the expiry writes leave the
// justification out of the fingerprint (#597). Each test runs apiHandler directly, with no listener: submit, decide, replay.
import assert from "node:assert/strict";
import { Readable } from "node:stream";
import { test } from "node:test";
import { KEYS_479, USERS, apiHandler, namespaceRecord } from "./standin.mjs";

function standIn() {
  const { handle, state } = apiHandler({ issuer: { whoHas: (token) => USERS[token] ?? null }, portalOrigin: () => "" });
  const call = async (method, path, user, { body, key, ifMatch } = {}) => {
    const req = Readable.from(body === undefined ? [] : [JSON.stringify(body)]);
    Object.assign(req, { method, url: path, headers: { authorization: `Bearer ${user}`,
      ...(key === undefined ? {} : { "idempotency-key": key }), ...(ifMatch === undefined ? {} : { "if-match": ifMatch }) } });
    let status, text = "";
    await handle(req, { writeHead: (s) => { status = s; }, end: (data = "") => { text = data; } });
    return { status, body: text ? JSON.parse(text) : null };
  };
  return { call, state };
}

/** Rejects a pending request as the approver, as the portal's Reject does. */
async function reject({ call }, requestId) {
  const answer = await call("POST", `/api/v1/requests/${requestId}:reject`, "approver", { body: { comment: "withdrawn" } });
  assert.equal(answer.status, 200);
  assert.equal(answer.body.status, "rejected");
  return answer.body;
}

/** The replay of a stored write: its current state, and 428 without If-Match or with `*` (SP and HTAB around it too). */
async function replays(send, decided, tag) {
  const again = await send(tag);
  assert.equal(again.status, 202);
  assert.deepEqual(again.body, decided, "the whole request in its current state, not the first answer");
  for (const value of [undefined, "*", " \t*\t "]) {
    const answer = await send(value);
    assert.equal(answer.status, 428, `If-Match ${JSON.stringify(value)} on a replay`);
    assert.equal(answer.body.code, "precondition-required");
  }
}

test("an expiry replay after a rejection answers the rejected request, and needs If-Match", async () => {
  const api = standIn();
  api.state.expirations = [{ clusterId: "CRC", name: "notes-dev", env: "dev", expiresAt: "2027-01-01", openRequest: null }];
  api.state.etags.set("CRC/notes-dev", "abc");
  const send = (ifMatch) => api.call("POST", "/api/v1/clusters/CRC/namespaces/notes-dev/expiration:makePermanent", "requester",
    { body: { justification: "in production" }, key: "k-expiry", ifMatch });
  const first = await send('"abc"');
  assert.equal(first.status, 202);
  assert.equal(first.body.status, "pending_approval");
  await replays(send, await reject(api, first.body.requestId), '"abc"');
});

test("a namespace change replayed after a rejection answers the rejected request, and needs If-Match", async () => {
  const api = standIn();
  const record = namespaceRecord({ name: "abc-ledger-dev", prefix: "abc", team: "ledger", extraLabels: { "cmapi.net/protected": "true" } });
  api.state.namespaces = [record];
  const etag = (await api.call("GET", "/api/v1/clusters/CRC/namespaces/abc-ledger-dev", "operator")).body.etag;
  const send = (ifMatch) => api.call("PATCH", "/api/v1/clusters/CRC/namespaces/abc-ledger-dev", "operator",
    { body: { labels: { "cmapi.net/protected": null } }, key: "k-change", ifMatch });
  const first = await send(`"${etag}"`);
  assert.equal(first.status, 202);
  assert.equal(first.body.status, "pending_approval");
  await replays(send, await reject(api, first.body.requestId), `"${etag}"`);
});

test("a quota change replayed after a rejection answers the rejected request, and needs If-Match", async () => {
  const api = standIn();
  const etag = (await api.call("GET", "/api/v1/clusters/CRC/namespaces/payments-dev", "requester")).body.etag;
  const send = (ifMatch) => api.call("PATCH", "/api/v1/clusters/CRC/namespaces/payments-dev", "requester",
    { body: { tier: "large" }, key: "k-quota", ifMatch });
  const first = await send(`"${etag}"`);
  assert.equal(first.status, 202);
  assert.equal(first.body.status, "pending_approval");
  const decided = await reject(api, first.body.requestId);
  // Git moves on: the retry still carries its first ETag, and the API replays it without comparing the tag again (#495).
  api.state.etags.set("CRC/payments-dev", "0123456789abcdef");
  await replays(send, decided, `"${etag}"`);
  const fresh = await api.call("PATCH", "/api/v1/clusters/CRC/namespaces/payments-dev", "requester",
    { body: { tier: "medium" }, key: "k-quota-2", ifMatch: `"${etag}"` });
  assert.equal(fresh.status, 412, "a new write with the old ETag is still compared");
});

test("a create replay answers the request as it is now; a create takes no If-Match", async () => {
  const api = standIn();
  const body = { namespace: "orders-dev", tier: "small", labels: { "cmapi.net/team": "orders" },
    annotations: { "cmapi.net/team-dl": "orders-team@ephico2real.com" } };
  const send = () => api.call("POST", "/api/v1/clusters/CRC/namespaces", "requester", { body, key: "k-create" });
  const first = await send();
  assert.equal(first.status, 202, JSON.stringify(first.body));
  // The API moves an approved request on (the bot opens its pull request); the stand-in has no bot, so the test moves it.
  // ChangeRequest.pr is a PrView (cmapi/src/cmapi/core/models.py), not a number.
  const moved = { ...first.body, status: "pr_open",
    pr: { number: 42, url: "https://git.test/pulls/42", branch: "cmapi/CRC/orders-dev", head: "abcdef12" } };
  api.state.items = api.state.items.map((r) => (r.requestId === moved.requestId ? moved : r));
  const again = await send();
  assert.equal(again.status, 202);
  assert.deepEqual(again.body, moved);
});

test("an expiry replay with another justification is the same request, as the API's fingerprint leaves it out", async () => {
  const api = standIn();
  api.state.expirations = [{ clusterId: "CRC", name: "notes-dev", env: "dev", expiresAt: "2027-01-01", openRequest: null }];
  api.state.etags.set("CRC/notes-dev", "abc");
  const send = (justification) => api.call("POST", "/api/v1/clusters/CRC/namespaces/notes-dev/expiration:extend", "requester",
    { body: { days: 7, justification }, key: "k-why", ifMatch: '"abc"' });
  const first = await send("one more sprint");
  assert.equal(first.status, 202);
  const again = await send("a different reason");
  assert.equal(again.status, 202);
  assert.equal(again.body.requestId, first.body.requestId);
  const other = await api.call("POST", "/api/v1/clusters/CRC/namespaces/notes-dev/expiration:extend", "requester",
    { body: { days: 8 }, key: "k-why", ifMatch: '"abc"' });
  assert.equal(other.status, 409);
  assert.equal(other.body.code, "idempotency-replay");
  assert.equal(other.body.requestId, first.body.requestId, "the 409 names the request that holds the key, as _replay's does");
});

test("a first write takes `*` as 428 and an empty If-Match as 412, on each write that needs one", async () => {
  // check_if_match (core/pipeline.py): require_if_match refuses `*` first; an empty value then lists no strong tag, so 412.
  const writes = {
    quota: async () => ["PATCH", "/api/v1/clusters/CRC/namespaces/payments-dev", "requester", { tier: "large" }],
    metadata: async (api) => {
      api.state.namespaces = [namespaceRecord({ name: "abc-ledger-dev", prefix: "abc", team: "ledger", extraLabels: { "cmapi.net/protected": "true" } })];
      return ["PATCH", "/api/v1/clusters/CRC/namespaces/abc-ledger-dev", "operator", { labels: { "cmapi.net/protected": null } }];
    },
    expiry: async (api) => {
      api.state.expirations = [{ clusterId: "CRC", name: "notes-dev", env: "dev", expiresAt: "2027-01-01", openRequest: null }];
      api.state.etags.set("CRC/notes-dev", "abc");
      return ["POST", "/api/v1/clusters/CRC/namespaces/notes-dev/expiration:extend", "requester", { days: 7 }];
    }
  };
  for (const [name, setUp] of Object.entries(writes)) {
    for (const [ifMatch, status, code] of [["*", 428, "precondition-required"], [" \t*\t ", 428, "precondition-required"], ["", 412, "precondition-failed"]]) {
      const api = standIn();
      const [method, path, user, body] = await setUp(api);
      const answer = await api.call(method, path, user, { body, key: `fresh-${name}`, ifMatch });
      assert.deepEqual([answer.status, answer.body.code], [status, code], `${name}, If-Match ${JSON.stringify(ifMatch)}`);
      assert.equal(api.state.keys.size, 0, "a refused first write holds no key");
    }
  }
});

test("an adopted namespace can add exact missing name keys through PATCH", async () => {
  const api = standIn();
  api.state.metadataKeys = KEYS_479;
  const record = namespaceRecord({ name: "abc-ledger-dev", prefix: "abc", team: "ledger" });
  const mnemonic = "company.net/mnemonic";
  const env = "company.net/app-environment";
  for (const key of ["name", mnemonic, env]) delete record.git.labels[key];
  api.state.namespaces = [record];
  const path = "/api/v1/clusters/CRC/namespaces/" + record.name;
  const ifMatch = '"' + (await api.call("GET", path, "operator")).body.etag + '"';
  const patch = (labels) => api.call("PATCH", path + "?dryRun=true", "operator", { body: { labels }, ifMatch });
  for (const [key, value] of [["name", "ABC-ledger-dev"], [mnemonic, "ab"], [mnemonic, "ledger"], [env, "rnd"], [env, null]]) {
    const res = await patch({ [key]: value });
    assert.equal(res.status, 422);
    assert.deepEqual(res.body.errors.map((e) => e.key), [key]);
  }
  const labels = { name: record.name, [mnemonic]: "abc", [env]: "dev" };
  const res = await patch(labels);
  assert.equal(res.status, 200, JSON.stringify(res.body));
  for (const [key, value] of Object.entries(labels)) {
    assert.deepEqual(res.body.metadataDiff.labels[key], { before: null, after: value, source: "request" });
  }
});
