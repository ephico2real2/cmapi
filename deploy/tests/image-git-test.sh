#!/usr/bin/env bash
# The cmapi image's Git layer (#286), proved in the built image under an arbitrary UID. Usage: image-git-test.sh <image> [engine]
#   1. /etc/passwd is neither group- nor other-writable. CRI-O adds the pod's UID only to such a file (cri-o utils/utils.go,
#      GeneratePasswd and checkFilePermissions), and a writable one lets any process in the container edit it (Red Hat,
#      access.redhat.com/articles/4859371). Nobody may bring that back.
#   2. git, ssh, ssh-keygen and libnss_wrapper are there.
#   3. ssh under a UID with no passwd entry fails ("No user exists for uid"), and with the Git layer's own nss_wrapper
#      environment (cmapi.core.git.transport.nss_wrapper) gets past the lookup, to the network: the fix, before and after.
# Engine: podman by default; --passwd=false keeps podman from adding the entry itself, as CRI-O off OpenShift does not.
set -euo pipefail
IMAGE=${1:?usage: image-git-test.sh <image> [engine]}
ENGINE=${2:-podman}
fails=0
ok() { echo "  ok   $*"; }
bad() { echo "  FAIL $*"; fails=$((fails + 1)); }
run() { "$ENGINE" run --rm --user 1001 --passwd=false --entrypoint "$1" "$IMAGE" "${@:2}"; }

mode=$(run stat -c %a /etc/passwd)
case "$mode" in *[2367]?|*?[2367]) bad "/etc/passwd is $mode: group or others can write it";; *) ok "/etc/passwd is $mode";; esac
for f in /usr/bin/git /usr/bin/ssh /usr/bin/ssh-keygen /usr/lib64/libnss_wrapper.so; do
  if run test -x "$f" -o -f "$f"; then ok "$f is there"; else bad "$f is missing"; fi
done

before=$(run ssh -F /dev/null -o BatchMode=yes -o ConnectTimeout=2 -p 1 127.0.0.1 true 2>&1 || true)
case "$before" in *"No user exists for uid 1001"*) ok "before: ssh under UID 1001 with no entry: $before";;
  *) bad "before: expected 'No user exists for uid 1001', got: $before";; esac

after=$(run python -c '
import os, subprocess, tempfile
from pathlib import Path
from cmapi.core.git.transport import nss_wrapper
home = Path(tempfile.mkdtemp())
env = {"PATH": os.environ["PATH"], "HOME": str(home), **nss_wrapper(home)}
p = subprocess.run(["ssh", "-F", "/dev/null", "-o", "BatchMode=yes", "-o", "ConnectTimeout=2", "-p", "1", "127.0.0.1", "true"],
                   env=env, capture_output=True, text=True)
print(p.stderr.strip())
' 2>&1 || true)
case "$after" in *"No user exists"*|"") bad "after: ssh still has no user: $after";;
  *) ok "after: ssh with the Git layer's nss_wrapper environment: $after";; esac

echo "image git cases failed: $fails"
[ "$fails" = 0 ]
