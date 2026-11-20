#!/usr/bin/env python3
"""deploy/kind-import/import-secret.py: reads a TokenRequest token on stdin and prints the import Secret of docs/02's contract as JSON on
stdout, for `oc apply -f -` (docs/02, "How the connection reaches the hub"). Both the CRC and kind import writers use this format.
The token goes from kubectl to oc through pipes only: never an argument, a file or a log line. Prints nothing else.
Usage: kubectl create token ... | import-secret.py CLUSTER_ID API_URL CA_FILE [TLS_SERVER_NAME] [--namespace NAMESPACE] | oc apply --server-side -f -
TLS_SERVER_NAME is the import's tlsServerName (#434): the name cmapi checks the certificate against instead of API_URL's host.
A cmapi before #434 ignores the field, so the Secret works with either."""
import argparse
import base64, datetime, json, os, re, ssl, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cmapi/src"))
from cmapi.core.cluster_tokens import MIN_WINDOW, ReaderGrant, TokenPolicy


# Copied from ReaderGrant.renewal_time in cmapi/src/cmapi/core/cluster_tokens.py (source of truth); the case table tests both.
def renewal_time(grant: ReaderGrant, policy: TokenPolicy) -> float:
    lifetime = grant.expires - grant.issued
    deadline = grant.expires - policy.window(lifetime)  # Start with the wanted window before expiry.
    deadline = max(deadline, grant.issued + lifetime / 2)  # Never renew before halfway through the grant.
    deadline = min(deadline, grant.expires - MIN_WINDOW)  # Leave at least ten minutes for relists and the scan delay.
    return deadline


values = {"duration": os.environ.get("CMAPI_TOKEN_DURATION", "7d")}
try:
    if "CMAPI_TOKEN_RENEW_BEFORE" in os.environ:
        values["renewBefore"] = os.environ["CMAPI_TOKEN_RENEW_BEFORE"]
    if "CMAPI_TOKEN_RENEW_BEFORE_PERCENTAGE" in os.environ:
        values["renewBeforePercentage"] = int(os.environ["CMAPI_TOKEN_RENEW_BEFORE_PERCENTAGE"])
    policy = TokenPolicy().override(values)
except ValueError as exc:
    sys.exit(f"invalid token policy: {exc}")
if sys.argv[1:] == ["--request-duration"]:
    # kubectl and oc accept hours or seconds, but not days.
    print(f"{policy.duration // 3600}h" if policy.duration % 3600 == 0 else f"{policy.duration}s")
    sys.exit(0)

parser = argparse.ArgumentParser()
parser.add_argument("cluster_id")
parser.add_argument("api_url")
parser.add_argument("ca_file")
parser.add_argument("server_name", nargs="?")
parser.add_argument("--namespace", default="cmapi-imports")
parser.add_argument("--resource-version")
args = parser.parse_args()
cluster_id, api_url, ca_file, server_name = args.cluster_id, args.api_url, args.ca_file, args.server_name
if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,62}", cluster_id):
    sys.exit(f"cluster id {cluster_id!r} is not ^[A-Z][A-Z0-9_]{{1,62}}$ (docs/02 ClusterId)")
token = sys.stdin.read().strip()
try:
    grant = ReaderGrant.parse(token)
    grant.check_new(policy, time.time())
except ValueError as exc:
    sys.exit(str(exc))
renew_at = renewal_time(grant, policy)
expires = datetime.datetime.fromtimestamp(grant.expires, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
with open(ca_file) as source:
    ca = source.read()
try:
    ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_verify_locations(cadata=ca)
except (ssl.SSLError, ValueError):
    sys.exit("cannot load the API CA bundle")
b64 = lambda s: base64.b64encode(s.encode()).decode()
print(json.dumps({
    "apiVersion": "v1", "kind": "Secret", "type": "Opaque",
    "metadata": {
        "name": "cmapi-cluster-" + cluster_id.lower().replace("_", "-"), "namespace": args.namespace,
        **({"resourceVersion": args.resource_version} if args.resource_version else {}),
        "labels": {"cmapi.net/secret-type": "cluster", "cmapi.net/cluster-id": cluster_id, "app.kubernetes.io/part-of": "cmapi"},
        "annotations": {"cmapi.net/managed-by": "cluster-baseline", "cmapi.net/token-expires-at": expires}},
    "data": {"apiUrl": b64(api_url), "token": b64(token), "caData": b64(ca), "insecure": b64("false"),
             **({"tlsServerName": b64(server_name)} if server_name else {})}}))
rotate = datetime.datetime.fromtimestamp(renew_at, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
print(f"import Secret for {cluster_id}: the token expires {expires}; automatic renewal due {rotate}", file=sys.stderr)
