"""Mutation sensitivity of the named moved-head regression test."""
import importlib
import inspect

import pytest

from cmapi.jobs import HANDLERS
from test_github_check_runs import (
    on_github,
    test_green_ci_does_not_excuse_a_head_that_moved as moved_head_check,
)


def test_named_moved_head_check_detects_removal_of_the_approved_head_guard(on_github, monkeypatch):
    module = importlib.import_module('cmapi.jobs.pr_checks')
    source = inspect.getsource(module.pr_checks)
    assert source.count('and head == pr.head_sha') == 1
    namespace = dict(vars(module))
    exec(compile(source.replace('and head == pr.head_sha', 'and True'), '<head-guard-mutant>', 'exec'), namespace)
    monkeypatch.setitem(HANDLERS, 'pr_checks', namespace['pr_checks'])
    # Also runs against the original test, which had only its one changed-file scenario.
    kwargs = {'same_tree': True} if 'same_tree' in inspect.signature(moved_head_check).parameters else {}
    with pytest.raises(AssertionError):
        moved_head_check(on_github, **kwargs)
