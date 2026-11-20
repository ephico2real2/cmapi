"""#479, Phase 1: the API contract of a namespace (docs/reviews/2026-11-20-issue-479/namespace_metadata.md, section 4).

The configuration is the design's section 3.1 (company.net): the name is <mnemonic>-<desired name>-<cluster env>, the
filled-in keys (value.from) are required and shown, cmapi.net/team defaults to the mnemonic, and allowOther.example puts
one extra label and one extra annotation in the create example. The instance serves rnd and dev; CRC is dev.

expiration.yaml gains `enabled` (the owner, 2026-11-20): an environment with enabled: false takes no expiry, as one with
no entry, and prod may have an entry only with enabled: false.

Each test names one behaviour. Every API test runs a dry run or a create on the service suite's world, with PostgreSQL.
"""
from __future__ import annotations

import copy
import json
import shutil
from datetime import date, timedelta

import jsonschema
import pytest
import yaml

from cmapi.core.metadata import MetadataKeys
from cmapi.plugins.expiration.rules import ExpirationRules
from conftest import EXAMPLES, build_world
from metadata_corpus import SchemaReader
from test_flow import OLA, auth

URL = "/api/v1/clusters/CRC/namespaces"
ROOT = EXAMPLES.parent
DESIGN = yaml.safe_load("""
system: [cmapi.net/cluster-id, cmapi.net/managed, cmapi.net/request-id, cmapi.net/requested-by,
         cmapi.net/requested-by-user, cmapi.net/tier, cmapi.net/instance, cmapi.net/env, cmapi.net/tier-hash,
         cmapi.net/beyond-tier, cmapi.net/expiry, cmapi.net/expires-at]
operatorOnly: [cmapi.net/protected, do-not-delete]
reservedPrefixes: [kubernetes.io/, "*.kubernetes.io/", k8s.io/, openshift.io/, "*.openshift.io/",
                   argocd.argoproj.io/, "*.kyverno.io/", redhatcop.redhat.io/,
                   olm.operatorgroup.uid/, openshift-pipelines.tekton.dev/]
requiredLabels:
  name:
    value: {from: namespace}
    title: Name
  company.net/app-environment:
    value: {from: environment}
    namespaceSuffix: true
    title: App environment
  company.net/mnemonic:
    pattern: "^[a-z]{3,4}$"
    namespacePrefix: true
    title: Mnemonic
    description: "Your team's mnemonic, 3 or 4 lowercase letters; every namespace name starts with it"
    example: abc
  company.net/lob:
    title: Line of business
    description: "Free text, a valid label value"
    example: amgsst
  company.net/cl:
    enum: ["0", "1", "2", "3", "4", "5", "6"]
    title: Critical level
    example: "1"
  cmapi.net/team:
    pattern: "^[a-z0-9-]{2,40}$"
    default: {from: company.net/mnemonic}
    title: Team
    description: "Who owns it, for cost and notices; defaults to the mnemonic"
    example: payments
requiredAnnotations:
  company.net/app-environment:
    value: {from: environment}
  cmapi.net/team-dl:
    format: email-in-domains
    title: Team DL
    example: payments-team@company.net
extraLabels:
  keys:
    cmapi.net/cost-center: {pattern: "^cc-[0-9]{4}$", title: Cost center, example: cc-4410}
    cmapi.net/app:         {pattern: "^[a-z0-9-]{2,40}$", title: App, description: "Links an app's environments"}
    cmapi.net/rightsizing: {enum: [auto, manual], title: Rightsizing}
  allowOther: {prefixes: ["", "*.company.net/"], max: 50,
               example: {team.company.net/squad: checkout}}
extraAnnotations:
  keys:
    company.net/mnemonic-group-contact: {format: email-in-domains, title: Group contact}
    company.net/mnemonic-confluence:    {format: url, title: Confluence page}
  allowOther: {prefixes: ["", "*.company.net/"], max: 50, maxValueBytes: 4096, maxBytesTotal: 65536,
               example: {runbook.company.net/url: "https://wiki.company.net/abc/runbook"}}
adoptionLabels:
  company.net/provisioner: {recognise: [cluster-configs]}
sensitiveKeys: [cmapi.net/team, company.net/cl, cmapi.net/protected, do-not-delete]
emailDomains: [company.net]
""")
# The design's minimal API client (section 6.1): cmapi fills name, both app-environment keys and cmapi.net/team.
MINIMAL = {"namespace": "abc-payments-dev",
           "labels": {"company.net/mnemonic": "abc", "company.net/lob": "amgsst", "company.net/cl": "1"},
           "annotations": {"cmapi.net/team-dl": "payments-team@company.net"}}


def design() -> dict:
    """A copy of the design's configuration, for a test to change one field of."""
    return copy.deepcopy(DESIGN)


def refused(raw: dict) -> str:
    with pytest.raises(ValueError) as e:
        MetadataKeys(raw)
    return str(e.value)


@pytest.fixture
def design_config(test_config, tmp_path):
    """The suite's instance folder with the design's metadata-keys.yaml."""
    d = tmp_path / "config"
    shutil.copytree(test_config, d)
    (d / "metadata-keys.yaml").write_text(yaml.safe_dump(DESIGN, sort_keys=False))
    return d


@pytest.fixture
def design_world(design_config, fresh_db, keys, monkeypatch):
    with build_world(design_config, keys, monkeypatch) as world:
        yield world


def expiry_world(test_config, keys, monkeypatch, tmp_path, environments: dict):
    """The suite's instance with its own expiration.yaml environments."""
    d = tmp_path / "config"
    shutil.copytree(test_config, d)
    exp = yaml.safe_load((d / "expiration.yaml").read_text())
    exp["environments"] = environments
    (d / "expiration.yaml").write_text(yaml.safe_dump(exp))
    return build_world(d, keys, monkeypatch)


def dry_run(client, keys, body: dict):
    return client.post(URL + "?dryRun=true", json=body, headers=auth(keys, "ola", **OLA))


def errors_of(r) -> list[tuple[str, str, str]]:
    assert r.status_code == 422 and r.json()["code"] == "policy-violation", r.text
    return [(e["code"], e["key"], e.get("detail", "")) for e in r.json()["errors"]]


def rendered_namespace(r) -> dict:
    assert r.status_code == 200, r.text
    return yaml.safe_load(next(t for p, t in r.json()["files"].items() if p.endswith("/namespace.yaml")))


def create_schema(spec: dict) -> dict:
    return spec["components"]["schemas"]["NamespaceCreate"]


def create_example(spec: dict) -> dict:
    return spec["paths"][URL.replace("CRC", "{cluster_id}")]["post"]["requestBody"]["content"]["application/json"]["examples"]["permanent"]["value"]


# --------------------------------------------------------------------------- the loader (A8)

def test_the_designs_configuration_loads():
    keys = MetadataKeys(DESIGN)
    assert keys.prefix_key() == ("label", "company.net/mnemonic")
    assert keys.suffix_key() == ("label", "company.net/app-environment")
    assert keys.rules["label"]["cmapi.net/team"].default_from == "company.net/mnemonic"
    assert keys.allow_other["label"].example == {"team.company.net/squad": "checkout"}


def test_a_second_namespace_suffix_key_is_refused_at_load():
    raw = design()
    raw["requiredLabels"]["company.net/lob"]["namespaceSuffix"] = True
    assert "namespaceSuffix: only one key may have it" in refused(raw)


def test_a_second_namespace_prefix_key_is_refused_at_load():
    raw = design()
    raw["requiredLabels"]["company.net/lob"]["namespacePrefix"] = True
    assert "namespacePrefix: only one key may have it" in refused(raw)


def test_a_namespace_suffix_that_is_not_true_or_false_is_refused_at_load():
    raw = design()
    raw["requiredLabels"]["company.net/app-environment"]["namespaceSuffix"] = "yes"
    assert "namespaceSuffix must be true or false" in refused(raw)


def test_a_default_from_a_key_that_is_not_declared_is_refused_at_load():
    raw = design()
    raw["requiredLabels"]["cmapi.net/team"]["default"] = {"from": "company.net/nothing"}
    assert "default.from company.net/nothing is not a declared key" in refused(raw)


def test_a_default_from_a_key_of_the_other_kind_is_refused_at_load():
    raw = design()
    raw["requiredLabels"]["cmapi.net/team"]["default"] = {"from": "cmapi.net/team-dl"}
    assert "default.from cmapi.net/team-dl is an annotation, not a label" in refused(raw)


def test_a_default_from_a_filled_in_key_loads():
    raw = design()
    raw["requiredLabels"]["cmapi.net/team"]["default"] = {"from": "name"}
    assert MetadataKeys(raw).rules["label"]["cmapi.net/team"].default_from == "name"


def test_a_chain_of_defaults_is_refused_at_load():
    raw = design()
    raw["extraLabels"]["keys"]["cmapi.net/app"]["default"] = {"from": "cmapi.net/team"}
    assert "default.from cmapi.net/team has a default itself" in refused(raw)


def test_a_filled_in_key_with_a_default_is_refused_at_load():
    raw = design()
    raw["requiredLabels"]["name"]["default"] = {"from": "company.net/mnemonic"}
    assert "a key with value.from takes no pattern, enum, format, namespacePrefix or default" in refused(raw)


def test_a_default_that_is_not_from_a_key_is_refused_at_load():
    raw = design()
    raw["requiredLabels"]["cmapi.net/team"]["default"] = "company.net/mnemonic"
    assert "default must be {from: <key>}" in refused(raw)


def test_an_extra_key_example_that_allow_other_does_not_admit_is_refused_at_load():
    raw = design()
    raw["extraLabels"]["allowOther"]["example"] = {"other.example/squad": "checkout"}
    assert "extraLabels.allowOther.example.other.example/squad: not a key that allowOther admits" in refused(raw)


def test_an_extra_key_example_that_is_a_declared_key_is_refused_at_load():
    raw = design()
    raw["extraLabels"]["allowOther"]["example"] = {"cmapi.net/cost-center": "cc-4410"}
    assert "not a key that allowOther admits" in refused(raw)


def test_an_extra_key_example_with_an_invalid_label_value_is_refused_at_load():
    raw = design()
    raw["extraLabels"]["allowOther"]["example"] = {"team.company.net/squad": "check out"}
    assert "extraLabels.allowOther.example.team.company.net/squad: not a valid label key and value" in refused(raw)


def test_the_charts_values_schema_takes_the_new_fields_and_refuses_a_wrong_one():
    schema = json.loads((ROOT / "deploy/helm/cmapi/values.schema.json").read_text())
    check = jsonschema.Draft7Validator(schema)
    assert list(check.iter_errors({"metadata": DESIGN})) == []
    wrong = design()
    wrong["requiredLabels"]["company.net/app-environment"]["namespaceSuffix"] = "yes"
    assert list(check.iter_errors({"metadata": wrong})), "namespaceSuffix is a boolean"
    wrong = design()
    wrong["requiredLabels"]["name"]["default"] = {"from": "company.net/mnemonic"}
    assert list(check.iter_errors({"metadata": wrong})), "a filled-in key takes no default"


# --------------------------------------------------------------------------- validation (A8, A9), through a dry run

def test_a_name_that_starts_with_the_mnemonic_and_ends_with_the_environment_is_accepted(design_world):
    client, ctx, git, kube, validator, keys = design_world
    ns = rendered_namespace(dry_run(client, keys, MINIMAL))
    assert ns["metadata"]["name"] == "abc-payments-dev"


def test_a_name_without_the_mnemonic_prefix_is_refused(design_world):
    client, ctx, git, kube, validator, keys = design_world
    r = dry_run(client, keys, {**MINIMAL, "namespace": "payments-dev"})
    assert errors_of(r) == [("invalid_value", "company.net/mnemonic", "payments-dev does not start with abc-")]


def test_a_name_that_ends_with_another_environment_is_refused(design_world):
    client, ctx, git, kube, validator, keys = design_world
    r = dry_run(client, keys, {**MINIMAL, "namespace": "abc-payments-rnd"})
    assert errors_of(r) == [("invalid_value", "company.net/app-environment", "abc-payments-rnd does not end with -dev")]
    assert r.json()["errors"][0]["kind"] == "label"


def test_a_name_without_the_environment_suffix_is_refused(design_world):
    client, ctx, git, kube, validator, keys = design_world
    r = dry_run(client, keys, {**MINIMAL, "namespace": "abc-payments"})
    assert errors_of(r) == [("invalid_value", "company.net/app-environment", "abc-payments does not end with -dev")]


def test_a_mnemonic_that_breaks_its_pattern_gets_one_error_and_no_name_error(design_world):
    client, ctx, git, kube, validator, keys = design_world
    r = dry_run(client, keys, {**MINIMAL, "namespace": "ab-payments-dev",
                               "labels": {**MINIMAL["labels"], "company.net/mnemonic": "ab"}})
    assert errors_of(r) == [("invalid_value", "company.net/mnemonic", "must match ^[a-z]{3,4}$")]


def test_the_team_is_filled_from_the_mnemonic_when_left_out(design_world):
    client, ctx, git, kube, validator, keys = design_world
    ns = rendered_namespace(dry_run(client, keys, MINIMAL))
    assert ns["metadata"]["labels"]["cmapi.net/team"] == "abc"


def test_a_sent_team_is_kept_over_its_default(design_world):
    client, ctx, git, kube, validator, keys = design_world
    ns = rendered_namespace(dry_run(client, keys, {**MINIMAL, "labels": {**MINIMAL["labels"], "cmapi.net/team": "payments"}}))
    assert ns["metadata"]["labels"]["cmapi.net/team"] == "payments"


def test_a_filled_in_key_left_out_is_filled_in(design_world):
    client, ctx, git, kube, validator, keys = design_world
    ns = rendered_namespace(dry_run(client, keys, MINIMAL))
    assert ns["metadata"]["labels"]["name"] == "abc-payments-dev"
    assert ns["metadata"]["labels"]["company.net/app-environment"] == "dev"
    assert ns["metadata"]["annotations"]["company.net/app-environment"] == "dev"


def test_a_filled_in_key_sent_with_its_own_value_is_accepted(design_world):
    client, ctx, git, kube, validator, keys = design_world
    body = {**MINIMAL, "labels": {**MINIMAL["labels"], "name": "abc-payments-dev", "company.net/app-environment": "dev"},
            "annotations": {**MINIMAL["annotations"], "company.net/app-environment": "dev"}}
    assert dry_run(client, keys, body).status_code == 200


def test_a_filled_in_key_sent_with_another_value_is_refused(design_world):
    client, ctx, git, kube, validator, keys = design_world
    r = dry_run(client, keys, {**MINIMAL, "labels": {**MINIMAL["labels"], "name": "abc-other-dev"}})
    assert [(c, k) for c, k, _ in errors_of(r)] == [("derived_key", "name")]


def test_an_extra_key_goes_in_the_same_map_and_is_accepted(design_world):
    client, ctx, git, kube, validator, keys = design_world
    body = {**MINIMAL, "labels": {**MINIMAL["labels"], "team.company.net/squad": "checkout"}}
    assert rendered_namespace(dry_run(client, keys, body))["metadata"]["labels"]["team.company.net/squad"] == "checkout"


# --------------------------------------------------------------------------- the dry run's sources (A7)

def test_the_dry_run_gives_each_final_value_with_its_source(design_world):
    client, ctx, git, kube, validator, keys = design_world
    body = {**MINIMAL, "labels": {**MINIMAL["labels"], "team.company.net/squad": "checkout"}}
    r = dry_run(client, keys, body)
    assert r.status_code == 200, r.text
    assert r.json()["metadata"] == {
        "namespace": "abc-payments-dev",
        "labels": {
            "cmapi.net/team": {"value": "abc", "source": "default:company.net/mnemonic"},
            "company.net/app-environment": {"value": "dev", "source": "environment"},
            "company.net/cl": {"value": "1", "source": "request"},
            "company.net/lob": {"value": "amgsst", "source": "request"},
            "company.net/mnemonic": {"value": "abc", "source": "request"},
            "name": {"value": "abc-payments-dev", "source": "namespace"},
            "team.company.net/squad": {"value": "checkout", "source": "request"}},
        "annotations": {
            "cmapi.net/team-dl": {"value": "payments-team@company.net", "source": "request"},
            "company.net/app-environment": {"value": "dev", "source": "environment"}}}


def test_the_dry_run_keeps_changes_as_the_files_it_would_write(design_world):
    """A7 is additive: `changes` is still each changed file and its status, which the portal lists."""
    client, ctx, git, kube, validator, keys = design_world
    r = dry_run(client, keys, MINIMAL)
    assert r.status_code == 200 and set(r.json()["changes"].values()) == {"added"}
    assert all(path.startswith("clusters/CRC/namespaces/abc-payments-dev/") for path in r.json()["changes"])


# --------------------------------------------------------------------------- the contract (A1 to A6)

def test_filled_in_keys_are_required_and_not_read_only(design_world):
    client, *_ = design_world
    create = create_schema(client.get("/openapi.json").json())
    labels, annotations = create["properties"]["labels"], create["properties"]["annotations"]
    assert {"name", "company.net/app-environment"} <= set(labels["required"])
    assert "company.net/app-environment" in annotations["required"]
    for prop, source in ((labels["properties"]["name"], "namespace"),
                         (labels["properties"]["company.net/app-environment"], "environment"),
                         (annotations["properties"]["company.net/app-environment"], "environment")):
        assert "readOnly" not in prop and prop["x-cmapi-derived-from"] == source
        assert "you may leave it out" in prop["description"]


def test_a_defaulted_key_says_the_key_it_is_filled_from(design_world):
    client, *_ = design_world
    team = create_schema(client.get("/openapi.json").json())["properties"]["labels"]["properties"]["cmapi.net/team"]
    assert team["x-cmapi-default-from"] == "company.net/mnemonic"
    assert "Default: the value of company.net/mnemonic." in team["description"]


def test_the_environment_key_is_marked_as_the_end_of_the_name(design_world):
    client, *_ = design_world
    labels = create_schema(client.get("/openapi.json").json())["properties"]["labels"]["properties"]
    assert labels["company.net/app-environment"]["x-cmapi-namespace-suffix"] is True
    assert labels["company.net/mnemonic"]["x-cmapi-namespace-prefix"] is True


def test_the_namespace_says_the_keys_that_start_and_end_it(design_world):
    client, *_ = design_world
    namespace = create_schema(client.get("/openapi.json").json())["properties"]["namespace"]
    assert namespace["x-cmapi-prefix-from"] == "company.net/mnemonic"
    assert namespace["x-cmapi-suffix-from"] == "company.net/app-environment"
    assert "`<company.net/mnemonic>-<desired name>-<company.net/app-environment>`, at most 63" in namespace["description"]
    # The example cluster CRC is dev, though the instance serves rnd first: "Try it out" on CRC must be accepted.
    assert namespace["examples"] == ["abc-payments-dev"]


def test_the_create_example_is_made_from_the_configurations_examples(design_world):
    client, *_ = design_world
    example = create_example(client.get("/openapi.json").json())
    assert example["namespace"] == "abc-payments-dev"
    assert example["labels"] == {"name": "abc-payments-dev", "company.net/app-environment": "dev",
                                 "company.net/mnemonic": "abc", "company.net/lob": "amgsst", "company.net/cl": "1",
                                 "cmapi.net/team": "payments", "cmapi.net/cost-center": "cc-4410",
                                 "team.company.net/squad": "checkout"}
    assert example["annotations"] == {"company.net/app-environment": "dev", "cmapi.net/team-dl": "payments-team@company.net",
                                      "runbook.company.net/url": "https://wiki.company.net/abc/runbook"}


def test_the_create_example_passes_the_schema_and_a_dry_run(design_world):
    client, ctx, git, kube, validator, keys = design_world
    spec = client.get("/openapi.json").json()
    example = create_example(spec)
    schema = {"$ref": "#/components/schemas/NamespaceCreate", "components": spec["components"]}
    assert SchemaReader().validator(schema).is_valid(example)
    assert dry_run(client, keys, example).status_code == 200


def test_the_metadata_keys_route_answers_the_documents_maps(design_world):
    client, ctx, git, kube, validator, keys = design_world
    spec = client.get("/openapi.json").json()
    view = client.get("/api/v1/metadata-keys", headers=auth(keys, "ola", **OLA)).json()
    props = create_schema(spec)["properties"]
    for field in ("labels", "annotations"):
        assert view[field] == {k: v for k, v in props[field].items() if k not in ("title", "description", "examples")}


def test_the_tool_renders_the_document_that_the_instance_serves(design_config, design_world):
    """cmapi-tools openapi render with the instance's folder reads its clusters.yaml as serving does (#337, #479)."""
    from cmapi.tools import openapi as tool
    client, *_ = design_world
    cfg = tool.load(design_config / "metadata-keys.yaml", design_config)
    rendered = json.loads(tool.render(cfg, tool.cluster_environments(cfg, design_config)))
    assert rendered == client.get("/openapi.json").json()


# --------------------------------------------------------------------------- expiration (A11 and enabled)

def test_expires_at_shows_each_served_environments_expiration_rules(world):
    client, *_ = world
    expires = create_schema(client.get("/openapi.json").json())["properties"]["expiresAt"]
    rules = {"enabled": True, "allowedAtCreate": True, "maxLifetimeDays": 180, "notifyDaysBefore": [14, 7, 1], "graceDays": 7}
    assert expires["x-cmapi-expiration"] == {"environments": {"rnd": rules, "dev": rules}}
    assert expires["description"].startswith("Optional: the day the namespace expires, after today.")


def test_an_environment_with_expiration_off_shows_it_in_the_contract(test_config, fresh_db, keys, monkeypatch, tmp_path):
    with expiry_world(test_config, keys, monkeypatch, tmp_path, {"rnd": {}, "dev": {"enabled": False}}) as (client, *_):
        expires = create_schema(client.get("/openapi.json").json())["properties"]["expiresAt"]
    assert expires["x-cmapi-expiration"]["environments"]["dev"] == {"enabled": False}
    assert expires["x-cmapi-expiration"]["environments"]["rnd"]["enabled"] is True
    assert "Refused with expiration-not-allowed in dev, where expiration is off." in expires["description"]


def test_an_environment_with_expiration_off_refuses_expires_at(test_config, fresh_db, keys, monkeypatch, tmp_path):
    with expiry_world(test_config, keys, monkeypatch, tmp_path, {"rnd": {}, "dev": {"enabled": False}}) as world:
        client, ctx, git, kube, validator, keys = world
        body = {"namespace": "payments-dev", "labels": {"cmapi.net/team": "payments"},
                "annotations": {"cmapi.net/team-dl": "payments-team@ephico2real.com"},
                "expiresAt": (date.today() + timedelta(days=20)).isoformat()}
        r = client.post(URL, json=body, headers={**auth(keys, "ola", **OLA), "Idempotency-Key": "479-expiry-off"})
        assert r.status_code == 422 and r.json()["code"] == "expiration-not-allowed", r.text
        assert not any("payments-dev" in path for branch in git.branches.values() for path in branch), "nothing is written"


def test_an_environment_with_expiration_off_writes_neither_expiry_key(test_config, fresh_db, keys, monkeypatch, tmp_path):
    with expiry_world(test_config, keys, monkeypatch, tmp_path, {"rnd": {}, "dev": {"enabled": False}}) as world:
        client, ctx, git, kube, validator, keys = world
        body = {"namespace": "payments-dev", "labels": {"cmapi.net/team": "payments"},
                "annotations": {"cmapi.net/team-dl": "payments-team@ephico2real.com"}}
        ns = rendered_namespace(dry_run(client, keys, body))
        with_date = dry_run(client, keys, {**body, "expiresAt": (date.today() + timedelta(days=20)).isoformat()})
    assert "cmapi.net/expires-at" not in ns["metadata"]["annotations"] and "cmapi.net/expiry" not in ns["metadata"]["labels"]
    assert with_date.status_code == 422 and with_date.json()["code"] == "expiration-not-allowed"


def test_prod_with_expiration_off_loads():
    rules = ExpirationRules({"environments": {"prod": {"enabled": False}}}, {"prod"})
    assert "prod" in rules.envs and not rules.allows("prod")


def test_prod_with_expiration_on_is_refused_at_load():
    for entry in ({}, {"enabled": True}):
        with pytest.raises(ValueError, match="prod takes only enabled: false"):
            ExpirationRules({"environments": {"prod": entry}}, {"prod"})


def test_an_enabled_that_is_not_true_or_false_is_refused_at_load():
    with pytest.raises(ValueError, match="enabled is true or false"):
        ExpirationRules({"environments": {"dev": {"enabled": "no"}}}, {"dev"})


def test_the_prod_instances_file_turns_expiration_off_for_prod():
    rules = ExpirationRules.load(EXAMPLES / "instances/prod/expiration.yaml", {"prod"})
    assert rules.envs["prod"].enabled is False and not rules.allows("prod")
    assert rules.contract_view(["prod"]) == {"environments": {"prod": {"enabled": False}}}
