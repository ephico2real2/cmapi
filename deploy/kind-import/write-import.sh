#!/usr/bin/env bash
# Shared by both bootstrap scripts. The caller supplies oc_ for the hub.
import_version() {
  oc_ get secret "$1" -n "$2" --ignore-not-found -o 'jsonpath={.metadata.resourceVersion}'
}

write_import() {
  local manager=$1 version=$2
  if [[ -n $version ]]; then
    # The document carries the pre-issuance resourceVersion. Force transfers field ownership.
    oc_ apply --server-side --field-manager="$manager" --force-conflicts -f -
  else
    # POST only succeeds if the name is still unused.
    oc_ create --field-manager="$manager" -f -
  fi
}
