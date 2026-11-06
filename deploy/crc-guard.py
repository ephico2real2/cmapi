#!/usr/bin/env python3
"""deploy/crc-guard.py: the guards of the Wave 1 run on CRC, a shared cluster. Python's standard library and `oc` only; reads only, except
`import-wait`, which may delete cmapi's own KeycloakRealmImport by name. Never prints a secret; TLS is always verified against CMAPI_CRC_CA.

  preflight [--needs MI]       this is CRC and its kubeadmin, no kind cluster, nothing of cmapi's where nothing should be, request headroom
  headroom --needs MI          stop unless request headroom minus MI is at least 2 GiB
  check-import FILE            the one document is KeycloakRealmImport cmapi of realm cmapi, namespace keycloak, Keycloak CR keycloak
  issuer                       realm cmapi: exit 0 present, 10 absent, 20 anything else (never read as absent)
  snapshot FILE                the other realms and their imports, keycloak-0, postgres-0, the Keycloak CR, with no credential
  compare BEFORE AFTER         stop on any difference
  watch LOG STOPFILE BASELINE  poll every realm every 5 s until LOG.done appears; on a breach write STOPFILE and report at 300 s
  gate STOPFILE                exit 1 if the run is stopped, or a watch that began is no longer looking
  watching STOPFILE            exit 1 unless the watch of this run has begun and is looking
  import-wait STOPFILE         follow our import; withdraw it, by name, if it has not started in time

Exit codes: 0 fine, 1 stop, 2 usage."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import http.client
import json
import os
import re
import shlex
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

KEYCLOAK = os.environ.get("CMAPI_KEYCLOAK_URL", "https://keycloak.apps-crc.testing")
API_SERVER = os.environ.get("CMAPI_CRC_API", "https://api.crc.testing:6443")
# What `oc login` on CRC writes: <namespace>/api-crc-testing:6443/kubeadmin.
CONTEXT_SUFFIX = "/api-crc-testing:6443/kubeadmin"
# The API names this virtual user kube:admin, and the kubeconfig kubeadmin. Which one `oc whoami` prints here has not been read from CRC, so either passes.
PRINCIPALS = ("kube:admin", "kubeadmin")
NS = "keycloak"
OURS = "cmapi"
# What the coordinator read on 2026-11-06. A realm no import names is invisible without a credential, so these are always asked for.
KNOWN_REALMS = ("master", "corp", "inkcast-prod", "inkcast-staging", "tutorial")
STOP_LINE_MI = 2048
POLL_SECONDS = float(os.environ.get("CMAPI_GUARD_POLL", "5"))
REPORT_AFTER_SECONDS = float(os.environ.get("CMAPI_GUARD_REPORT_AFTER", "300"))
SCHEDULE_DEADLINE = float(os.environ.get("CMAPI_GUARD_SCHEDULE_DEADLINE", "300"))
RUN_DEADLINE = float(os.environ.get("CMAPI_GUARD_RUN_DEADLINE", "300"))
# Longer than one round of the watch can take: five realms at 3 s, oc's 60 s, the poll.
WATCH_STALE_SECONDS = float(os.environ.get("CMAPI_GUARD_WATCH_STALE", "120"))
WATCH_START_SECONDS = float(os.environ.get("CMAPI_GUARD_WATCH_START", "15"))


class Stop(Exception):
    pass


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def oc(*args: str, check: bool = True) -> str:
    r = subprocess.run([*shlex.split(os.environ.get("CMAPI_OC", "oc")), *args], capture_output=True, text=True, timeout=60)
    if check and r.returncode != 0:
        raise Stop(f"oc {args[0]} {' '.join(a for a in args[1:4])}: {r.stderr.strip()[:300]}")
    return r.stdout


def oc_json(*args: str) -> dict:
    out = oc(*args, "-o", "json")
    return json.loads(out) if out.strip() else {}


def tls() -> ssl.SSLContext:
    ca = os.environ.get("CMAPI_CRC_CA")
    if not ca or not os.path.isfile(ca):
        raise Stop("CMAPI_CRC_CA must name the CA bundle (deploy/crc-trust.sh --mac-ca); TLS verification is never off")
    c = ssl.create_default_context(cafile=ca)
    # Hostname and chain are verified. Python 3.13's stricter default also refuses a chain missing an RFC 5280 extension such as the Authority Key Identifier,
    # which curl accepts (measured here on Python 3.14 with a plain openssl CA), and a false stop on a shared cluster's guard is a failure too.
    c.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return c


def http_get(url: str, timeout: float = 5) -> tuple[int, bytes]:
    """(status, body); status 0 for anything that gave no HTTP answer, a certificate failure included."""
    try:
        with urllib.request.urlopen(url, timeout=timeout, context=tls()) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        # The status came, the body may not: raised in this handler, the next one could not catch it.
        try:
            return e.code, e.read()
        except (http.client.HTTPException, OSError, ValueError):
            return e.code, b""
    # HTTPException: a Keycloak going down can cut an answer short, and that must read as no answer, not end the watch.
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
        return 0, b""


def realm_state(name: str, timeout: float = 5) -> dict:
    status, body = http_get(f"{KEYCLOAK}/realms/{name}", timeout)
    key = None
    if status == 200:
        try:
            key = hashlib.sha256(json.loads(body)["public_key"].encode()).hexdigest()
        except (ValueError, KeyError, TypeError, AttributeError):
            status = -1                                     # a 200 that is not a realm document is not a realm
    return {"status": status, "public_key_sha256": key}


def issuer_state() -> str:
    """present, absent or unknown. Only Keycloak's own 404 is absent: a router's 404 or 503, a timeout or a bad certificate is not."""
    status, body = http_get(f"{KEYCLOAK}/realms/{OURS}")
    try:
        doc = json.loads(body)
    except ValueError:
        return "unknown"
    if not isinstance(doc, dict):
        return "unknown"
    if status == 200 and doc.get("realm") == OURS:
        return "present"
    if status == 404 and doc == {"error": "Realm does not exist"}:
        return "absent"
    return "unknown"


def condition(obj: dict, kind: str) -> str | None:
    for c in obj.get("status", {}).get("conditions", []) or []:
        if c.get("type") == kind:
            return str(c.get("status")).lower()
    return None


def pod_state(name: str) -> dict:
    p = oc_json("get", "pod", name, "-n", NS)
    cs = (p.get("status", {}).get("containerStatuses") or [{}])[0]
    return {"uid": p["metadata"]["uid"], "started": (cs.get("state", {}).get("running") or {}).get("startedAt"),
            "restarts": cs.get("restartCount"), "ready": cs.get("ready")}


def snapshot() -> dict:
    imports = oc_json("get", "keycloakrealmimport", "-n", NS).get("items", [])
    names = set(KNOWN_REALMS) | {i["spec"]["realm"]["realm"] for i in imports if i["metadata"]["name"] != OURS}
    realms = {n: realm_state(n) for n in sorted(names)}
    bad = {n: s["status"] for n, s in realms.items() if s["status"] != 200}
    if bad:
        raise Stop(f"a realm does not answer 200: {bad}")
    return {"realms": realms,
            "imports": {i["metadata"]["name"]: {"uid": i["metadata"]["uid"], "created": i["metadata"]["creationTimestamp"],
                                                "generation": i["metadata"].get("generation"), "done": condition(i, "Done")}
                        for i in imports if i["metadata"]["name"] != OURS},
            "keycloak-0": pod_state("keycloak-0"), "postgres-0": pod_state("postgres-0"),
            "keycloak_cr_generation": oc_json("get", "keycloak", "keycloak", "-n", NS)["metadata"]["generation"]}


def diff(a, b, path: str = "") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        return [d for k in sorted(set(a) | set(b)) for d in diff(a.get(k, "<absent>"), b.get(k, "<absent>"), f"{path}/{k}")]
    return [] if a == b else [f"{path}: {a} -> {b}"]


def headroom_mi() -> int:
    node = oc_json("get", "node", "crc")["status"]["allocatable"]["memory"]
    m = re.fullmatch(r"(\d+)(Ki|Mi|Gi)?", node)
    if not m:
        raise Stop(f"allocatable memory {node} is not understood")
    alloc = int(m[1]) * {"Ki": 1 / 1024, "Mi": 1, "Gi": 1024, None: 1 / 1048576}[m[2]]
    # The row of "Allocated resources", in non-terminated pods: a finished import no longer counts.
    m = re.search(r"^\s+memory\s+(\d+)(Ki|Mi|Gi)?\s", oc("describe", "node", "crc"), re.M)
    if not m:
        raise Stop("no memory requests in oc describe node crc")
    req = int(m[1]) * {"Ki": 1 / 1024, "Mi": 1, "Gi": 1024, None: 1 / 1048576}[m[2]]
    return int(alloc - req)


def need_headroom(needs: int) -> None:
    h = headroom_mi()
    print(f"{now()} request headroom {h} Mi, this step needs {needs} Mi, leaving {h - needs} Mi; the stop line is {STOP_LINE_MI} Mi")
    if h - needs < STOP_LINE_MI:
        raise Stop("under the stop line")


def check_principal() -> None:
    """The context and the principal, as well as the server: a kubeconfig pointing at CRC as someone else would pass on the server alone."""
    server = oc("whoami", "--show-server").strip()
    if server != API_SERVER:
        raise Stop(f"oc points at {server}, not {API_SERVER}")
    context = oc("config", "current-context").strip()
    if not context.endswith(CONTEXT_SUFFIX):
        raise Stop(f"the context is {context}, not <namespace>{CONTEXT_SUFFIX}")
    user = oc("whoami").strip()
    if user not in PRINCIPALS:
        raise Stop(f"oc is logged in as {user}, not as kubeadmin")


def preflight(needs: int) -> None:
    check_principal()
    clusters = subprocess.run(["kind", "get", "clusters"], capture_output=True, text=True,
                              env={**os.environ, "KIND_EXPERIMENTAL_PROVIDER": "podman"}, timeout=30)
    names = [c for c in clusters.stdout.split() if c]
    if clusters.returncode != 0 or names:
        raise Stop(f"a kind cluster exists or cannot be listed: {names or clusters.stderr.strip()[:200]}; none may run during a CRC step")
    need_headroom(needs)
    for ns in ("cmapi-imports", "cmapi-system"):
        if oc("get", "ns", ns, "--ignore-not-found", "-o", "name").strip():
            print(f"note    : namespace {ns} exists: it is cmapi's only if an earlier step of this run made it")
    for pod in ("keycloak-0", "postgres-0"):
        if not pod_state(pod)["ready"]:
            raise Stop(f"{pod} is not Ready")


def check_import(path: str) -> None:
    """On the text, with no YAML library: this runs on a Mac's plain python3 before the one apply into a shared namespace. Each line is
    required exactly, once, and a second document is refused, so no other realm or namespace can hide in the file."""
    text = open(path).read()
    if re.search(r"^---", text, re.M) or re.search(r"^\.\.\.", text, re.M):
        raise Stop(f"{path} holds more than one document")
    required = (r"^kind: KeycloakRealmImport$", r"^metadata:$", r"^  name: cmapi$", r"^  namespace: keycloak$", r"^spec:$",
                r"^  keycloakCRName: keycloak$", r"^  realm:$", r"^    realm: cmapi$")
    for pattern in required:
        if len(re.findall(pattern, text, re.M)) != 1:
            raise Stop(f"{path}: must hold exactly one line matching {pattern}")
    # Any other top-level or metadata name, or a realm key at the realm's indent, would be a second answer to the same question.
    if re.findall(r"^    (?:realm|id): (?!cmapi$).*$", text, re.M):
        raise Stop(f"{path}: spec.realm names a realm other than cmapi")
    print(f"{now()} {os.path.basename(path)}: KeycloakRealmImport cmapi, realm cmapi, namespace keycloak")


def stop_the_run(stop_file: str) -> None:
    open(stop_file, "a").close()


def why_stopped(stop_file: str) -> str | None:
    """Why nothing more may run, or None. The stop file, or a watch that began and is no longer looking: killed, hung or asleep with the Mac, it writes nothing,
    so the file alone would read that blindness as all well. No heartbeat means it has not begun, or ended cleanly."""
    if os.path.exists(stop_file):
        return f"this run is stopped ({stop_file}); nothing more runs until the owner has been told"
    alive = stop_file + ".alive"
    try:
        with open(alive) as f:
            pid = int(f.read())
            age = time.time() - os.fstat(f.fileno()).st_mtime
    except FileNotFoundError:
        return None
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):           # PermissionError: another user's process has that number now, so it is not the watch
        return f"the watch (pid {pid}) is not running, so nothing is watching Keycloak"
    if age > WATCH_STALE_SECONDS:
        return f"the watch (pid {pid}) has not looked for {int(age)} s"
    return None


def watching(stop_file: str) -> None:
    t0 = time.monotonic()
    while not os.path.exists(stop_file + ".alive"):
        if os.path.exists(stop_file) or time.monotonic() - t0 > WATCH_START_SECONDS:
            raise Stop("the watch did not begin; read its output")
        time.sleep(0.1)
    why = why_stopped(stop_file)
    if why:
        raise Stop(why)
    print(f"{now()} the watch is looking")


def watch(log: str, stop_file: str, baseline_file: str) -> int:
    """A watch that ends before LOG.done, for any reason, is one nobody is reading: the run stops. A guard that cannot look never reads as healthy."""
    try:
        return follow(log, stop_file, baseline_file)
    except BaseException as e:
        stop_the_run(stop_file)
        print(f"{now()} BREACH, the run is stopped: the watch ended: {type(e).__name__}: {str(e)[:200]}", flush=True)
        return 1


def follow(log: str, stop_file: str, baseline_file: str) -> int:
    base = json.load(open(baseline_file))
    realms = sorted(base["realms"])
    alive = stop_file + ".alive"
    # Whole or not at all: gate and watching read it at any moment.
    with open(alive + ".new", "w") as f:
        f.write(str(os.getpid()))
    os.replace(alive + ".new", alive)
    breach_since = None
    reported = recovered = False
    rc = 0
    with open(log, "a", buffering=1) as f:
        def say(line: str) -> None:
            f.write(f"{now()} {line}\n")
        say(f"watch: every {POLL_SECONDS:g} s, realms {realms}")
        while not os.path.exists(log + ".done"):
            t0 = time.monotonic()
            os.utime(alive)
            problems = []
            statuses = {}
            kc = {}
            # Every exception, not a list of them: the list is what let this die twice. It logs on, so the outage's length is on record.
            try:
                for r in realms:
                    s = realm_state(r, timeout=3)
                    statuses[r] = s["status"]
                    if s["status"] != 200:
                        problems.append(f"{r}={s['status']}")
                    elif s["public_key_sha256"] != base["realms"][r]["public_key_sha256"]:
                        problems.append(f"{r}: public key changed")
                try:
                    kc = pod_state("keycloak-0")
                    b = base["keycloak-0"]
                    if (kc["uid"], kc["restarts"], kc["started"]) != (b["uid"], b["restarts"], b["started"]):
                        problems.append(f"keycloak-0 restarted: {kc}")
                    elif not kc["ready"]:
                        problems.append("keycloak-0 not Ready")
                except (Stop, KeyError, ValueError, OSError, subprocess.SubprocessError) as e:
                    kc = {}
                    problems.append(f"keycloak-0 unreadable: {str(e)[:120]}")
            except Exception as e:
                problems.append(f"the watch could not look: {type(e).__name__}: {str(e)[:120]}")
            say(f"realms {statuses} keycloak-0 {kc.get('restarts')}/{kc.get('ready')} {'BREACH ' + '; '.join(problems) if problems else 'ok'}")
            down = any(s != 200 for s in statuses.values()) or not kc.get("ready")
            if problems and breach_since is None:
                breach_since = time.monotonic()
                rc = 3
                stop_the_run(stop_file)
                say("STOP: every cmapi step stops now. cmapi takes no action on Keycloak: no delete, no restart. Report to the owner")
                print(f"{now()} BREACH, the run is stopped: {'; '.join(problems)}", flush=True)
            if breach_since is not None:
                waited = time.monotonic() - breach_since
                if down and waited >= REPORT_AFTER_SECONDS and not reported:
                    reported = True
                    say(f"REPORT TO THE OWNER NOW: Keycloak still not back after {int(waited)} s; the one measured restart took 162 s")
                    print(f"{now()} REPORT TO THE OWNER NOW: Keycloak not back after {int(waited)} s", flush=True)
                if not down and not recovered:
                    recovered = True
                    say(f"Keycloak answers again after {int(waited)} s; the run stays stopped")
            time.sleep(max(0.0, POLL_SECONDS - (time.monotonic() - t0)))
        say(f"watch ended rc={rc}")
    os.unlink(alive)
    return rc


def import_pods() -> list[dict]:
    return oc_json("get", "pods", "-n", NS, "-l", f"job-name={OURS}").get("items", [])


def container_started(pod: dict) -> bool:
    for c in pod.get("status", {}).get("containerStatuses") or []:
        st = c.get("state", {})
        if "running" in st or "terminated" in st:
            return True
    return False


def pod_failed(pod: dict) -> bool:
    if pod.get("status", {}).get("phase") == "Failed":
        return True
    return any((c.get("state", {}).get("terminated") or {}).get("exitCode") not in (None, 0) for c in pod.get("status", {}).get("containerStatuses") or [])


def withdraw(reason: str) -> None:
    """Delete our import, by name and only by name. The operator owns its Job and Secret through owner references (GarbageCollected,
    KeycloakRealmImportJobDependentResource.java:59), so they go with it, and a pod that has not started never will."""
    print(f"{now()} withdrawing KeycloakRealmImport {OURS}: {reason}", flush=True)
    oc("delete", "keycloakrealmimport", OURS, "-n", NS, "--wait=true", "--timeout=60s")
    left = oc("get", "job", OURS, "-n", NS, "--ignore-not-found", "-o", "name").strip()
    print(f"{now()} withdrawn; Job left: {left or 'none'}; realm cmapi is {issuer_state()}", flush=True)


def import_wait(stop_file: str) -> int:
    t0 = time.monotonic()
    started_at = None
    pods: list[dict] = []
    while True:
        # A read that fails says nothing about the import, and ending here would leave a pending one to start unattended. So go on, on what was last known, to the same deadlines.
        try:
            kri, pods = oc_json("get", "keycloakrealmimport", OURS, "-n", NS, "--ignore-not-found"), import_pods()
            if not kri:
                print(f"STOP: KeycloakRealmImport {OURS} is not there", file=sys.stderr)
                return 1
            started = any(container_started(p) for p in pods)
        except (Stop, KeyError, ValueError, OSError, subprocess.SubprocessError) as e:
            print(f"{now()} could not read the import: {str(e)[:200]}", flush=True)
            kri, started = {}, started_at is not None
        if started and started_at is None:
            started_at = time.monotonic()
            print(f"{now()} the import's container started {int(started_at - t0)} s after the apply", flush=True)
        if condition(kri, "Done") == "true" and condition(kri, "HasErrors") != "true":
            state = issuer_state()
            print(f"{now()} import Done after {int(time.monotonic() - t0)} s; realm cmapi is {state}")
            if why_stopped(stop_file):
                # A running import is left to finish, but a breach during it still stops what comes next.
                print(f"{now()} the watch stopped the run while the import ran; nothing more runs until the owner has been told", flush=True)
                return 1
            return 0 if state == "present" else 1
        # A failed pod, not the condition alone: the operator also sets HasErrors for an error of its own while a pod runs on (updateErrorStatus, KeycloakRealmImportController.java:101-109), and a running import is never interrupted.
        if condition(kri, "HasErrors") == "true" and any(pod_failed(p) for p in pods):
            # The Job has no backoffLimit of its own (buildJob sets none), so Kubernetes' default of 6 would start more pods.
            withdraw("the import failed; this stops the Job's further attempts")
            return 1
        if not started and why_stopped(stop_file):
            withdraw("the run is stopped and the import has not started")
            return 1
        if not started and time.monotonic() - t0 > SCHEDULE_DEADLINE:
            phases = [p.get("status", {}).get("phase") for p in pods]
            withdraw(f"not started after {int(SCHEDULE_DEADLINE)} s (pods {phases}); left alone it could start unattended, days later")
            return 1
        if started and time.monotonic() - started_at > RUN_DEADLINE:
            print(f"{now()} the import has run {int(RUN_DEADLINE)} s without finishing. It is not interrupted; report to the owner", flush=True)
            return 1
        time.sleep(POLL_SECONDS)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("preflight"); p.add_argument("--needs", type=int, default=0)
    p = sub.add_parser("headroom"); p.add_argument("--needs", type=int, required=True)
    p = sub.add_parser("check-import"); p.add_argument("file")
    sub.add_parser("issuer")
    p = sub.add_parser("snapshot"); p.add_argument("file")
    p = sub.add_parser("compare"); p.add_argument("before"); p.add_argument("after")
    p = sub.add_parser("watch"); p.add_argument("log"); p.add_argument("stop_file"); p.add_argument("baseline")
    p = sub.add_parser("gate"); p.add_argument("stop_file")
    p = sub.add_parser("watching"); p.add_argument("stop_file")
    p = sub.add_parser("import-wait"); p.add_argument("stop_file")
    a = ap.parse_args()
    try:
        if a.cmd == "preflight":
            preflight(a.needs)
        elif a.cmd == "headroom":
            need_headroom(a.needs)
        elif a.cmd == "check-import":
            check_import(a.file)
        elif a.cmd == "issuer":
            state = issuer_state()
            print(f"realm cmapi: {state}")
            return {"present": 0, "absent": 10}.get(state, 20)
        elif a.cmd == "snapshot":
            s = snapshot()
            with open(a.file, "w") as f:
                json.dump(s, f, indent=1, sort_keys=True)
            print(f"{now()} snapshot: {len(s['realms'])} realms, {len(s['imports'])} other imports, keycloak-0 restarts {s['keycloak-0']['restarts']}")
        elif a.cmd == "compare":
            d = diff(json.load(open(a.before)), json.load(open(a.after)))
            if d:
                raise Stop("something changed:\n  " + "\n  ".join(d))
            print(f"{now()} no difference: {os.path.basename(a.before)} and {os.path.basename(a.after)}")
        elif a.cmd == "watch":
            return watch(a.log, a.stop_file, a.baseline)
        elif a.cmd == "gate":
            why = why_stopped(a.stop_file)
            if why:
                raise Stop(why)
        elif a.cmd == "watching":
            watching(a.stop_file)
        elif a.cmd == "import-wait":
            return import_wait(a.stop_file)
    except Stop as e:
        print(f"STOP: {e}", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as e:
        # oc or kind missing, a timeout, an answer that is not what was asked for: a guard that cannot look stops the run, and says why.
        print(f"STOP: the guard could not check: {type(e).__name__}: {str(e)[:300]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
