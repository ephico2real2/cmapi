"""#739: self-service adoption, and the missing metadata supplied with it or added later.

The owner's decision of 2026-11-26 on #26: "adopting a namespace is very easy and promote self services ... ask for additional
required metadata via the same form or screen so that adoption can be triggered via the api as well with the required
fields." So:

- a requester with namespaces:write in the cluster's environment lists the candidates, plans and submits an adoption, and
  the approval rules gate it exactly as before (D10);
- `:adopt` takes `labels` and `annotations` for keys the live namespace lacks, checked as a change of an existing namespace
  checks a key it adds (#732); a key the namespace has is 422 `adoption-key-held` (D3, "as-is");
- each key supplied is written to `namespace.yaml` and drops its `missing-required-key` finding; none supplied is the
  behaviour before #739;
- the candidates list, the plan and the namespace read name the keys that may be added (`missingKeys`), with the one value
  of a key that cmapi fills in or that starts the name.

The test instance has the reference metadata-keys.yaml (cmapi.net/team and cmapi.net/team-dl required, no derived key); the
company's file, with the derived `name` and the `company.net/mnemonic` prefix, is in `company_world`.
"""
from __future__ import annotations

import shutil

import pytest
import yaml
from sqlalchemy import text

from conftest import EXAMPLES, build_world
from test_add_missing_key_732 import company_world  # noqa: F401  (the fixture: the company's metadata-keys.yaml)
from test_adoption_26 import BASE, LABELS, NS, approve_all, owner_sample, request
from test_flow import OLA, OPAL, auth, run_jobs

ADOPT = f"/api/v1/clusters/CRC/namespaces/{NS}:adopt"
VIEWER = dict(roles=["cmapi-viewer"], groups=[])
ONBOARDING = dict(roles=["cmapi-onboarding"], groups=[])
BOT_RND = dict(roles=["cmapi-bot-rnd"], groups=[])      # inherits cmapi-requester, in rnd only; CRC is dev
TEAM = {"cmapi.net/team": "abc"}
TEAM_DL = {"cmapi.net/team-dl": "abc-team@ephico2real.com"}


def adopt(client, keys, *, labels=None, annotations=None, dry_run=False, who="ola", role=OLA):
    body = {"justification": "Bring abc-rnd under cmapi"}
    if labels is not None:
        body["labels"] = labels
    if annotations is not None:
        body["annotations"] = annotations
    return client.post(ADOPT + ("?dryRun=true" if dry_run else ""), json=body, headers=auth(keys, who, **role))


def missing(plan, rule="missing-required-key"):
    return sorted(f["message"].split(":", 1)[0] for f in plan["findings"] if f["rule"] == rule)


def namespace_yaml(plan):
    return yaml.safe_load(plan["files"][BASE + "namespace.yaml"])["metadata"]


def requests_total(client, keys):
    return client.get("/api/v1/requests", headers=auth(keys, "opal", **OPAL)).json()["page"]["total"]


# --------------------------------------------------------------------------- self-service


def test_a_requester_lists_the_candidates_plans_and_submits_an_adoption(world):
    client, ctx, git, kube, validator, keys = world
    owner_sample(kube)
    listed = client.get("/api/v1/clusters/CRC/adoption/candidates", headers=auth(keys, "ola", **OLA))
    assert listed.status_code == 200, listed.text
    assert [i["name"] for i in listed.json()["items"]] == [NS]
    assert client.get("/api/v1/clusters/CRC/adoption/skipped", headers=auth(keys, "ola", **OLA)).status_code == 200
    planned = adopt(client, keys, dry_run=True)
    assert planned.status_code == 200, planned.text
    submitted = adopt(client, keys)
    assert submitted.status_code == 202, submitted.text
    req = submitted.json()
    assert req["requester"]["requester"]["username"] == "ola" and req["status"] == "pending_approval"
    # D10 unchanged: the same approvers as an operator's adoption of the same namespace, never automatic
    assert req["approval"]["auto"] is None
    assert req["approval"]["slots"] == [{"group": "approver-platform", "count": 3, "reason": req["approval"]["slots"][0]["reason"]}]
    assert planned.json()["approval"]["slots"] == req["approval"]["slots"]


def test_the_approval_of_a_requesters_adoption_is_the_operators(world):
    client, ctx, git, kube, validator, keys = world
    owner_sample(kube)
    mine = adopt(client, keys, dry_run=True).json()["approval"]
    theirs = adopt(client, keys, dry_run=True, who="opal", role=OPAL).json()["approval"]
    assert mine == theirs


def test_an_imported_cluster_with_no_environment_lists_no_candidates(world):
    """docs/14: the adoption lists are scoped to the cluster's environment. A cluster imported with no clusters.yaml entry has
    none, and RoleGrant.covers(None) would admit a grant limited to any environment, so nobody lists it (:adopt is 422)."""
    client, ctx, git, kube, validator, keys = world
    owner_sample(kube)
    ctx.registry.get("CRC").policy = None
    for who, role in (("ola", BOT_RND), ("ola", OLA), ("opal", OPAL)):
        for path in ("candidates", "skipped"):
            r = client.get(f"/api/v1/clusters/CRC/adoption/{path}", headers=auth(keys, who, **role))
            assert r.status_code == 403 and r.json()["code"] == "environment-forbidden", (role, path, r.text)


def test_without_namespaces_write_in_the_environment_nobody_adopts(world):
    client, ctx, git, kube, validator, keys = world
    owner_sample(kube)
    for role, code in ((VIEWER, "forbidden"), (ONBOARDING, "forbidden"), (BOT_RND, "environment-forbidden")):
        h = auth(keys, "ola", **role)
        for r in (client.get("/api/v1/clusters/CRC/adoption/candidates", headers=h),
                  client.get("/api/v1/clusters/CRC/adoption/skipped", headers=h),
                  adopt(client, keys, dry_run=True, role=role), adopt(client, keys, role=role)):
            assert r.status_code == 403 and r.json()["code"] == code, (role, r.text)
    assert requests_total(client, keys) == 0


# --------------------------------------------------------------------------- metadata at adoption


def test_the_candidates_name_the_keys_an_adoption_may_add(world):
    client, ctx, git, kube, validator, keys = world
    owner_sample(kube)
    item = client.get("/api/v1/clusters/CRC/adoption/candidates", headers=auth(keys, "ola", **OLA)).json()["items"][0]
    missing_keys = item["missingKeys"]
    assert {"kind": "label", "key": "cmapi.net/team", "required": True, "value": None} in missing_keys
    assert {"kind": "annotation", "key": "cmapi.net/team-dl", "required": True, "value": None} in missing_keys
    assert [m["required"] for m in missing_keys] == sorted((m["required"] for m in missing_keys), reverse=True)
    assert {m["key"] for m in missing_keys if not m["required"]} == {"cmapi.net/cost-center", "cmapi.net/app",
                                                                    "cmapi.net/rightsizing"}


def test_supplied_keys_are_written_and_their_findings_go(world):
    client, ctx, git, kube, validator, keys = world
    owner_sample(kube)
    before = adopt(client, keys, dry_run=True).json()
    assert missing(before) == ["annotation cmapi.net/team-dl", "label cmapi.net/team"]
    r = adopt(client, keys, labels=TEAM, annotations=TEAM_DL, dry_run=True)
    assert r.status_code == 200, r.text
    plan = r.json()
    assert missing(plan) == []
    meta = namespace_yaml(plan)
    assert meta["labels"]["cmapi.net/team"] == "abc" and meta["annotations"]["cmapi.net/team-dl"] == TEAM_DL["cmapi.net/team-dl"]
    # every key the namespace held stays as it is; only the supplied ones are new
    for key in ("name", "company.net/provisioner", "company.net/cl", "cmapi.net/adopt"):
        assert meta["labels"][key] == LABELS[key], key
    assert plan["metadataDiff"] == {"labels": {"cmapi.net/team": {"before": None, "after": "abc", "source": "request"}},
                                    "annotations": {"cmapi.net/team-dl": {"before": None, "after": TEAM_DL["cmapi.net/team-dl"],
                                                                          "source": "request"}}}
    assert plan["adoption"]["supplied"] == {"labels": TEAM, "annotations": TEAM_DL}
    assert {m["key"] for m in plan["adoption"]["missingKeys"]} == {"cmapi.net/cost-center", "cmapi.net/app",
                                                                    "cmapi.net/rightsizing"}
    # the base of the policies stays the live namespace as it was read (D6a): a supplied key is new, so it is checked
    assert "cmapi.net/team" not in validator.previous[-1][BASE + "namespace.yaml"]
    assert len(plan["findings"]) == len(before["findings"]) - 2


def test_an_adoption_with_supplied_keys_reaches_git_and_the_cluster(world):
    client, ctx, git, kube, validator, keys = world
    owner_sample(kube)
    r = adopt(client, keys, labels=TEAM, annotations=TEAM_DL)
    assert r.status_code == 202, r.text
    rid = r.json()["requestId"]
    with ctx.db.session() as s:
        stored = s.execute(text("select plan from change_requests where request_id = :r"), {"r": rid}).scalar()
    assert stored["adoption"]["supplied"] == {"labels": TEAM, "annotations": TEAM_DL}
    assert "cmapi.net/team: abc" in stored["files"][BASE + "namespace.yaml"]
    assert request(client, keys, rid)["status"] == "pending_approval"
    approve_all(client, keys, rid)
    run_jobs(ctx, limit=40)
    assert request(client, keys, rid)["status"] == "synced"
    assert "cmapi.net/team: abc" in git.branches["main"][BASE + "namespace.yaml"]
    live = kube.objects[("Namespace", "", NS)]["metadata"]
    assert live["labels"]["cmapi.net/team"] == "abc" and live["annotations"]["cmapi.net/team-dl"] == TEAM_DL["cmapi.net/team-dl"]
    assert live["labels"]["name"] == "aao-rnd"                        # a held key is never changed by the adoption


def test_no_supplied_key_is_the_adoption_before_739(world):
    """Empty maps and no maps plan the same files, findings and approval, and the plan says it adds nothing."""
    client, ctx, git, kube, validator, keys = world
    owner_sample(kube)
    none = adopt(client, keys, dry_run=True).json()
    empty = adopt(client, keys, labels={}, annotations={}, dry_run=True).json()
    for key in ("files", "findings", "approval", "planHash", "changes"):
        assert none[key] == empty[key], key
    assert none["metadataDiff"] is None and none["adoption"]["supplied"] == {"labels": {}, "annotations": {}}


def test_a_key_the_namespace_has_is_refused_and_nothing_is_recorded(world):
    """D3: the adoption keeps each key it finds as it is. A held key, an empty one and one under a skip prefix alike."""
    client, ctx, git, kube, validator, keys = world
    owner_sample(kube)
    for labels, annotations, held in (
            ({"company.net/lob": "other"}, None, [{"kind": "label", "key": "company.net/lob"}]),
            ({"company.net/mnemonic-group-contact": "x"}, None, [{"kind": "label", "key": "company.net/mnemonic-group-contact"}]),
            ({"pod-security.kubernetes.io/audit": "baseline", **TEAM}, None,
             [{"kind": "label", "key": "pod-security.kubernetes.io/audit"}]),
            (None, {"company.net/app-environment": "dev"}, [{"kind": "annotation", "key": "company.net/app-environment"}])):
        for dry in (True, False):
            r = adopt(client, keys, labels=labels, annotations=annotations, dry_run=dry)
            assert r.status_code == 422, r.text
            assert r.json()["code"] == "adoption-key-held" and r.json()["keys"] == held, r.text
    assert requests_total(client, keys) == 0


def test_a_supplied_value_is_checked_by_its_rule(world):
    client, ctx, git, kube, validator, keys = world
    owner_sample(kube)
    r = adopt(client, keys, labels={"cmapi.net/team": "Not A Team"}, annotations={"cmapi.net/team-dl": "x@other.com"},
              dry_run=True)
    assert r.status_code == 422 and r.json()["code"] == "policy-violation", r.text
    assert {(e["code"], e["key"]) for e in r.json()["errors"]} == {("invalid_value", "cmapi.net/team"),
                                                                     ("invalid-team-dl", "cmapi.net/team-dl")}
    # an empty value is no way round a required key: its pattern refuses it, as on a change
    empty = adopt(client, keys, labels={"cmapi.net/team": ""}, dry_run=True)
    assert empty.status_code == 422 and [(e["code"], e["key"]) for e in empty.json()["errors"]] == \
        [("invalid_value", "cmapi.net/team")], empty.text
    for label in ({"cmapi.net/managed": "true"}, {"kubernetes.io/foo": "x"}):
        refused = adopt(client, keys, labels=label, dry_run=True)
        assert refused.status_code == 422 and refused.json()["errors"][0]["code"] == "reserved_key", refused.text
    protect = adopt(client, keys, labels={"cmapi.net/protected": "true"}, dry_run=True)
    assert protect.status_code == 403 and protect.json()["code"] == "forbidden", protect.text
    assert requests_total(client, keys) == 0


def test_a_null_value_is_not_an_adoption(world):
    """An adoption adds keys and removes none: a merge patch's null is refused by the body's schema."""
    client, ctx, git, kube, validator, keys = world
    owner_sample(kube)
    r = adopt(client, keys, labels={"cmapi.net/team": None}, dry_run=True)
    assert r.status_code == 422 and r.json()["code"] == "validation-failed", r.text


def test_an_idempotent_replay_keeps_the_supplied_keys(world):
    client, ctx, git, kube, validator, keys = world
    owner_sample(kube)
    h = auth(keys, "ola", **OLA)
    body = {"justification": "Bring abc-rnd under cmapi", "labels": TEAM}
    first = client.post(ADOPT, json=body, headers=h)
    assert first.status_code == 202, first.text
    again = client.post(ADOPT, json=body, headers=h)
    assert again.json()["requestId"] == first.json()["requestId"], again.text
    other = client.post(ADOPT, json={**body, "labels": {"cmapi.net/team": "xyz"}}, headers=h)
    assert other.status_code == 409 and other.json()["code"] == "idempotency-replay", other.text


# --------------------------------------------------------------------------- derived and prefix keys (company keys)


def company_sample(world, *missing_keys):
    client, ctx, git, kube, validator, keys = world
    owner_sample(kube, labels={k: v for k, v in LABELS.items() if k not in missing_keys})
    return client, keys


def test_the_candidates_give_the_one_value_of_a_missing_derived_or_prefix_key(company_world):
    client, keys = company_sample(company_world, "name", "company.net/mnemonic", "company.net/lob")
    item = client.get("/api/v1/clusters/CRC/adoption/candidates", headers=auth(keys, "ola", **OLA)).json()["items"][0]
    got = {m["key"]: m for m in item["missingKeys"]}
    assert got["name"] == {"kind": "label", "key": "name", "required": True, "value": NS}
    assert got["company.net/mnemonic"] == {"kind": "label", "key": "company.net/mnemonic", "required": True, "value": "abc"}
    assert got["company.net/lob"] == {"kind": "label", "key": "company.net/lob", "required": True, "value": None}
    # held keys are not offered, even when their value breaks a rule (the empty contact labels are reported, kept)
    assert "company.net/cl" not in got and "company.net/app-environment" not in got


def test_a_derived_or_prefix_key_is_added_only_with_its_one_value(company_world):
    client, keys = company_sample(company_world, "name", "company.net/mnemonic")
    wrong = adopt(client, keys, labels={"name": "aao-rnd", "company.net/mnemonic": "abd"}, dry_run=True)
    assert wrong.status_code == 422, wrong.text
    assert {(e["code"], e["key"]) for e in wrong.json()["errors"]} == {("derived_key", "name"),
                                                                       ("invalid_value", "company.net/mnemonic")}
    right = adopt(client, keys, labels={"name": NS, "company.net/mnemonic": "abc"}, dry_run=True)
    assert right.status_code == 200, right.text
    plan = right.json()
    assert missing(plan) == []
    meta = namespace_yaml(plan)
    assert meta["labels"]["name"] == NS and meta["labels"]["company.net/mnemonic"] == "abc"
    assert plan["adoption"]["missingKeys"] == [] or all(not m["required"] for m in plan["adoption"]["missingKeys"])


def test_a_key_the_adoption_left_missing_is_named_on_the_namespace_and_added_later(company_world):
    """The follow-up: the namespace read names each key a change may add, and a PATCH adds it with that value."""
    client, ctx, git, kube, validator, keys = company_world
    owner_sample(kube, labels={k: v for k, v in LABELS.items() if k not in ("name", "company.net/lob")})
    rid = adopt(client, keys).json()["requestId"]
    approve_all(client, keys, rid)
    run_jobs(ctx, limit=40)
    assert request(client, keys, rid)["status"] == "synced"
    h = auth(keys, "ola", **OLA)
    view = client.get(f"/api/v1/clusters/CRC/namespaces/{NS}", headers=h).json()
    got = {m["key"]: m for m in view["git"]["missingKeys"]}
    assert got["name"]["value"] == NS and got["company.net/lob"]["value"] is None
    r = client.patch(f"/api/v1/clusters/CRC/namespaces/{NS}?dryRun=true", headers={**h, "If-Match": f'"{view["etag"]}"'},
                     json={"labels": {"name": NS, "company.net/lob": "amgsst"}, "justification": "The metadata the adoption lacked"})
    assert r.status_code == 200, r.text
    assert not [f for f in r.json()["findings"] if f["rule"] == "missing_required_key"], r.json()["findings"]


@pytest.fixture
def suffix_world(test_config, fresh_db, keys, monkeypatch, tmp_path):
    """The company's keys with CRC's rule for the environment label: filled in by cmapi and the end of the name."""
    d = tmp_path / "config"
    shutil.copytree(test_config, d)
    doc = yaml.safe_load((EXAMPLES / "cluster-configs/policies/metadata-keys.company.yaml").read_text())
    doc["requiredLabels"]["company.net/app-environment"]["namespaceSuffix"] = True
    (d / "metadata-keys.yaml").write_text(yaml.safe_dump(doc))
    with build_world(d, keys, monkeypatch) as world:
        yield world


def test_a_key_that_ends_the_name_is_never_offered(suffix_world):
    """D20: "A key that the name ends with is never offered", also one that cmapi fills in. abc-rnd on the dev cluster would
    otherwise be offered company.net/app-environment: dev, a value its name does not end with."""
    client, keys = company_sample(suffix_world, "name", "company.net/app-environment")
    item = client.get("/api/v1/clusters/CRC/adoption/candidates", headers=auth(keys, "ola", **OLA)).json()["items"][0]
    assert [m["key"] for m in item["missingKeys"] if m["kind"] == "label"] == ["name"], item["missingKeys"]
    plan = adopt(client, keys, dry_run=True).json()
    assert "company.net/app-environment" not in {m["key"] for m in plan["adoption"]["missingKeys"] if m["kind"] == "label"}
    assert "label company.net/app-environment" in missing(plan), "it stays a finding (decision 2)"
