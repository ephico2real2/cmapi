#!/bin/bash
# The measurements of #708, as they were run (2026-11-26, a 4-CPU x86_64 podman machine on macOS).
# $1 is a folder that holds: dl/kyverno and dl/kubeconform (the image's pinned releases, SHA-256 checked as cmapi/Containerfile
# does), pol/env/dev/*.yaml (`cmapi-tools policies render` of the CRC config, dev only), res/*.yaml (the rendered folder of
# cmap-z39-dev), and scripts/measure.py (this folder's).
set -euo pipefail
M=$1
IMG=registry.access.redhat.com/ubi9/python-312-minimal@sha256:b99faaadaf10de740d60c713a047088df2f46ebdd766e9c6a0957896f44d0ea1
OPTS=()
run() { podman run --rm "${OPTS[@]}" -v "$M:/m:ro,Z" --entrypoint python3 "$IMG" /m/scripts/measure.py "$@"; }
# results.jsonl: no CPU or memory limit
for spec in "kyverno 1" "kyverno 1" "kyverno 1" "kyverno 1" "kyverno 1" "kubeconform 1" "kubeconform 1" \
            "kyverno 2" "kyverno 4" "kyverno 12"; do
  read -r tool n <<<"$spec"
  run "$tool" "$n"
done
# results-cpu1.jsonl: the API container's limits, cpu 1 and memory 512Mi
for e in X=1 X=1 X=1 GOGC=50 GOMEMLIMIT=96MiB; do
  OPTS=(--cpus=1 --memory=512m -e "$e")
  run kyverno 1
done
OPTS=(--cpus=1 --memory=512m)
run kyverno 2
