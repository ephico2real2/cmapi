#!/usr/bin/env bash
# The kubectl command deploy/secrets-test.sh is given when no cluster is: the stub, run by the Python that has PyYAML.
exec "$STUB_PY" "$STUB_KUBECTL" "$@"
