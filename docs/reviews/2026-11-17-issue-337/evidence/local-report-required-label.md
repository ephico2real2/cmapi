## API contract report

What this change of `metadata-keys.yaml` does to the API document. Each side is rendered by `cmapi-tools openapi render` on the packaged reference instance with the `metadata-keys.yaml` that `helm template` writes into the ConfigMap, so every difference below comes from that file. oasdiff lists breaking changes as errors.

**Report only.** A change of required keys is the operator's decision (#328, question 4); it never fails this check. Generate a client for an instance from that instance's own `/openapi.json` (docs/18).

cmapi `test`.

### `deploy/environments/crc.yaml`

1 breaking (error), 0 possibly breaking (warning), 4 other changes.

# API Changelog 0.2.0 vs. 0.2.0


## API Changes

### POST /api/v1/clusters/{cluster_id}/namespaces
- :warning: added the new required request property `labels/cmapi.net/data-class`
-  added the new `cmapi.net/data-class` enum value to the request property `labels/propertyNames/anyOf[subschema #1]`


### PATCH /api/v1/clusters/{cluster_id}/namespaces/{ns}
-  added the new optional request property `labels/anyOf[subschema #1]/cmapi.net/data-class`
-  added the new `cmapi.net/data-class` enum value to the request property `labels/anyOf[subschema #1]/propertyNames/anyOf[subschema #1]`




## Info
-  a breaking change was detected but the version is still `0.2.0`

::warning file=deploy/environments/crc.yaml,title=API contract::1 breaking (error), 0 possibly breaking (warning), 4 other changes: see the job summary of this run
