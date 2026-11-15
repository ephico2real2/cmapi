# #253: cmapi's own LimitRanges, one for each resource, and storage behind a switch

The build of the adoption design's D19 and the tier part of D8 (`docs/reviews/2026-11-14-issue-26-adoption/README.md`,
PR #239). Opus 5.5 (OB1 run 7) wrote the code, the tests and this record.

## The owner's decisions (#251, 2026-11-14)

| Time (UTC) | Decision |
|---|---|
| 15:28 | "maybe we might need to have separate limit range object names for cpu and memory in cmapi as well. This is our standard." |
| 15:34 | "We don't enforce limit ranges for storage." Replaced at 15:45. |
| 15:45 | "Why don't we keep it and turn it off in configuration." The pvc code paths stay, behind a switch. |
| 16:09 | "turn it off by default in code and then provide an override if we want to enforce storage LimitRanges." |

## What Kubernetes does with several LimitRanges

The page [Limit Ranges](https://kubernetes.io/docs/concepts/policy/limit-range/) says two things that decide the design:
- Each LimitRange is enforced: usage must "not exceed resource minimum, maximum and ratio defined in any LimitRange
  present in the namespace".
- Defaults are not merged: "If two or more LimitRange objects exist in the namespace, it is not deterministic which
  default value will be applied."

So cmapi writes one object for each resource name, and no two objects set a default for the same resource of the same
type. The test `test_no_two_objects_set_a_default_for_the_same_resource` checks it on a tier with a third container
resource.

## Decisions

**D1. The objects.** `<ns>-limits-cpu` and `<ns>-limits-memory` hold the `Container` item of one resource each. Another
container resource gets its own object, named from the resource: lower case, and each run of characters outside
`[a-z0-9.-]` becomes `-` (`nvidia.com/gpu` gives `<ns>-limits-nvidia.com-gpu`). The catalog refuses two resources that
would share one object, or a container resource named like the storage object (`_object_collisions`). `<ns>-limits-storage`
holds the `PersistentVolumeClaim` item. The order of the objects is cpu, memory, the others by name, then storage.

**D2. The switch: `storageLimitRange.enabled`, off by default in code.** `CatalogFile.storageLimitRange` defaults to
`{enabled: false}`, and `EnvDef.storageLimitRange` is `None` unless an environment sets it, so `inherit` passes the
parent's value on. No shipped file carries the key (`test_the_default_is_off_in_code_with_the_key_absent`). The value is a
pydantic `StrictBool`: a quoted `"false"` is refused at load, because a string must not be read as a boolean (#240's F3
was an unquoted `off` read as false).
- **Why not `limitRange.storage.enabled`.** In `tiers.yaml`, a key under `limitRange.` is a value key of the form
  `limitRange.<kind>.<part>.<resource>` (`limit_key_parts`). `overridable`, the bounds and the approval facts use it. A
  switch spelled the same way looks like a value key. The coordinator was told, and a rename is cheap if the owner wants
  the other spelling.

**D3. Switch off.** The tiers' `pvc` values are still checked at load, so turning the switch on needs no other edit.
They are not rendered: `ResolvedTier.limit_range` holds what render() writes. A new custom `limitRange.pvc.*` value is
refused with 422 `policy-violation` and the item code `storage-limits-off`, with the keys and the environment, as every
tier refusal is (the TierError handler in `main.py`). A pvc value that Git holds (approved while the switch was on) is
dropped, not refused, so a label change still goes through; that plan removes `<ns>-limits-storage`. The generated
policies have no storage rule. `GET /api/v1/tiers` gives `storageLimitRange.enabled` for each environment.

**D4. The tier hash** is over what render() writes, so turning the switch on or off changes the hash of each tier, and a
change of a pvc value with the switch off changes nothing. Each object carries the hash.

**D5. One file for each object** (the design's D8): `resourcequota-<name>.yaml` and `limitrange-<name>.yaml`, or
`<kind>-<sha256 of the name>.yaml` when the name is longer than 255 bytes allow. The readers find objects by kind:
`objects_of` in `core/render/manifests.py`, used by `core/pipeline.py` (`_tier_quota`, the approved overrides from every
LimitRange), `core/sync.py` (each planned ResourceQuota) and `core/validate` (a file is checked by the kind it holds; a
file of a checked kind holds one document). A folder of the old layout is read, and its next change removes
`resourcequota.yaml` and `limitrange.yaml` and writes the named files in the same commit. An object whose content did not
change keeps the request ID that Git holds, wherever its file was.

**D6. The ratchet across the split.** At plan time the validator drops a failure on a key whose value the previous
version of the object held (#212). The previous version is now the object of the same kind and name, from any file. A
LimitRange split out of the old `<ns>-limits` has a new name, so for a limit key its previous version is the one previous
LimitRange that held the key. Two previous holders give none, so nothing is held on a guess
(`test_a_value_that_git_held_before_the_split_stays_held`).

**D7. No migration on a cluster.** Nothing of cmapi runs on a cluster yet (#157). The example folder `payments-dev`, the
tests, docs/02, docs/04 and the recorded samples change. The sample of a custom dry run no longer sends a pvc value,
because the instances refuse one.

## Not measured

That a pod with no resources gets its CPU default from `<ns>-limits-cpu` and its memory default from
`<ns>-limits-memory` on a real API server. It needs a cluster: the CRC run after this PR shows it.

## Tests

| Test | Before (old code) | After |
|---|---|---|
| `tests/core/test_limitrange_split.py`, 23 tests | Fails at import: `object_file` does not exist | 23 passed |
| The changed core tests (`test_tiers`, `test_policygen`, `test_render_listquery_config`, `test_review_212`) | See `logs` below | All pass |
| `tests/service/test_storage_limits_switch.py`, 5 tests | Run below | Run below |

The runs and their logs are in the PR body.
