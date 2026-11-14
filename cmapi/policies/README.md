# Hand-written Kyverno policies

cmapi renders its own Kyverno bundle from the instance's configuration (`core/policygen.py`, #212): the metadata
keys of `metadata-keys.yaml`, the bounds of `tiers.yaml`, and `deny-expiry-in-prod`. The image therefore ships no
policy here.

An organisation can add its own `policies.kyverno.io/v1` policies to this folder (`/etc/cmapi/policies`, the
setting `CMAPI_POLICIES_DIR`). The validator runs them at plan time with the rendered bundle. A policy under `env/<env>/`
runs only for `<env>`. Give each one a test, as the rendered policies have, because the validator refuses a policy that
gives no result for a file it matches.
