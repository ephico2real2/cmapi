"""#330 follow-up: a key that Git already holds from before the fix ("/foo", accepted and merged on main 9ba33b2) can be
removed by a merge patch, though no request may set it now.

The pipeline (core/pipeline.py, plan_namespace) keeps each current key that classifies as governed or team, and "/foo"
classifies as team under the reference config's "" entry, so every later change re-renders it and the API server refuses
it at apply. Removing it (`{"/foo": null}`) writes nothing, so its syntax must not block the removal.
"""
from __future__ import annotations

import pytest
import yaml

from cmapi.core.metadata import MetadataKeys
from conftest import EX

REFERENCE = EX / "cluster-configs/policies/metadata-keys.yaml"
CUR_A = {"cmapi.net/team-dl": "payments-team@ephico2real.com"}


@pytest.fixture(scope="module")
def keys() -> MetadataKeys:
    return MetadataKeys(yaml.safe_load(REFERENCE.read_text()))


@pytest.mark.parametrize("kind", ["label", "annotation"])
def test_a_held_key_with_an_empty_prefix_can_be_removed(keys, kind):
    cur_l = {"cmapi.net/team": "payments", **({"/foo": "x"} if kind == "label" else {})}
    cur_a = {**CUR_A, **({"/foo": "x"} if kind == "annotation" else {})}
    # The premise: the pipeline keeps "/foo" from Git, because it classifies as team.
    assert keys.classify("/foo", kind) == "team"
    labels = {"/foo": None} if kind == "label" else {}
    annotations = {"/foo": None} if kind == "annotation" else {}
    assert keys.validate(labels, annotations, operator=False, current_labels=cur_l, current_annotations=cur_a,
                         existing=True) == []
    assert "/foo" not in keys.merge_patch(cur_l if kind == "label" else cur_a, labels or annotations)


@pytest.mark.parametrize("value", ["x", ""])
def test_a_held_key_with_an_empty_prefix_still_cannot_be_set(keys, value):
    cur_l = {"cmapi.net/team": "payments", "/foo": "x"}
    assert keys.validate({"/foo": value}, {}, operator=False, current_labels=cur_l, current_annotations=CUR_A,
                         existing=True) == [{"code": "invalid_key", "key": "/foo"}]


def test_removing_an_invalid_key_that_git_does_not_hold_is_still_refused(keys):
    assert keys.validate({"/foo": None}, {}, operator=False, current_labels={"cmapi.net/team": "payments"},
                         current_annotations=CUR_A, existing=True) == [{"code": "invalid_key", "key": "/foo"}]
