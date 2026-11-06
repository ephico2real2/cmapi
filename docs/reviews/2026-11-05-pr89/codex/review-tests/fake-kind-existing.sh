#!/usr/bin/env bash
set -u
state=${FAKE_KIND_STATE:?}
case "$1 $2" in
  'get clusters') printf '%s\n' cmapi-test; exit 0;;
  'create cluster') exit 1;;
  'delete cluster') printf '%s\n' deleted > "$state/deleted"; exit 0;;
esac
exit 1
