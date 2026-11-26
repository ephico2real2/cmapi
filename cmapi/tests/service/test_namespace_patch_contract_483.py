"""#483, the contract of a change to an existing namespace's metadata, through the API
(docs/reviews/2026-11-20-epic-481-metadata-patch/design.md, sections 3 to 5).

The configuration is the #479 design's company.net file (test_namespace_contract_479.DESIGN): the name is
<mnemonic>-<desired name>-<cluster env>, name and app-environment are filled in, and cmapi.net/team and company.net/cl
are sensitive. The instance serves dev; CRC is dev. Each test names one behaviour, on the service suite's world with
PostgreSQL."""
from __future__ import annotations

import copy

import yaml

from cmapi.core.db.repo import RequestRepo
from cmapi.core.pipeline import folder_etag
from test_flow import AMY, OLA, OPAL, auth, run_jobs
from test_namespace_contract_479 import MINIMAL, URL, design_config, design_world  # noqa: F401  (fixtures)

NS = "abc-payments-dev"
NS_FILE = f"clusters/CRC/namespaces/{NS}/namespace.yaml"


def headers(keys, user: str = "ola", who: dict = OLA, etag: str | None = None) -> dict[str, str]:
    h = auth(keys, user, **who)
    if etag is not None:
        h["If-Match"] = f'"{etag}"'
    return h


def relist(ctx) -> None:
    """The fake cluster's watch does not stream: read the cache's list again, as test_flow does."""
    ctx.registry.cache("CRC")._list("Namespace")


def create(world, name: str = NS, labels: dict | None = None, annotations: dict | None = None) -> dict:
    """A namespace from a create to synced, then its read."""
    client, ctx, git, kube, validator, keys = world
    body = {**MINIMAL, "namespace": name, "labels": {**MINIMAL["labels"], **(labels or {})},
            "annotations": {**MINIMAL["annotations"], **(annotations or {})}}
    if not name.startswith("abc-"):
        body["labels"]["company.net/mnemonic"] = name.split("-")[0]
    r = client.post(URL, json=body, headers=headers(keys))
    assert r.status_code == 202, r.text
    run_jobs(ctx)
    relist(ctx)
    return read(world, name)


def read(world, name: str = NS) -> dict:
    client, ctx, git, kube, validator, keys = world
    r = client.get(f"{URL}/{name}", headers=headers(keys))
    assert r.status_code == 200, r.text
    return r.json()


def patch(world, body: dict, *, dry: bool = True, etag: str | None = None, user: str = "ola", who: dict = OLA,
          name: str = NS):
    """A PATCH with the etag of the current read, unless one is given."""
    client, ctx, git, kube, validator, keys = world
    etag = etag if etag is not None else read(world, name)["etag"]
    return client.patch(f"{URL}/{name}" + ("?dryRun=true" if dry else ""), json={"justification": "A test", **body},
                        headers=headers(keys, user, who, etag))


def errors_of(r) -> list[tuple[str, str]]:
    assert r.status_code == 422 and r.json()["code"] == "policy-violation", r.text
    return [(e["code"], e.get("key")) for e in r.json()["errors"]]


def planned_namespace(r) -> dict:
    assert r.status_code == 200, r.text
    return yaml.safe_load(r.json()["files"][NS_FILE])["metadata"]


def put_live(kube, name: str, labels: dict) -> None:
    """A managed namespace on the fake cluster only (the list reads the watch cache, never Git)."""
    kube.objects[("Namespace", "", name)] = {"kind": "Namespace", "metadata": {
        "name": name, "labels": {"cmapi.net/managed": "true", **labels}, "annotations": {}}}


# --------------------------------------------------------------------------- 4.4: the lookup in one cluster

def lookup(world, query: str = ""):
    client, ctx, git, kube, validator, keys = world
    return client.get(URL + (f"?{query}" if query else ""), headers=headers(keys))


def three(world) -> None:
    client, ctx, git, kube, validator, keys = world
    put_live(kube, "abc-payments-dev", {"company.net/mnemonic": "abc", "cmapi.net/team": "abc"})
    put_live(kube, "abc-orders-dev", {"company.net/mnemonic": "abc", "cmapi.net/team": "payroll"})
    put_live(kube, "pay-orders-dev", {"company.net/mnemonic": "pay", "cmapi.net/team": "pay"})
    relist(ctx)


def names(r) -> list[str]:
    assert r.status_code == 200, r.text
    return [i["name"] for i in r.json()["items"]]


def test_the_list_without_parameters_is_every_managed_namespace_by_name(design_world):
    three(design_world)
    r = lookup(design_world)
    assert names(r) == ["abc-orders-dev", "abc-payments-dev", "pay-orders-dev"]
    assert r.json()["total"] == 3 and r.json()["facets"] == {"mnemonics": {"abc": 2, "pay": 1}}


def test_q_puts_names_that_start_with_it_first_then_names_then_teams_that_contain_it(design_world):
    three(design_world)
    assert names(lookup(design_world, "q=pay")) == ["pay-orders-dev", "abc-payments-dev", "abc-orders-dev"]
    assert names(lookup(design_world, "q=ORDERS")) == ["abc-orders-dev", "pay-orders-dev"]


def test_mnemonic_filters_and_the_mnemonic_counts_keep_every_chip(design_world):
    three(design_world)
    r = lookup(design_world, "mnemonic=abc")
    assert names(r) == ["abc-orders-dev", "abc-payments-dev"] and r.json()["total"] == 2
    assert r.json()["facets"]["mnemonics"] == {"abc": 2, "pay": 1}
    r = lookup(design_world, "q=orders&mnemonic=pay")
    assert names(r) == ["pay-orders-dev"] and r.json()["facets"]["mnemonics"] == {"abc": 1, "pay": 1}


def test_limit_is_10_when_searching_at_most_50_and_total_counts_every_match(design_world):
    client, ctx, git, kube, validator, keys = design_world
    for i in range(12):
        put_live(kube, f"abc-app{i:02d}-dev", {"company.net/mnemonic": "abc"})
    relist(ctx)
    assert len(names(lookup(design_world))) == 12                          # no parameter: every namespace, as before
    r = lookup(design_world, "q=abc")
    assert len(names(r)) == 10 and r.json()["total"] == 12
    assert len(names(lookup(design_world, "q=abc&limit=3"))) == 3
    for bad in ("limit=51", "limit=0"):
        assert lookup(design_world, bad).json()["code"] == "validation-failed", bad


def test_each_item_has_its_mnemonic_team_and_sync_pending_when_a_request_holds_it(design_world):
    client, ctx, git, kube, validator, keys = design_world
    three(design_world)
    held = client.post(URL, json={**MINIMAL, "tier": "large"}, headers=headers(keys))
    assert held.status_code == 202 and held.json()["status"] == "pending_approval", held.text
    items = {i["name"]: i for i in lookup(design_world, "q=abc").json()["items"]}
    assert items["abc-payments-dev"]["mnemonic"] == "abc" and items["abc-orders-dev"]["team"] == "payroll"
    assert items["abc-payments-dev"]["sync"] == {
        "state": "pending", "openRequest": {"requestId": held.json()["requestId"], "status": "pending_approval"},
        "driftedKeys": []}
    assert items["abc-orders-dev"]["sync"]["state"] == "unknown"           # the list reads no Git


# --------------------------------------------------------------------------- 4.2: the detail read

def test_the_detail_read_gives_the_git_metadata_from_the_same_read_as_its_etag(design_world):
    client, ctx, git, kube, validator, keys = design_world
    view = create(design_world)
    in_git = yaml.safe_load(git.branches["main"][NS_FILE])["metadata"]
    # #528 adds `edits` beside the two maps; the maps are still the folder's.
    assert {k: view["git"][k] for k in ("labels", "annotations")} == {"labels": in_git["labels"], "annotations": in_git["annotations"]}
    files = {p: t for p, t in git.branches["main"].items() if p.startswith(f"clusters/CRC/namespaces/{NS}/")}
    assert view["etag"] == folder_etag(files) and view["mnemonic"] == "abc"


def test_a_synced_namespace_is_in_sync(design_world):
    assert create(design_world)["sync"] == {"state": "in-sync", "openRequest": None, "driftedKeys": []}


def test_a_namespace_that_a_request_holds_is_pending_with_the_request(design_world):
    create(design_world)
    r = patch(design_world, {"labels": {"company.net/cl": "2"}}, dry=False)
    assert r.status_code == 202 and r.json()["status"] == "pending_approval", r.text
    assert read(design_world)["sync"] == {
        "state": "pending", "openRequest": {"requestId": r.json()["requestId"], "status": "pending_approval"},
        "driftedKeys": []}


def test_a_merge_that_the_cluster_does_not_have_yet_is_pending_not_drift(design_world):
    client, ctx, git, kube, validator, keys = design_world
    create(design_world)
    r = patch(design_world, {"labels": {"company.net/lob": "retail"}}, dry=False)
    assert r.status_code == 202, r.text
    with ctx.db.session() as s:                       # Git main has the change; Argo CD has not applied it yet
        RequestRepo(s).get(r.json()["requestId"]).status = "merged"
    git.branches["main"][NS_FILE] = _with_label(git.branches["main"][NS_FILE], "company.net/lob", "retail")
    sync = read(design_world)["sync"]
    assert sync["state"] == "pending" and sync["openRequest"]["status"] == "merged"
    assert sync["driftedKeys"] == [{"kind": "label", "key": "company.net/lob", "git": "retail", "live": "amgsst"}]


def _with_label(text: str, key: str, value: str) -> str:
    doc = yaml.safe_load(text)
    doc["metadata"]["labels"][key] = value
    return yaml.safe_dump(doc, sort_keys=False)


def test_a_hand_label_on_the_cluster_is_drift_with_both_values(design_world):
    client, ctx, git, kube, validator, keys = design_world
    create(design_world)
    live = copy.deepcopy(kube.objects[("Namespace", "", NS)])
    live["metadata"]["labels"]["company.net/lob"] = "amgsst-old"
    live["metadata"]["labels"]["kubernetes.io/metadata.name"] = NS              # reserved: never compared
    kube.objects[("Namespace", "", NS)] = live
    relist(ctx)
    assert read(design_world)["sync"] == {"state": "drift", "openRequest": None, "driftedKeys": [
        {"kind": "label", "key": "company.net/lob", "git": "amgsst", "live": "amgsst-old"}]}


def test_a_watch_that_is_not_fresh_is_unknown(design_world):
    client, ctx, git, kube, validator, keys = design_world
    create(design_world)
    cache = ctx.registry.cache("CRC")
    cache.state["Namespace"].last_good = cache.clock() - cache.RELIST_SECONDS - 5
    assert read(design_world)["sync"] == {"state": "unknown", "openRequest": None, "driftedKeys": []}


# --------------------------------------------------------------------------- 4.1: the change, merge-patch semantics

def test_a_change_keeps_omitted_keys_sets_values_and_removes_null_in_both_maps(design_world):
    create(design_world, labels={"cmapi.net/cost-center": "cc-4410"},
           annotations={"runbook.company.net/url": "https://wiki.company.net/abc/old"})
    r = patch(design_world, {"labels": {"company.net/lob": "retail", "cmapi.net/cost-center": None},
                             "annotations": {"runbook.company.net/url": None,
                                             "company.net/mnemonic-confluence": "https://wiki.company.net/abc"}})
    meta = planned_namespace(r)
    assert meta["labels"]["company.net/lob"] == "retail" and meta["labels"]["company.net/cl"] == "1"
    assert "cmapi.net/cost-center" not in meta["labels"] and "runbook.company.net/url" not in meta["annotations"]
    assert meta["annotations"]["cmapi.net/team-dl"] == "payments-team@company.net"
    assert r.json()["metadataDiff"] == {
        "labels": {"cmapi.net/cost-center": {"before": "cc-4410", "after": None, "source": "request"},
                   "company.net/lob": {"before": "amgsst", "after": "retail", "source": "request"}},
        "annotations": {"company.net/mnemonic-confluence": {"before": None, "after": "https://wiki.company.net/abc",
                                                            "source": "request"},
                        "runbook.company.net/url": {"before": "https://wiki.company.net/abc/old", "after": None,
                                                    "source": "request"}}}


def test_the_metadata_diff_leaves_out_a_value_sent_back_and_cmapis_own_keys(design_world):
    create(design_world)
    r = patch(design_world, {"tier": "medium", "labels": {"company.net/lob": "amgsst", "company.net/cl": "0"}})
    assert r.status_code == 200, r.text
    assert r.json()["metadataDiff"] == {"labels": {"company.net/cl": {"before": "1", "after": "0", "source": "request"}},
                                        "annotations": {}}


def test_a_fixed_key_is_refused_and_each_fixed_or_automatic_key_sent_back_is_accepted(design_world):
    create(design_world)
    assert errors_of(patch(design_world, {"labels": {"company.net/mnemonic": "abcd"}})) == \
        [("invalid_value", "company.net/mnemonic")]
    echo = {"name": NS, "company.net/app-environment": "dev", "company.net/mnemonic": "abc", "company.net/lob": "retail"}
    r = patch(design_world, {"labels": echo, "annotations": {"company.net/app-environment": "dev"}})
    assert r.status_code == 200, r.text
    assert list(r.json()["metadataDiff"]["labels"]) == ["company.net/lob"]


def test_an_automatic_key_with_another_value_is_refused(design_world):
    create(design_world)
    assert errors_of(patch(design_world, {"labels": {"name": "other"}})) == [("derived_key", "name")]


def test_an_operator_only_key_needs_namespaces_protect(design_world):
    create(design_world)
    r = patch(design_world, {"labels": {"cmapi.net/protected": "true"}})
    assert r.status_code == 403 and r.json()["code"] == "forbidden", r.text
    r = patch(design_world, {"labels": {"cmapi.net/protected": "true"}}, user="opal", who=OPAL)
    assert r.status_code == 200 and planned_namespace(r)["labels"]["cmapi.net/protected"] == "true", r.text


def test_a_required_key_changes_and_is_never_removed(design_world):
    create(design_world)
    assert errors_of(patch(design_world, {"labels": {"company.net/lob": None}})) == \
        [("missing_required_key", "company.net/lob")]
    assert planned_namespace(patch(design_world, {"labels": {"company.net/lob": "retail"}}))["labels"]["company.net/lob"] \
        == "retail"


def test_an_extra_key_that_allow_other_admits_is_added_and_removed_within_its_limits(design_world):
    create(design_world, labels={"team.company.net/squad": "checkout"})
    r = patch(design_world, {"labels": {"team.company.net/squad": None, "team.company.net/tribe": "money"}})
    assert r.json()["metadataDiff"]["labels"] == {
        "team.company.net/squad": {"before": "checkout", "after": None, "source": "request"},
        "team.company.net/tribe": {"before": None, "after": "money", "source": "request"}}
    many = {f"x{i}.company.net/k": "v" for i in range(51)}
    assert ("too_many_keys", None) in errors_of(patch(design_world, {"labels": many}))
    assert ("annotations_too_large", None) in errors_of(patch(design_world, {"annotations": {"runbook.company.net/u": "x" * 5000}}))


def test_a_change_of_sensitive_keys_adds_one_approval_per_request(design_world):
    create(design_world)

    def sensitive_slots(r) -> int:
        assert r.status_code == 200, r.text
        return sum(1 for s in r.json()["approval"]["slots"] if s["reason"] == "Sensitive key changed")

    assert sensitive_slots(patch(design_world, {"labels": {"company.net/lob": "retail"}})) == 0
    assert sensitive_slots(patch(design_world, {"labels": {"company.net/cl": "2"}})) == 1
    assert sensitive_slots(patch(design_world, {"labels": {"company.net/cl": "2", "cmapi.net/team": "payments"}})) == 1


def test_a_required_key_that_the_namespace_lacks_is_a_finding_and_the_change_can_add_it(design_world):
    client, ctx, git, kube, validator, keys = design_world
    create(design_world)
    doc = yaml.safe_load(git.branches["main"][NS_FILE])           # an adopted namespace: no line of business (#234)
    del doc["metadata"]["labels"]["company.net/lob"]
    git.branches["main"][NS_FILE] = yaml.safe_dump(doc, sort_keys=False)
    r = patch(design_world, {"labels": {"company.net/cl": "0"}})
    assert r.status_code == 200, r.text
    found = [f for f in r.json()["findings"] if f["rule"] == "missing_required_key"]
    assert found == [{"source": "cmapi", "rule": "missing_required_key", "path": NS_FILE, "severity": "warning",
                      "message": "the label company.net/lob is required and the namespace lacks it: a request can add it",
                      "kyvernoRule": None}]
    r = patch(design_world, {"labels": {"company.net/lob": "amgsst"}})
    assert [f for f in r.json()["findings"] if f["rule"] == "missing_required_key"] == []
    assert r.json()["metadataDiff"]["labels"] == {"company.net/lob": {"before": None, "after": "amgsst", "source": "request"}}


def test_a_reserved_or_adoption_key_that_git_holds_is_kept_by_a_change(design_world):
    client, ctx, git, kube, validator, keys = design_world
    create(design_world)
    doc = yaml.safe_load(git.branches["main"][NS_FILE])
    doc["metadata"]["labels"]["company.net/provisioner"] = "cluster-configs"
    doc["metadata"]["annotations"]["openshift.io/requester"] = "ola"
    git.branches["main"][NS_FILE] = yaml.safe_dump(doc, sort_keys=False)
    meta = planned_namespace(patch(design_world, {"labels": {"company.net/cl": "0"}}))
    assert meta["labels"]["company.net/provisioner"] == "cluster-configs"
    assert meta["annotations"]["openshift.io/requester"] == "ola"
    assert errors_of(patch(design_world, {"labels": {"company.net/provisioner": None}})) == \
        [("reserved_key", "company.net/provisioner")]


# --------------------------------------------------------------------------- 5: two people, one namespace

def test_a_second_submit_while_a_request_holds_the_namespace_is_409_with_the_holder(design_world):
    create(design_world)
    first = patch(design_world, {"labels": {"company.net/cl": "2"}}, dry=False)
    assert first.status_code == 202, first.text
    second = patch(design_world, {"labels": {"company.net/lob": "retail"}}, dry=False)
    assert second.status_code == 409 and second.json()["code"] == "change-pending", second.text
    assert second.json()["requestId"] == first.json()["requestId"]


def test_a_stale_etag_is_412_with_the_current_etag(design_world):
    create(design_world)
    current = read(design_world)["etag"]
    r = patch(design_world, {"labels": {"company.net/lob": "retail"}}, etag="0123456789abcdef")
    assert r.status_code == 412 and r.json()["code"] == "precondition-failed", r.text
    assert r.json()["etag"] == current


def test_a_change_without_if_match_is_428(design_world):
    client, ctx, git, kube, validator, keys = design_world
    create(design_world)
    r = client.patch(f"{URL}/{NS}?dryRun=true", json={"labels": {"company.net/lob": "retail"}}, headers=headers(keys))
    assert r.status_code == 428 and r.json()["code"] == "precondition-required", r.text


def test_a_refused_change_has_one_policy_violation_entry_per_key(design_world):
    create(design_world)
    r = patch(design_world, {"labels": {"cmapi.net/tier": "large", "other.org/x": "1", "company.net/cl": "9",
                                        "name": "other", "company.net/lob": None}})
    assert sorted(errors_of(r)) == [("derived_key", "name"), ("invalid_key", "other.org/x"),
                                    ("invalid_value", "company.net/cl"), ("missing_required_key", "company.net/lob"),
                                    ("reserved_key", "cmapi.net/tier")]


def test_an_approver_cannot_change_a_namespace_without_namespaces_write(design_world):
    create(design_world)
    r = patch(design_world, {"labels": {"company.net/lob": "retail"}}, user="amy", who=AMY)
    assert r.status_code == 403, r.text


# --------------------------------------------------------------------------- 4.3: x-cmapi-edit

def test_metadata_keys_gives_each_key_how_it_may_change(design_world):
    client, ctx, git, kube, validator, keys = design_world
    body = client.get("/api/v1/metadata-keys", headers=headers(keys)).json()
    labels = body["labels"]["properties"]
    assert labels["company.net/mnemonic"]["x-cmapi-edit"] == \
        {"mode": "fixed", "reason": "Part of the namespace's fixed name.", "sensitive": False}
    assert labels["name"]["x-cmapi-edit"] == {"mode": "automatic", "reason": "Copied from the namespace name.",
                                              "sensitive": False}
    assert labels["company.net/cl"]["x-cmapi-edit"]["sensitive"] is True
    assert body["annotations"]["properties"]["cmapi.net/team-dl"]["x-cmapi-edit"]["mode"] == "required"
