"""#648: a ValueError that escapes a route is the service's fault, not the caller's.

Before, main.py's value_error_handler answered every ValueError as 422 validation-failed with up to 300 characters of the
exception's text, so a codec error of the Git layer blamed the caller and showed an implementation message. RFC 9457, section
3.1.4: the detail "ought to focus on helping the client correct the problem, rather than giving debugging information"; RFC 9110,
section 15.6.1: 500 is for "an unexpected condition that prevented it from fulfilling the request". Now such a ValueError
answers 500 internal-error with no text of it, and the log line `unhandled` names its class and its route. The refusals that
meant "the request is not valid" are explicit Problems, and answer the same 422 as before, byte for byte.
"""
from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

import cmapi.core.listquery as listquery
from cmapi.core.docs import PROBLEMS
from cmapi.core.errors import type_base
from cmapi.core.pipeline import Plan
from test_custom_tier_change import SIZES, URL, catalog_with, custom, patch, synced
from test_flow import NS, OLA, auth

ONE = f"{URL}/{NS['namespace']}"
SECRET = "an implementation detail that must not reach the caller"


def problem(ctx, status: int, code: str, detail: str) -> dict:
    """The whole body of a problem, as problem_response writes it."""
    base = type_base(ctx.cfg.raw_instance["instance"])
    return {"type": base + code, "title": code.replace("-", " "), "status": status, "detail": detail, "code": code}


def unhandled(capsys) -> list[dict]:
    """The `unhandled` log lines of the request, parsed."""
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if '"event": "unhandled"' in line]


def assert_internal_error(ctx, capsys, r, route: str, error_type: str, *hidden: str) -> None:
    assert r.status_code == 500, r.text
    assert r.headers["content-type"] == "application/problem+json"
    assert r.json() == problem(ctx, 500, "internal-error", PROBLEMS["internal-error"][1]), r.text
    for text in hidden:
        assert text not in r.text, f"{text!r} is in the answer: {r.text}"
    logged = unhandled(capsys)
    assert len(logged) == 1, logged
    assert logged[0]["route"] == route and logged[0]["error_type"] == error_type, logged[0]
    assert logged[0]["request_id"] == r.headers["x-request-id"], logged[0]
    assert all(text in logged[0]["exception"] for text in hidden), logged[0]       # the cause stays in the log


# ---- a ValueError that is the service's fault: 500 internal-error, its text in the log only

def test_a_codec_error_of_the_git_layer_is_internal_error(world, capsys):
    """The case that found #648: a folder name that is not UTF-8 made the Git read raise UnicodeDecodeError, a ValueError."""
    client, ctx, git, kube, validator, keys = world

    def read_folder(path, ref=None):
        raise UnicodeDecodeError("utf-8", b"caf\xe9.yaml", 3, 4, "invalid continuation byte")

    git.read_folder = read_folder
    r = client.patch(ONE, json={"tier": "medium"}, headers={**auth(keys, "ola", **OLA), "If-Match": '"0"'})
    assert_internal_error(ctx, capsys, r, "/api/v1/clusters/{cluster_id}/namespaces/{ns}", "UnicodeDecodeError",
                          "codec", "0xe9", "invalid continuation byte")


def test_a_value_error_of_a_dependency_is_internal_error(world, capsys):
    from cmapi.routers import ctx as context

    client, ctx, git, kube, validator, keys = world

    def fail():
        raise ValueError(SECRET)

    client.app.dependency_overrides[context] = fail
    try:
        r = client.get("/api/v1/requests/req-20261124-0001", headers=auth(keys, "ola", **OLA))
    finally:
        del client.app.dependency_overrides[context]
    assert_internal_error(ctx, capsys, r, "/api/v1/requests/{request_id}", "ValueError", SECRET)


def test_a_response_that_fails_its_own_model_is_internal_error(world, capsys, monkeypatch):
    """pydantic's ValidationError is a ValueError: a plan view that PlanView refuses is cmapi's bug, never the caller's 422."""
    client, ctx, git, kube, validator, keys = world
    monkeypatch.setattr(Plan, "view", lambda self: {"planHash": SECRET})
    r = client.post(URL + "?dryRun=true", json=NS, headers=auth(keys, "ola", **OLA))
    assert_internal_error(ctx, capsys, r, "/api/v1/clusters/{cluster_id}/namespaces", "ValidationError", "PlanView")


# ---- the deliberate refusals: the same 422 validation-failed as before #648, byte for byte

def test_a_username_that_cannot_be_a_label_value_is_still_validation_failed(world):
    client, ctx, git, kube, validator, keys = world
    r = client.post(URL, json=NS, headers=auth(keys, "John Doe@corp", **OLA))
    assert r.status_code == 422, r.text
    assert r.json() == problem(ctx, 422, "validation-failed", "username 'John Doe@corp' cannot be a label value"), r.text


@pytest.mark.parametrize("body", [
    custom(quota={**SIZES, "requests.cpu": "lots"}),
    custom(limitRange={"container": {"max": {"cpu": "lots"}}}),
], ids=["quota", "limit"])
def test_a_requested_value_that_is_not_a_quantity_is_still_validation_failed(world, body):
    client, ctx, git, kube, validator, keys = world
    r = client.post(URL + "?dryRun=true", json=body, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 422, r.text
    assert r.json() == problem(ctx, 422, "validation-failed", "not a Kubernetes quantity: 'lots'"), r.text


def test_a_change_of_a_value_that_git_holds_to_one_that_is_not_a_quantity_is_still_validation_failed(world):
    """The value is compared with Git's before the bounds are checked: that comparison parses the caller's value too."""
    client, ctx, git, kube, validator, keys = world
    etag = synced(world, custom(), approvals=1)
    r = patch(world, etag, {"quota": {"requests.cpu": "lots"}})
    assert r.status_code == 422, r.text
    assert r.json() == problem(ctx, 422, "validation-failed", "not a Kubernetes quantity: 'lots'"), r.text


@pytest.mark.parametrize("body,value", [
    (custom(quota={**SIZES, "requests.cpu": "1e1000000"}), "1e1000000"),
    (custom(quota={**SIZES, "requests.cpu": "1e9999999"}), "1e9999999"),
    (custom(quota={**SIZES, "requests.cpu": "1e999999999999999999"}), "1e999999999999999999"),
    (custom(quota={**SIZES, "requests.cpu": "1e9000000000000000"}), "1e9000000000000000"),
    (custom(limitRange={"container": {"max": {"cpu": "1e9999999"}}}), "1e9999999"),
], ids=["quota-at-the-bound", "quota-past-emax", "quota-past-max-prec", "quota-memory-error", "limit-past-emax"])
def test_a_requested_quantity_too_large_to_hold_is_validation_failed(world, body, value):
    """apimachinery reads the exponent as an int64 (suffix.go, interpret), so "1e9999999" is a quantity for Kubernetes, but
    qty cannot hold it. Before: quantize raised decimal.InvalidOperation (500), a precision past MAX_PREC raised decimal's
    "valid range for prec is [1, MAX_PREC]" (422 with that text), and "1e9000000000000000" raised MemoryError (500). Each
    is the caller's value: 422 with a text that says what to correct."""
    client, ctx, git, kube, validator, keys = world
    r = client.post(URL + "?dryRun=true", json=body, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 422, r.text
    detail = f"quantity out of range (cmapi takes one below 1e1000000): {value!r}"
    assert r.json() == problem(ctx, 422, "validation-failed", detail), r.text


def test_a_requested_value_of_more_digits_than_decimal_keeps_is_checked_against_the_step(world):
    """The step check ran `v % st` in Decimal's 28-digit context: DivisionImpossible, 500, for a value of more digits on a
    key with a step and no max. pods is sizable, and the catalog needs a max for an overridable key only."""
    client, ctx, git, kube, validator, keys = world

    def no_pods_max(raw):
        raw["custom"]["max"].pop("pods")
        for env in raw["environments"].values():
            ((env or {}).get("custom") or {}).get("max", {}).pop("pods", None)

    catalog_with(world, no_pods_max)
    many = "1" + "0" * 39 + "1"                       # 41 digits, not a multiple of the step 10
    r = client.post(URL + "?dryRun=true", json=custom(quota={**SIZES, "pods": many}), headers=auth(keys, "ola", **OLA))
    assert r.status_code == 422, r.text
    error = r.json()["errors"][0]
    assert error["code"] == "custom-out-of-bounds", r.text
    assert error["items"] == [{"key": "pods", "value": many, "min": "10", "max": None, "step": "10"}], r.text
    r = client.post(URL + "?dryRun=true", json=custom(quota={**SIZES, "pods": many[:-1] + "0"}), headers=auth(keys, "ola", **OLA))
    assert r.status_code == 200, r.text                # a whole number of steps passes


def test_a_value_error_after_the_csv_stream_started_is_logged_by_its_class_and_leaks_nothing(world, capsys, monkeypatch):
    """The 200 has gone, so the stream ends early and no problem replaces it. The log names the ValueError, not the
    ExceptionGroup of the response's task group."""
    client, ctx, git, kube, validator, keys = world

    def lines(rows, columns):
        yield "name\n"
        raise ValueError(SECRET)

    monkeypatch.setattr(listquery, "_csv_lines", lines)
    r = TestClient(client.app, raise_server_exceptions=False).get("/api/v1/quotas:export", headers=auth(keys, "ola", **OLA))
    assert r.status_code == 200 and SECRET not in r.text, (r.status_code, r.text)
    logged = unhandled(capsys)
    assert [(e["route"], e["error_type"]) for e in logged] == [("/api/v1/quotas:export", "ValueError")], logged
    assert SECRET in logged[0]["exception"]
