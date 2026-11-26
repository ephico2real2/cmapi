"""#732: a required key that an adopted namespace lacks can be added by a request, with exactly the value it would have had at
create: the derived value of a value.from key, or the start of the namespace name for the namespacePrefix key.

The owner's decision 2 on #26 (2026-11-14): "A required key missing at adoption is never forced, only reported. Later updates
go through without it; it stays a finding until someone chooses to add it." Before this fix #481's change rule refused the
addition (invalid_value, "a change cannot add it; adoption does"), and adoption never adds a key, so the finding had no way out.
The instance here has the company's metadata-keys.company.yaml; the namespace is the owner's sample, adopted without its
mnemonic and its derived `name` label.
"""
from __future__ import annotations

import shutil

import pytest
import yaml

from conftest import EXAMPLES, build_world
from test_adoption_26 import ANN, LABELS, NS, adopt, owner_sample, request
from test_flow import AMY, OPAL, auth, run_jobs

BASE = f"/api/v1/clusters/CRC/namespaces/{NS}"


@pytest.fixture
def company_world(test_config, fresh_db, keys, monkeypatch, tmp_path):
    d = tmp_path / "config"
    shutil.copytree(test_config, d)
    shutil.copy(EXAMPLES / "cluster-configs/policies/metadata-keys.company.yaml", d / "metadata-keys.yaml")
    with build_world(d, keys, monkeypatch) as world:
        yield world


def adopted_without(world, *missing):
    """The owner's sample without the keys named, adopted through the API to synced."""
    client, ctx, git, kube, validator, keys = world
    owner_sample(kube, labels={k: v for k, v in LABELS.items() if k not in missing})
    rid = adopt(client, keys).json()["requestId"]
    # As many approvers of approver-platform as this instance's rules ask of the plan (its findings set the count).
    for user, role in (("amy", AMY), ("ann", ANN), ("alan", ANN), ("abe", ANN)):
        if request(client, keys, rid)["status"] != "pending_approval":
            break
        r = client.post(f"/api/v1/requests/{rid}:approve", json={"comment": "ok"}, headers=auth(keys, user, **role))
        assert r.status_code == 200, r.text
    run_jobs(ctx, limit=40)
    assert request(client, keys, rid)["status"] == "synced"


def change(world, labels, *, dry_run):
    client, ctx, git, kube, validator, keys = world
    h = auth(keys, "opal", **OPAL)
    etag = client.get(BASE, headers=h).json()["etag"]
    return client.patch(BASE + ("?dryRun=true" if dry_run else ""), headers={**h, "If-Match": f'"{etag}"'},
                        json={"labels": labels, "justification": "Add the mnemonic the adoption reported missing"})


def missing(plan):
    return [f["message"] for f in plan["findings"] if f["rule"] == "missing_required_key"]


def test_a_request_adds_the_missing_mnemonic_with_the_start_of_the_name_and_the_finding_goes(company_world):
    adopted_without(company_world, "company.net/mnemonic")
    # The finding of any change says how: a request adds it with the start of the name.
    before = change(company_world, {"company.net/cl": "2"}, dry_run=True)
    assert before.status_code == 200, before.text
    planned = change(company_world, {"company.net/mnemonic": "abc"}, dry_run=True)
    assert planned.status_code == 200, planned.text
    assert missing(planned.json()) == []
    ns = yaml.safe_load(planned.json()["files"][f"clusters/CRC/namespaces/{NS}/namespace.yaml"])
    assert ns["metadata"]["labels"]["company.net/mnemonic"] == "abc"
    assert ns["metadata"]["labels"]["company.net/provisioner"] == "cluster-configs"      # the adopted keys stay
    submitted = change(company_world, {"company.net/mnemonic": "abc"}, dry_run=False)
    assert submitted.status_code == 202, submitted.text
    assert missing(before.json()) == ["the label company.net/mnemonic is required and the namespace lacks it: a request can "
                                      "add it with the start of the namespace name"]


def test_a_value_that_is_not_the_start_of_the_name_is_still_refused(company_world):
    adopted_without(company_world, "company.net/mnemonic")
    for wrong in ("abd", "rnd"):
        r = change(company_world, {"company.net/mnemonic": wrong}, dry_run=True)
        assert r.status_code == 422, r.text
        assert [(e["code"], e["key"]) for e in r.json()["errors"]] == [("invalid_value", "company.net/mnemonic")], wrong


def test_a_request_adds_the_missing_derived_name_with_its_derived_value_only(company_world):
    adopted_without(company_world, "name")
    wrong = change(company_world, {"name": "aao-rnd"}, dry_run=True)
    assert wrong.status_code == 422 and wrong.json()["errors"][0]["code"] == "derived_key", wrong.text
    assert "a request can add it with the value cmapi derives from the namespace (abc-rnd)" in wrong.json()["errors"][0]["detail"]
    right = change(company_world, {"name": NS}, dry_run=True)
    assert right.status_code == 200, right.text
    assert not any("label name" in m for m in missing(right.json()))
    ns = yaml.safe_load(right.json()["files"][f"clusters/CRC/namespaces/{NS}/namespace.yaml"])
    assert ns["metadata"]["labels"]["name"] == NS             # the renderer writes it: Git lacked it, so none is kept
    assert right.json()["metadataDiff"]["labels"]["name"] == {"before": None, "after": NS, "source": "request"}
