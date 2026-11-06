"""#91: the api, the worker and migrate connect to CloudNativePG with sslmode=verify-full against its CA, and refuse plaintext. CNPG
writes the URI, with no sslmode in it, so the Deployments give libpq its defaults: PGSSLMODE, and PGSSLROOTCERT naming ca.crt of
Secret <cluster>-ca, projected beside the trust bundle. A URI that says otherwise wins, which is how docs/12's external server keeps
working. Static on the manifests and the renders, real libpq against the plaintext PostgreSQL of this suite. deploy/kind-test.sh
proves the rest on CNPG itself: pg_stat_ssl, and a CA that does not cover the server."""
from __future__ import annotations

import subprocess
from pathlib import Path

import psycopg
import pytest
import yaml

from conftest import DB_URL

ROOT = Path(__file__).resolve().parents[3]
CA_FILE = "/etc/cmapi/ca/database-ca.crt"
GHCR = "ghcr.io/ephico2real2/cmapi@sha256:" + "a" * 64
INTERNAL = "image-registry.openshift-image-registry.svc:5000/cmapi/cmapi@sha256:" + "a" * 64


def objects_in(folder):
    return [d for f in sorted(folder.rglob("*.yaml")) for d in yaml.safe_load_all(f.read_text()) if d]


@pytest.fixture(scope="module", params=["source", "kind", "crc"])
def components(request, tmp_path_factory):
    """What is applied: the source, and the render for each environment, so that an environment cannot lose it."""
    if request.param == "source":
        return objects_in(ROOT / "deploy/manifests/components")
    out = tmp_path_factory.mktemp("render") / "out"
    image = INTERNAL if request.param == "crc" else GHCR
    subprocess.run([ROOT / "deploy/render.sh", request.param, image, out], check=True, capture_output=True)
    return objects_in(out / "components")


def pod(objects, name):
    return next(d for d in objects if d["kind"] == "Deployment" and d["metadata"]["name"] == name)["spec"]["template"]["spec"]


def env_of(container):
    return {e["name"]: e for e in container.get("env", [])}


WORKLOADS = ["cmapi-api", "cmapi-worker"]
CONTAINERS = [("cmapi-api", "initContainers"), ("cmapi-api", "containers"), ("cmapi-worker", "initContainers"), ("cmapi-worker", "containers")]


def container(objects, name, where):
    return pod(objects, name)[where][0]


@pytest.mark.parametrize("name,where", CONTAINERS)
def test_every_connection_verifies_the_server_against_the_cnpg_ca(components, name, where):
    env = env_of(container(components, name, where))
    assert env["PGSSLMODE"] == {"name": "PGSSLMODE", "value": "verify-full"}
    assert env["PGSSLROOTCERT"] == {"name": "PGSSLROOTCERT", "value": CA_FILE}
    assert env["CMAPI_DATABASE_URL"]["valueFrom"]["secretKeyRef"] == {"name": "cmapi-db-app", "key": "uri"}


@pytest.mark.parametrize("name", WORKLOADS)
def test_the_ca_is_the_public_certificate_of_the_clusters_own_secret(components, name):
    """<cluster>-ca also holds ca.key, which signs server certificates: items projects ca.crt alone, so the key never reaches a pod.
    Optional, or a site on an existing server (docs/12), which has no such Secret, never gets past ContainerCreating."""
    cluster = next(d for d in components if d["kind"] == "Cluster")["metadata"]["name"]
    trust = next(v for v in pod(components, name)["volumes"] if v["name"] == "trust")
    secrets = [s["secret"] for s in trust["projected"]["sources"] if "secret" in s]
    assert secrets == [{"name": f"{cluster}-ca", "optional": True, "items": [{"key": "ca.crt", "path": Path(CA_FILE).name}]}]


@pytest.mark.parametrize("name", WORKLOADS)
def test_the_trust_bundle_stays_in_that_volume(components, name):
    trust = next(v for v in pod(components, name)["volumes"] if v["name"] == "trust")
    assert {"configMap": {"name": "cmapi-trust", "items": [{"key": "ca-bundle.crt", "path": "ca-bundle.crt"}]}} in trust["projected"]["sources"]


@pytest.mark.parametrize("name,where", CONTAINERS)
def test_a_renewed_ca_reaches_a_running_container(components, name, where):
    """CNPG renews ca.crt in place, in a Secret no checksum reads (internal/controller/cluster_pki.go, renewCASecret). A projected
    volume follows the Secret and libpq reads the file at every connection; a subPath mount would freeze it until the pod restarts."""
    mounts = [m for m in container(components, name, where)["volumeMounts"] if m["name"] == "trust"]
    assert mounts == [{"name": "trust", "mountPath": str(Path(CA_FILE).parent), "readOnly": True}]


@pytest.mark.parametrize("name", WORKLOADS)
def test_a_uid_openshift_chooses_can_read_the_file(components, name):
    """restricted-v2: an arbitrary UID, no fsGroup in the manifests, and files owned by root, so the kubelet's default mode 0644 is what
    lets it read. The pod's own shape is held by test_plain_manifests; a mode set here would break the read only on CRC."""
    trust = next(v for v in pod(components, name)["volumes"] if v["name"] == "trust")
    assert "defaultMode" not in trust["projected"]
    assert all("mode" not in item for s in trust["projected"]["sources"] for src in s.values() for item in src["items"])
    assert "fsGroup" not in pod(components, name)["securityContext"]


# ------------------------------------------------------------------ real libpq, with the manifests' own values
def libpq_defaults_of(name, where, monkeypatch):
    """The manifest's PG* values in this process's environment, where libpq reads them. Whatever is absent stays absent: a Deployment
    with none of them must read here as what it is, libpq's default sslmode=prefer."""
    objects = objects_in(ROOT / "deploy/manifests/components")
    for key in ("PGSSLMODE", "PGSSLROOTCERT"):
        monkeypatch.delenv(key, raising=False)
    for key, e in env_of(container(objects, name, where)).items():
        if key.startswith("PG"):
            monkeypatch.setenv(key, e["value"])


@pytest.mark.parametrize("name,where", CONTAINERS)
def test_a_cnpg_shaped_uri_refuses_a_server_without_tls(name, where, monkeypatch):
    """This suite's PostgreSQL has no TLS, like a server or a man in the middle that answers plaintext. CNPG's URI has no sslmode."""
    libpq_defaults_of(name, where, monkeypatch)
    assert "sslmode" not in DB_URL
    with pytest.raises(psycopg.OperationalError, match="SSL"):
        psycopg.connect(DB_URL, connect_timeout=5)


@pytest.mark.parametrize("name,where", CONTAINERS)
def test_what_the_uri_says_wins_over_the_default(name, where, monkeypatch):
    """Why docs/12's URI keeps its own sslmode and sslrootcert: the Deployments' values are only defaults (libpq's documentation,
    "if no value is directly specified"). sslmode=disable here stands for any value a URI names, against this suite's plaintext server."""
    libpq_defaults_of(name, where, monkeypatch)
    with psycopg.connect(DB_URL + "?sslmode=disable", connect_timeout=5) as c:
        assert c.execute("select 1").fetchone() == (1,)
