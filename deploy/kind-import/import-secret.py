#!/usr/bin/env python3
"""deploy/kind-import/import-secret.py: reads a TokenRequest token on stdin and prints the import Secret of docs/02's contract as JSON on
stdout, for `oc apply -f -` (docs/02, "How the connection reaches the hub"). Both the CRC and kind import writers use this format.
The token goes from kubectl to oc through pipes only: never an argument, a file or a log line. Prints nothing else.
Usage: kubectl create token ... | import-secret.py CLUSTER_ID API_URL CA_FILE [TLS_SERVER_NAME] [--namespace NAMESPACE] | oc apply --server-side -f -
TLS_SERVER_NAME is the import's tlsServerName (#434): the name cmapi checks the certificate against instead of API_URL's host.
A cmapi before #434 ignores the field, so the Secret works with either."""
import argparse
import base64, datetime, json, re, sys, time

parser = argparse.ArgumentParser()
parser.add_argument("cluster_id")
parser.add_argument("api_url")
parser.add_argument("ca_file")
parser.add_argument("server_name", nargs="?")
parser.add_argument("--namespace", default="cmapi-imports")
args = parser.parse_args()
cluster_id, api_url, ca_file, server_name = args.cluster_id, args.api_url, args.ca_file, args.server_name
if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,62}", cluster_id):
    sys.exit(f"cluster id {cluster_id!r} is not ^[A-Z][A-Z0-9_]{{1,62}}$ (docs/02 ClusterId)")
token = sys.stdin.read().strip()
if token.count(".") != 2:
    sys.exit("stdin is not a JWT")
payload = token.split(".")[1]
claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
if claims.get("sub") != "system:serviceaccount:cmapi-system:cmapi-reader":
    sys.exit(f"token subject is {claims.get('sub')!r}, not cmapi-system:cmapi-reader")
if not 0 < claims["exp"] - claims["iat"] <= 7 * 24 * 3600:
    sys.exit("reader token lifetime must be positive and at most seven days")
renew_at = claims["iat"] + 0.8 * (claims["exp"] - claims["iat"])
if time.time() >= renew_at:
    sys.exit("reader token has already reached its renewal deadline")
expires = datetime.datetime.fromtimestamp(claims["exp"], datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
ca = open(ca_file).read()
b64 = lambda s: base64.b64encode(s.encode()).decode()
print(json.dumps({
    "apiVersion": "v1", "kind": "Secret", "type": "Opaque",
    "metadata": {
        "name": "cmapi-cluster-" + cluster_id.lower().replace("_", "-"), "namespace": args.namespace,
        "labels": {"cmapi.net/secret-type": "cluster", "cmapi.net/cluster-id": cluster_id, "app.kubernetes.io/part-of": "cmapi"},
        "annotations": {"cmapi.net/managed-by": "cluster-baseline", "cmapi.net/token-expires-at": expires}},
    "data": {"apiUrl": b64(api_url), "token": b64(token), "caData": b64(ca), "insecure": b64("false"),
             **({"tlsServerName": b64(server_name)} if server_name else {})}}))
rotate = datetime.datetime.fromtimestamp(renew_at, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
print(f"import Secret for {cluster_id}: the token expires {expires}; rerun the import writer by {rotate}, 80% of its life", file=sys.stderr)
