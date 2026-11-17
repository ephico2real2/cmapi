"""OB3 finding on PR #378: removing a protection label needs approver-platform even when an annotation of the same key
holds the same value. change_facts compared {**labels, **annotations}, so the annotation hid the label's removal."""
from __future__ import annotations

import shutil

import pytest
import yaml

from conftest import build_world
from test_flow import NS, OPAL, auth, run_jobs

URL = "/api/v1/clusters/CRC/namespaces"
ONE = f"{URL}/payments-dev"


@pytest.fixture
def world(test_config, fresh_db, keys, monkeypatch, tmp_path):
    d = tmp_path / "config"
    shutil.copytree(test_config, d)
    inst = yaml.safe_load((d / "instance.yaml").read_text())
    inst["instance"]["policy"] = {"engine": "none"}
    (d / "instance.yaml").write_text(yaml.safe_dump(inst))
    with build_world(d, keys, monkeypatch) as w:
        yield w


@pytest.mark.parametrize("key", ["do-not-delete", "cmapi.net/protected"])
def test_removing_a_protection_label_needs_approver_platform_when_an_annotation_shares_its_key(world, key):
    client, ctx, git, *_, keys = world
    body = {**NS, "labels": {**NS["labels"], key: "true"}, "annotations": {**NS["annotations"], key: "true"}}
    r = client.post(URL, json=body, headers=auth(keys, "opal", **OPAL))
    assert r.status_code == 202 and r.json()["status"] == "approved", r.text
    run_jobs(ctx)
    etag = client.get(ONE, headers=auth(keys, "opal", **OPAL)).json()["etag"]
    r = client.patch(ONE, json={"labels": {key: None}}, headers={**auth(keys, "opal", **OPAL), "If-Match": etag})
    print("UNPROTECT", key, r.status_code, r.json().get("status"), r.json().get("approval", {}).get("reasons"))
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "pending_approval", r.json()["approval"]
    assert "threshold sensitiveKeyChanged: +1 approver-platform" in r.json()["approval"]["reasons"], r.json()["approval"]


def test_a_requesters_sensitive_team_label_change_is_not_hidden_by_an_annotation_of_the_same_key(world):
    """The same merge let a requester change a sensitiveKeys label with no approval: a team key is allowed as a label and as
    an annotation, so an annotation of the same key hid the label's change."""
    from test_flow import OLA
    client, ctx, git, *_, keys = world
    zone = "network.ephico2real.com/zone"
    body = {**NS, "labels": {**NS["labels"], zone: "a"}, "annotations": {**NS["annotations"], zone: "a"}}
    r = client.post(URL, json=body, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 202 and r.json()["status"] == "approved", r.text
    run_jobs(ctx)
    etag = client.get(ONE, headers=auth(keys, "ola", **OLA)).json()["etag"]
    r = client.patch(ONE, json={"labels": {zone: "b"}}, headers={**auth(keys, "ola", **OLA), "If-Match": etag})
    print("ZONE", r.status_code, r.json().get("status"), r.json().get("approval", {}).get("reasons"))
    assert r.status_code == 202 and r.json()["status"] == "pending_approval", r.json()
    assert "threshold sensitiveKeyChanged: +1 approver-platform" in r.json()["approval"]["reasons"], r.json()["approval"]
