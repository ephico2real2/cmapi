#!/usr/bin/env bash
set -u
state=${FAKE_STATE:?}
if [ "$1" = get ] && [ "$2" = secret ]; then
  name=$3
  shift 3
  ns=
  while [ $# -gt 0 ]; do
    case "$1" in -n) ns=$2; shift 2;; *) shift;; esac
  done
  if [ "$ns/$name" = realm/cmapi-realm-secrets ]; then
    printf '%s\n' '{"apiVersion":"v1","kind":"Secret","metadata":{"name":"cmapi-realm-secrets"},"data":{}}'
    exit 0
  fi
  exit 1
fi
if [ "$1" = get ] && [ "$2" = keycloakrealmimport ]; then exit 1; fi
if [ "$1" = apply ]; then
  n=$(cat "$state/applies")
  printf '%s\n' "$((n + 1))" > "$state/applies"
  cat >/dev/null
  exit 0
fi
exit 1
