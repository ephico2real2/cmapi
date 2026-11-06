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
  case "$ns/$name" in
    app/cmapi-keycloak)
      printf '%s\n' '{"data":{"realmAdminClientSecret":"QQ==","directoryClientSecret":"QQ==","svcPaymentsCiSecret":"QQ==","automationClientSecret":"QQ=="}}';;
    realm/cmapi-realm-secrets)
      printf '%s\n' '{"data":{"CMAPI_REALM_ADMIN_SECRET":"QQ==","CMAPI_DIRECTORY_SECRET":"QQ==","CMAPI_SVC_PAYMENTS_CI_SECRET":"QQ==","CMAPI_AUTOMATION_SECRET":"QQ=="}}';;
    app/cmapi-keys)
      printf '%s\n' '{"data":{"linkKey":"QQ==","cursorKey":"QQ=="}}';;
    app/cmapi-github-app)
      printf '%s\n' 'simulated API read failure' >&2
      exit 7;;
    *) exit 0;;
  esac
  exit 0
fi
if [ "$1" = apply ]; then
  n=$(cat "$state/applies")
  printf '%s\n' "$((n + 1))" > "$state/applies"
  cat >/dev/null
  exit 0
fi
exit 1
