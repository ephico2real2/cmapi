"""The guards the chart's reviews earned, on the plain manifests (deploy/manifests): the chart tests read helm's output, so
nothing reads these files until the charts are removed. Ruling 3 of the deployment design: reviewed guards do not leave with
the charts. Static: no cluster, no database."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
COMPONENTS = ROOT / "deploy/manifests/components"
PLACEHOLDER = "ghcr.io/ephico2real2/cmapi@sha256:DIGEST"
TRUST = "/etc/cmapi/ca/ca-bundle.crt"
CHECKSUM_PLACEHOLDER = "CMAPI_CONFIG_CHECKSUM"
# The only images here that are not cmapi's, by repository. A digest bump changes nothing; a new repository is a decision.
OTHER_IMAGES = {"docker.io/nginxinc/nginx-unprivileged", "ghcr.io/cloudnative-pg/postgresql:17"}


def docs():
    # .yml too: kubectl apply -R and Argo CD take it, and render.sh only refuses one that holds a placeholder.
    for f in sorted([*COMPONENTS.rglob("*.yaml"), *COMPONENTS.rglob("*.yml")]):
        for d in yaml.safe_load_all(f.read_text()):
            if d:
                yield d


def workload(name):
    return next(d for d in docs() if d["kind"] == "Deployment" and d["metadata"]["name"] == name)["spec"]["template"]["spec"]


def deployments():
    return [d for d in docs() if d["kind"] == "Deployment"]


def env(container):
    return {e["name"]: e for e in container.get("env", [])}


def pod_annotations(name):
    d = next(d for d in deployments() if d["metadata"]["name"] == name)
    return d["spec"]["template"]["metadata"].get("annotations") or {}


@pytest.mark.parametrize("name", ["cmapi-api", "cmapi-worker"])
def test_a_changed_configuration_changes_the_pod_template(name):
    """The process reads its configuration once, at start, and the ConfigMaps are mutable, so without this a changed one leaves
    the running pods on the old values. deploy/render-test.sh proves the fill; this proves the two Deployments ask for it."""
    assert pod_annotations(name)["checksum/config"] == CHECKSUM_PLACEHOLDER


def test_the_readme_says_the_configuration_goes_first():
    """The checksum makes a restart, it does not order one: pods restarted before the ConfigMap changes keep the old values."""
    text = " ".join((ROOT / "deploy/manifests/README.md").read_text().split())
    assert "apply the environment, then the components, in that order" in text


def test_the_mockup_reads_none_of_that_configuration():
    assert "checksum/config" not in pod_annotations("cmapi-mockup")


def test_api_port_is_not_open_to_every_namespace():
    policy = next(d for d in docs() if d["kind"] == "NetworkPolicy" and d["metadata"]["name"] == "cmapi-metrics")
    api = next(r for r in policy["spec"]["ingress"] if any(p["port"] == 8080 for p in r["ports"]))
    assert api.get("from"), "a rule with no from: any pod on the shared cluster reaches 8080"
    # Whole, not "the router's label is among them": an added peer with an empty namespaceSelector would match every namespace
    # and still hold that label's peer.
    assert api["from"] == [
        {"namespaceSelector": {"matchLabels": {"policy-group.network.openshift.io/ingress": ""}}},
        {"podSelector": {}},
    ]


@pytest.mark.parametrize("name", ["cmapi-api", "cmapi-worker"])
def test_both_workloads_migrate_first_trusting_what_the_main_container_trusts(name):
    spec = workload(name)
    init = spec["initContainers"][0]
    assert init["command"] == ["cmapi-migrate", "head"]
    e = env(init)
    assert e["SSL_CERT_FILE"]["value"] == TRUST
    assert "PGSSLROOTCERT" not in e, "with CNPG's URI and a bundle without its CA, libpq falls back to plaintext (measured)"
    assert {"name": "trust", "mountPath": "/etc/cmapi/ca", "readOnly": True} in init["volumeMounts"]
    main = spec["containers"][0]
    assert {"name": "trust", "mountPath": "/etc/cmapi/ca", "readOnly": True} in main["volumeMounts"]
    assert env(main)["CMAPI_CA_BUNDLE"]["value"] == TRUST


@pytest.mark.parametrize("name", ["cmapi-api", "cmapi-worker"])
def test_the_database_url_comes_from_the_one_secret_key(name):
    spec = workload(name)
    for c in spec["initContainers"] + spec["containers"]:
        assert env(c)["CMAPI_DATABASE_URL"]["valueFrom"]["secretKeyRef"] == {"name": "cmapi-db-app", "key": "uri"}, c["name"]


def test_readiness_is_the_schema_and_liveness_does_no_io():
    api = workload("cmapi-api")["containers"][0]
    assert api["readinessProbe"]["httpGet"]["path"] == "/readyz" and api["startupProbe"]["httpGet"]["path"] == "/readyz"
    assert api["livenessProbe"]["httpGet"]["path"] == "/api/v1/version"


def test_every_container_has_requests_limits_and_the_restricted_shape():
    for d in deployments():
        pod = d["spec"]["template"]["spec"]
        assert pod["securityContext"]["runAsNonRoot"] is True and pod["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"
        assert "runAsUser" not in pod["securityContext"] and "fsGroup" not in pod["securityContext"]
        for c in pod.get("initContainers", []) + pod["containers"]:
            for side in ("requests", "limits"):
                assert {"cpu", "memory"} <= set(c["resources"][side]), (d["metadata"]["name"], c["name"], side)
            sc = c["securityContext"]
            assert sc["allowPrivilegeEscalation"] is False and sc["capabilities"]["drop"] == ["ALL"] and "runAsUser" not in sc


def images(node):
    """Every image and imageName under an object, whatever its kind: a Job or a sidecar runs an image as well."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("image", "imageName") and isinstance(value, str):
                yield value
            else:
                yield from images(value)
    elif isinstance(node, list):
        for value in node:
            yield from images(value)


def image_problems(objects):
    """The api and the worker run the placeholder and nothing else, so render.sh decides what they run. Anything else is the
    placeholder or a known repository pinned by a whole digest. Against a mistake (a digest pinned while debugging, a forgotten
    tag), not an attacker: whoever can edit the manifests in a pull request can edit this too, and review is what stops them."""
    problems = []
    for d in objects:
        name = d["metadata"]["name"]
        for image in images(d):
            repository, _, digest = image.partition("@sha256:")
            pinned = repository in OTHER_IMAGES and re.fullmatch(r"[0-9a-f]{64}", digest)
            ours = d["kind"] == "Deployment" and name in ("cmapi-api", "cmapi-worker")
            if image != PLACEHOLDER and (ours or not pinned):
                problems.append(f"{d['kind']}/{name}: {image}")
    return problems


def test_every_image_is_the_placeholder_or_a_known_digest():
    objects = list(docs())
    assert image_problems(objects) == []
    assert sum(1 for d in objects for image in images(d) if image == PLACEHOLDER) == 4, "two Deployments, each a migrate and a main container"


EVIL = "ghcr.io/evil/cmapi@sha256:" + "e" * 64


def _containers(objects, name):
    pod = next(d for d in objects if d["kind"] == "Deployment" and d["metadata"]["name"] == name)["spec"]["template"]["spec"]
    return pod.get("initContainers", []) + pod["containers"]


@pytest.mark.parametrize("change", [
    pytest.param(lambda o: _containers(o, "cmapi-api")[0].update(image=EVIL), id="the api's migrate container"),
    pytest.param(lambda o: _containers(o, "cmapi-worker")[1].update(image=EVIL), id="the worker's main container"),
    pytest.param(lambda o: _containers(o, "cmapi-mockup")[0].update(image=EVIL), id="the mockup, another repository"),
    pytest.param(lambda o: _containers(o, "cmapi-mockup")[0].update(image="docker.io/nginxinc/nginx-unprivileged:latest"), id="the mockup, a tag"),
    pytest.param(lambda o: _containers(o, "cmapi-mockup")[0].update(image="docker.io/nginxinc/nginx-unprivileged@sha256:abc"), id="the mockup, a short digest"),
    pytest.param(lambda o: next(d for d in o if d["kind"] == "Cluster")["spec"].update(imageName="ghcr.io/cloudnative-pg/postgresql:17"), id="the database, a tag"),
    pytest.param(lambda o: o.append({"kind": "Job", "metadata": {"name": "x"}, "spec": {"template": {"spec": {"containers": [{"name": "x", "image": EVIL}]}}}}), id="a Job"),
])
def test_the_image_guard_can_fail(change):
    objects = list(docs())
    assert image_problems(objects) == []
    change(objects)
    assert image_problems(objects), "the guard let this through"


def test_the_database_keeps_itself_and_names_no_storage_class():
    cluster = next(d for d in docs() if d["kind"] == "Cluster")
    assert set(cluster["metadata"]["annotations"]["argocd.argoproj.io/sync-options"].split(",")) >= {"Prune=false", "Delete=false"}
    assert "@sha256:" in cluster["spec"]["imageName"] and "storageClass" not in cluster["spec"]["storage"]


def test_nothing_here_is_kind_only_or_a_secret():
    assert not [d["metadata"]["name"] for d in docs() if d["kind"] in ("Secret", "Namespace")]
