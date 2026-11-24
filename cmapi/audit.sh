#!/usr/bin/env bash
# The dependency audit (#655): CI's dependency-audit job runs it, and anyone can run the same command.
#
#   cmapi/audit.sh [<python 3.12>]      needs the network (PyPI and api.osv.dev); exit 0 only when no set has an advisory
#
# Each installed set is checked against OSV (https://osv.dev) by pip-audit, which installs from its own hashed lock:
#   1. the image's: cmapi/requirements.txt installed with --require-hashes as the Containerfile installs it, then cmapi
#      itself with --no-deps; pip check proves that the lock still satisfies pyproject.toml's pins.
#   2. the service tests': set 1 plus cmapi[test], as CI's service job installs them.
#   3. the reference code's: examples/local/requirements.txt, as CI's reference-code job and examples/local/run.sh install it.
# Any advisory fails the run. There is no ignore list; adding one (pip-audit --ignore-vuln) is a reviewed change that says
# why the advisory cannot reach cmapi and when the entry expires.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
root=$(dirname "$here")
python=${1:-python3}
work=$(mktemp -d "${TMPDIR:-/tmp}/cmapi-audit.XXXXXX")
trap 'rm -rf "$work"' EXIT
failed=()

step() { printf '\n== %s\n' "$*"; }
venv() {    # venv <name>: a fresh virtual environment at $work/<name>
  "$python" -m venv "$work/$1" || { echo "audit.sh: $python cannot make a venv" >&2; exit 2; }
}
pip_install() {    # pip_install <python> <args...>: quiet unless it fails
  "$1" -m pip install --quiet --disable-pip-version-check "${@:2}"
}
# audit <label> <python>: pip-audit on that environment's site-packages, against OSV. With --strict a package that cannot be
# audited fails the run, so cmapi itself, which is on no index, is never in an environment when it is audited.
audit() {
  local label=$1 site
  site=$("$2" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  if "$work/tools/bin/pip-audit" --vulnerability-service osv --path "$site" --strict --aliases on --desc off \
      --progress-spinner off; then
    echo "ok: $label has no known advisory"
  else
    failed+=("$label")
  fi
}

step "pip-audit, from its hashed lock (cmapi/audit/requirements.txt)"
venv tools
pip_install "$work/tools/bin/python" --require-hashes --no-deps --only-binary :all: -r "$here/audit/requirements.txt" || exit 2
"$work/tools/bin/pip-audit" --version

step "1. The image's set: cmapi/requirements.txt with --require-hashes, then cmapi with --no-deps"
venv image
image=$work/image/bin/python
# Without --only-binary, unlike the Containerfile: cryptography has no wheel for an Intel Mac, and pip builds it there.
# CI and the image are linux/amd64, where every locked package has a wheel and pip prefers it.
pip_install "$image" --require-hashes --no-deps -r "$here/requirements.txt" || exit 2
audit "the image's set (cmapi/requirements.txt)" "$image"
if pip_install "$image" --no-deps --no-build-isolation --no-index -e "$here" && "$image" -m pip check; then
  echo "ok: the lock satisfies pyproject.toml"
else
  failed+=("pip check: cmapi/requirements.txt does not satisfy cmapi/pyproject.toml; run cmapi/lock.sh")
fi

step "2. The service tests' set: set 1 plus cmapi[test]"
pip_install "$image" -e "${here}[test]" || exit 2
"$image" -m pip uninstall --quiet --yes cmapi
audit "the service tests' set (cmapi[test])" "$image"

step "3. The reference code's set: examples/local/requirements.txt"
venv examples
examples=$work/examples/bin/python
pip_install "$examples" -r "$root/examples/local/requirements.txt" || exit 2
audit "the reference code's set (examples/local/requirements.txt)" "$examples"

if ((${#failed[@]})); then
  printf '\naudit.sh: FAILED\n' >&2
  printf '  - %s\n' "${failed[@]}" >&2
  exit 1
fi
printf '\naudit.sh: no known advisory in any set\n'
