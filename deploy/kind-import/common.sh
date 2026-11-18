#!/usr/bin/env bash
# deploy/kind-import/common.sh: sourced by up.sh and down.sh, never run. The names, the address of kind-cmapi-test.yaml, and the checks
# both scripts make before they touch anything. Every kubectl call names --kubeconfig; every oc call goes to CRC, which check_hub proves.
# shellcheck disable=SC2034  # the names are read by up.sh and down.sh, which source this file
# Executable like every script under deploy/ (#86), but run by itself it would only define names: say so and stop.
[[ ${BASH_SOURCE[0]} != "$0" ]] || { echo "deploy/kind-import/common.sh is sourced by up.sh and down.sh; run one of those" >&2; exit 2; }
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CONFIG=$HERE/kind-cmapi-test.yaml
PF_CONF=$HERE/pf-cmapi-kind.conf
NAME=cmapi-test
CLUSTER_ID=KIND_CMAPI_TEST
SECRET=cmapi-cluster-kind-cmapi-test
HUB_NS=cmapi-imports
HUB_SERVER=https://api.crc.testing:6443
FIELD_MANAGER=cmapi-baseline
export KIND_EXPERIMENTAL_PROVIDER=podman
# kind-test.sh's default file: the two never run together, since each refuses or deletes the other's cluster by name first.
KC=${KIND_IMPORT_KUBECONFIG:-$HERE/../../.cmapi-test.kubeconfig}
OC=${CMAPI_OC:-oc}
ADDRESS=$(awk '$1 == "apiServerAddress:" {print $2}' "$CONFIG")
PORT=$(awk '$1 == "apiServerPort:" {print $2}' "$CONFIG")

die() { echo "ERROR: $*" >&2; exit 1; }
say() { echo "kind-import: $*"; }
# shellcheck disable=SC2086  # CMAPI_OC may carry --kubeconfig
oc_() { $OC "$@"; }
kc() { kubectl --kubeconfig="$KC" "$@"; }

# kind-cmapi-test.yaml names one address three times (the binding, the certificate, the firewall): one value, or nothing runs.
check_config() {
  [[ $ADDRESS =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || die "no IPv4 apiServerAddress in $CONFIG"
  [[ $PORT =~ ^[0-9]+$ ]] || die "no apiServerPort in $CONFIG"
  local sans; sans=$(awk '$1 == "certSANs:"' "$CONFIG")
  case "$sans" in *" $ADDRESS,"*|*" $ADDRESS]"*) ;; *) die "certSANs in $CONFIG do not name apiServerAddress $ADDRESS";; esac
  case "$sans" in *"host.crc.testing"*) ;; *) die "certSANs in $CONFIG do not name host.crc.testing";; esac
  grep -qE "^block .* to $ADDRESS port $PORT\$" "$PF_CONF" || die "$PF_CONF does not drop the LAN's traffic to $ADDRESS port $PORT"
}

# The Mac must still hold the address: a DHCP lease that moved breaks the port binding and the certificate at once.
address_held() { ifconfig -a | grep -qE "^[[:space:]]*inet $ADDRESS "; }
moved() {
  echo "ERROR: this Mac no longer holds $ADDRESS, the address in $CONFIG: the DHCP lease has moved. cmapi-test's API port and its" >&2
  echo "certificate both name the old address, so CRC cannot verify it. Delete it ($HERE/down.sh --stale), put the new address in" >&2
  echo "kind-cmapi-test.yaml (apiServerAddress and certSANs) and pf-cmapi-kind.conf, reload the pf anchor, then run up.sh (docs/13, \"A second cluster: kind\")." >&2
  exit 1
}

# The certificate the API server serves names the address and host.crc.testing; CRC verifies it against the first.
check_served() {
  local sans
  sans=$(openssl s_client -connect "$ADDRESS:$PORT" -servername host.crc.testing </dev/null 2>/dev/null | openssl x509 -noout -ext subjectAltName 2>/dev/null) ||
    die "no certificate from $ADDRESS:$PORT: is cmapi-test running?"
  # Whole names only: 192.168.86.11 must not pass on a certificate for 192.168.86.110.
  local names; names=",$(echo "$sans" | tail -n +2 | tr -d ' \n'),"
  case "$names" in *",IPAddress:$ADDRESS,"*) ;; *) die "the certificate $ADDRESS:$PORT serves does not name $ADDRESS (it names ${names//,/ }). Recreate the cluster: $HERE/down.sh --stale, then $HERE/up.sh";; esac
  case "$names" in *",DNS:host.crc.testing,"*) ;; *) die "the certificate $ADDRESS:$PORT serves does not name host.crc.testing: this is not the cluster up.sh makes";; esac
}

# The import Secret goes to the hub: oc must be CRC's, never whatever context the shell happens to have.
check_hub() {
  local server; server=$(oc_ whoami --show-server) || die "oc is not logged in"
  [ "$server" = "$HUB_SERVER" ] || die "oc talks to $server, not CRC ($HUB_SERVER)"
}

# A name taken is a cluster; not "| grep -q" in an if: under pipefail an early match can read as none (kind-test.sh).
cluster_exists() {
  local clusters; clusters=$(kind get clusters 2>/dev/null) || die "kind get clusters failed"
  case $'\n'"$clusters"$'\n' in *$'\n'"$NAME"$'\n'*) return 0;; esac
  return 1
}
