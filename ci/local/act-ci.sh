#!/bin/bash
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0. If a copy of the MPL was not
# distributed with this file, You can obtain one at https://mozilla.org/MPL/2.0/.
# Run the jobs of one GitHub Actions workflow locally with act under Podman (or any Docker API engine).
#
# Rules that came from measured failures (gotchas.md):
#   - always -W <workflow> and -j <job>: a bare `act` runs every push workflow, deploys included (G4);
#   - --container-daemon-socket -: the macOS socket path does not exist in the Podman VM (G1);
#   - each matrix entry runs alone: act starts the entries together, and two services on one host port
#     collide with "proxy already running" (G8);
#   - --rm and a cleanup before and after: a failed job keeps its containers, and its services keep their
#     host ports, so the next job fails for a reason that is not its own (G11);
#   - each run runs a copy of the workflow named <run id>-<name>: act names containers after the workflow and
#     job names only, so two runs of workflows with the same name remove each other's containers (G13, #53);
#   - each runs-on label of the workflow maps to the runner image, and exit 0 counts only with act's "Job succeeded":
#     act skips a job whose label has no -P and still exits 0, which read as a pass (G14);
#   - a job that installs gitleaks runs the same gitleaks release natively for the host CPU, because the
#     x64 Go binary crashes under qemu-user emulation in the Podman VM (G7).
set -uo pipefail

usage() {
  cat >&2 <<'EOF'
usage: act-ci.sh -r <clone> -b <base sha> [-w <workflow>] [-j "<job> <job>"] [-i <image>] [-o <log dir>] [-t <seconds>] [-d]
  -r  a clone of the branch to test (not your working repository)
  -b  the base commit of the pull request; the secret scan reads base..HEAD
  -w  the workflow file, relative to the clone (default .github/workflows/ci.yml)
  -j  the job ids to run (default: every job of the workflow)
  -i  the local runner image (default act-runner:ubuntu-24.04, built from Dockerfile.runner)
  -o  the log folder (default <clone>/../act-logs)
  -t  the limit for each act call, in seconds (default 2400)
  -d  allow a working tree with changes (act runs the tree; the secret scan reads only commits)
EOF
  exit 2
}

repo='' base='' workflow=.github/workflows/ci.yml jobs='' image=act-runner:ubuntu-24.04 logs='' limit=2400 dirty=0
while getopts r:b:w:j:i:o:t:d opt; do
  case $opt in
    r) repo=$OPTARG ;; b) base=$OPTARG ;; w) workflow=$OPTARG ;; j) jobs=$OPTARG ;;
    i) image=$OPTARG ;; o) logs=$OPTARG ;; t) limit=$OPTARG ;; d) dirty=1 ;; *) usage ;;
  esac
done
[[ -n $repo && -n $base ]] || usage

fail() { echo "act-ci: $*" >&2; exit 2; }
for tool in act yq gh git podman perl; do command -v "$tool" >/dev/null || fail "$tool is not installed"; done
repo=$(cd "$repo" && pwd) || fail "no clone at $repo"
[[ -f $repo/$workflow ]] || fail "no workflow $workflow in $repo"
if [[ -z ${DOCKER_HOST:-} && ! -S /var/run/docker.sock ]]; then
  fail "no container socket: set DOCKER_HOST, or restore /var/run/docker.sock (sudo podman-mac-helper install)"
fi
podman image exists "$image" || fail "no local image $image: build it from Dockerfile.runner"
git -C "$repo" cat-file -e "$base^{commit}" 2>/dev/null || fail "base $base is not a commit in $repo"
if [[ $dirty -eq 0 && -n $(git -C "$repo" status --porcelain) ]]; then
  fail "the working tree of $repo has changes; commit them, or pass -d"
fi

head=$(git -C "$repo" rev-parse HEAD)
base=$(git -C "$repo" rev-parse "$base")
logs=${logs:-$(dirname "$repo")/act-logs}
mkdir -p "$logs"
status=$logs/status.txt
: > "$status"

case $(uname -m) in
  arm64 | aarch64) arch=linux/arm64 gl_cpu=arm64 ;;
  x86_64) arch=linux/amd64 gl_cpu=x64 ;;
  *) fail "unknown CPU $(uname -m)" ;;
esac
gl_os=$(uname -s | tr '[:upper:]' '[:lower:]')

# act names its containers, networks and volumes act-<workflow name>-<job>-<hash of both>, so two runs of workflows
# with the same name share those names: one run removes the containers of the other (#53). Each run gives a copy of
# the workflow a name that starts with its own run id, runs that copy, and cleans up only act-<run id>-*.
name=$(yq -r '.name // ""' "$repo/$workflow")
[[ -n $name ]] || fail "$workflow has no name: act names its containers after it, and the cleanup needs it"
run_id=r$(date -u +%y%m%d%H%M%S)p$$
prefix="act-$run_id-"
run_workflow=$logs/workflow-$run_id.yml
yq ".name = \"$run_id-\" + .name" "$repo/$workflow" > "$run_workflow" || fail "cannot write $run_workflow"
clean() {
  local kind
  podman ps -a --format '{{.Names}}' | grep "^$prefix" | xargs -r podman rm -f >/dev/null
  for kind in network volume; do
    podman "$kind" ls --format '{{.Name}}' | grep "^$prefix" | xargs -r podman "$kind" rm >/dev/null
  done
}
trap clean EXIT

event=$logs/event.json
printf '{"pull_request":{"number":0,"base":{"sha":"%s"},"head":{"sha":"%s"}}}\n' "$base" "$head" > "$event"

record() { echo "$1 $2 $(date -u +%H:%M:%S)" >> "$status"; }

# act runs a job only when a -P names its runs-on label. With no -P for the label it skips the job and exits 0 (G14). So each
# plain label of the workflow maps to the runner image. A label that is an expression cannot be mapped here: act skips that job,
# and run_act records the skip as a failure.
platforms=(-P "ubuntu-latest=$image")
while IFS= read -r label; do
  [[ -z $label || $label == ubuntu-latest || $label == *\$\{\{* ]] || platforms+=(-P "$label=$image")
done < <({ yq -r '.jobs[]."runs-on" | select(tag == "!!str")' "$repo/$workflow"
           yq -r '.jobs[]."runs-on" | select(tag == "!!seq") | .[]' "$repo/$workflow"; } | sort -u)

run_act() { # tag, job, extra act arguments
  local tag=$1 job=$2 code result
  shift 2
  clean
  record "$tag" start
  GITHUB_TOKEN=$(gh auth token) perl -e 'alarm shift; exec @ARGV' "$limit" \
    act pull_request -W "$run_workflow" -j "$job" -e "$event" "${platforms[@]}" --pull=false \
    --container-architecture "$arch" --container-daemon-socket - --rm -s GITHUB_TOKEN "$@" \
    > "$logs/$tag.log" 2>&1
  code=$?
  # perl's alarm ends act with SIGALRM, which the shell reports as 142.
  if [[ $code -eq 142 ]]; then result="timeout after ${limit}s"; else result="exit=$code"; fi
  # Exit 0 is a pass only when act says that a job succeeded. A job that act skipped, or a call that ran no job, is not a pass (G14).
  if [[ $code -eq 0 ]]; then
    if grep -q 'Skipping unsupported platform' "$logs/$tag.log"; then
      result="exit=3 act skipped the job: its runs-on label has no runner image"
    elif ! grep -q 'Job succeeded' "$logs/$tag.log"; then
      result="exit=3 act exited 0 but no job succeeded"
    fi
  fi
  record "$tag" "$result"
}

scan_native() { # tag, job
  local tag=$1 job=$2 version pin cache asset code
  record "$tag" start
  version=$(yq -r ".jobs.\"$job\"" "$repo/$workflow" | grep -oE 'gitleaks_[0-9.]+_linux_x64' | head -1 | sed -E 's/gitleaks_([0-9.]+)_linux_x64/\1/')
  pin=$(yq -r ".jobs.\"$job\".steps[].env.GITLEAKS_SHA256 // \"\"" "$repo/$workflow" | grep -v '^$' | head -1)
  [[ -n $version && -n $pin ]] || { record "$tag" "exit=2 no gitleaks version or checksum pin in the job"; return; }
  cache=$logs/gitleaks-$version
  asset=gitleaks_${version}_${gl_os}_${gl_cpu}.tar.gz
  mkdir -p "$cache/bin"
  gh release download "v$version" -R gitleaks/gitleaks -D "$cache" --clobber \
    -p "gitleaks_${version}_checksums.txt" -p "$asset" >/dev/null 2>&1 \
    || { record "$tag" "exit=2 download of gitleaks $version failed"; return; }
  # The pin in the workflow must be the x64 entry of the same checksum file, so the native binary is the same release.
  grep -q "^$pin  gitleaks_${version}_linux_x64.tar.gz$" "$cache/gitleaks_${version}_checksums.txt" \
    || { record "$tag" "exit=2 the workflow pin is not in the release checksum file"; return; }
  (cd "$cache" && grep "  $asset$" "gitleaks_${version}_checksums.txt" | shasum -a 256 -c - >/dev/null) \
    || { record "$tag" "exit=2 checksum of $asset failed"; return; }
  tar -xzf "$cache/$asset" -C "$cache/bin" gitleaks
  (cd "$repo" && "$cache/bin/gitleaks" git --no-banner --redact --log-opts="$base..$head" .) > "$logs/$tag.log" 2>&1
  code=$?
  record "$tag" "exit=$code commits=$(git -C "$repo" rev-list --count --no-merges "$base..$head") native gitleaks $version $gl_os/$gl_cpu"
}

[[ -n $jobs ]] || jobs=$(yq -r '.jobs | keys | .[]' "$repo/$workflow" | tr '\n' ' ')
cd "$repo" || exit 2
for job in $jobs; do
  yq -e ".jobs.\"$job\"" "$workflow" >/dev/null 2>&1 || { record "$job" "exit=2 no such job"; continue; }
  # Read all the run lines first: `yq | grep -q` under pipefail fails when grep exits before yq has written them all.
  runs=$(yq -r ".jobs.\"$job\".steps[].run // \"\"" "$workflow")
  if grep -q 'gitleaks' <<<"$runs"; then
    scan_native "$job" "$job"
    continue
  fi
  entries=$(yq -r ".jobs.\"$job\".strategy.matrix.include // [] | length" "$workflow")
  if [[ $entries -eq 0 ]]; then
    run_act "$job" "$job"
    continue
  fi
  for ((n = 0; n < entries; n++)); do
    # Select the entry by its keys whose values hold no ':' (act splits --matrix on the first ':').
    args=() label=''
    while IFS= read -r pair; do
      args+=(--matrix "$pair") label+="-${pair#*:}"
    done < <(yq -r ".jobs.\"$job\".strategy.matrix.include[$n] | to_entries | .[] | select((.value | tostring) | test(\":\") | not) | .key + \":\" + (.value | tostring)" "$workflow")
    run_act "$job$label" "$job" "${args[@]}"
  done
done

cat "$status"
! grep -qvE ' start | exit=0 ' "$status"
