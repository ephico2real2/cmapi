#!/usr/bin/env bash
# The dependency audit (#655): CI's dependency-audit job runs it, and anyone can run the same command.
#
#   cmapi/audit.sh [<python 3.12>]      needs the network (PyPI and api.osv.dev); exit 0 only when every set was audited
#                                       and none has an advisory
#
# Exit 1: a set has an advisory, or the lock does not satisfy pyproject.toml. Exit 3: pip-audit gave no answer for a set
# after three attempts (OSV or the network failed), so that set was not audited; run it again. Exit 2: a set could not be
# installed.
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
unaudited=()
# The image is linux/amd64, where every locked package has a wheel (the Containerfile's --only-binary :all:), and CI is
# too, so set 1 installs there as the image does. Elsewhere pip may build: cryptography has no wheel for an Intel Mac.
# pip install --only-binary: ":all:" to disable all source packages, ":none:" to empty the set.
binary=:none:
[[ $(uname -s) == Linux ]] && binary=:all:

step() { printf '\n== %s\n' "$*"; }
venv() {    # venv <name>: a fresh virtual environment at $work/<name>
  "$python" -m venv "$work/$1" || { echo "audit.sh: $python cannot make a venv" >&2; exit 2; }
}
pip_install() {    # pip_install <python> <args...>: quiet unless it fails
  "$1" -m pip install --quiet --disable-pip-version-check "${@:2}"
}
# audit <label> <python>: that environment's site-packages against OSV, by audit/osv_audit.py, which says why it reads
# pip-audit's report and not its exit code. cmapi itself is on no index, so it is never in an environment when it is audited.
audit() {
  local label=$1 site rc
  site=$("$2" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  "$work/tools/bin/python" "$here/audit/osv_audit.py" "$site"
  rc=$?
  case $rc in
    0) echo "ok: $label has no known advisory" ;;
    1) failed+=("$label") ;;
    *) unaudited+=("$label (osv_audit.py exit $rc)") ;;
  esac
}

step "pip-audit, from its hashed lock (cmapi/audit/requirements.txt)"
venv tools
pip_install "$work/tools/bin/python" --require-hashes --no-deps --only-binary :all: -r "$here/audit/requirements.txt" || exit 2
"$work/tools/bin/pip-audit" --version

step "1. The image's set: cmapi/requirements.txt with --require-hashes, then cmapi with --no-deps"
venv image
image=$work/image/bin/python
pip_install "$image" --require-hashes --no-deps --only-binary "$binary" -r "$here/requirements.txt" || exit 2
audit "the image's set (cmapi/requirements.txt)" "$image"
# cmapi is installed from a copy of its source: an install from the checkout leaves src/cmapi.egg-info in it.
mkdir "$work/cmapi" && cp -R "$here/pyproject.toml" "$here/src" "$work/cmapi/" || exit 2
if pip_install "$image" --no-deps --no-build-isolation --no-index "$work/cmapi" && "$image" -m pip check; then
  echo "ok: the lock satisfies pyproject.toml"
else
  failed+=("pip check: cmapi/requirements.txt does not satisfy cmapi/pyproject.toml; run cmapi/lock.sh")
fi

step "2. The service tests' set: set 1 plus cmapi[test]"
pip_install "$image" "$work/cmapi[test]" || exit 2
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
fi
if ((${#unaudited[@]})); then
  printf '\naudit.sh: NOT AUDITED: pip-audit gave no answer (its error is above) for these sets. Run it again.\n' >&2
  printf '  - %s\n' "${unaudited[@]}" >&2
fi
((${#failed[@]})) && exit 1
((${#unaudited[@]})) && exit 3
printf '\naudit.sh: no known advisory in any set\n'
