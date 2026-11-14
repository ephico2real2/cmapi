# #215: configurable metadata stanzas

OB1 run 6 (Opus 5.5 at high) wrote the code, the tests and this record on 2026-11-14. Fable reviews it later. The
change is to which labels and annotations a requester may set (validation at plan time), not to auth, tokens,
admission, secrets or deletion, so no Codex pass was required by `OB1-PROMPT.md`.

## The owner's decisions

- #215, 2026-11-14: "requiredAnnotations (stanza) and requiredLabels (stanza as well) - we want to be able to configure
  the required keys so that the requester needs to set them - and also have flexibility to configure extraAnnotations
  and extraLabels". The owner's sample namespace is `abc-rnd` with `name`, `company.net/app-environment`,
  `company.net/mnemonic`, `company.net/lob`, `company.net/cl`, two optional keys, `company.net/provisioner:
  cluster-configs`, and the annotation `company.net/app-environment`.
- #215, the owner's item 1: keep both `cmapi.net/env` (cmapi's system key) and `company.net/app-environment` (the
  company's label), and keep `company.net/app-environment` derived from the cluster's environment.
- #228: keep `company.net/provisioner: cluster-configs` in `adoptionLabels`.
- The coordinator, 2026-11-14: the sample's `name: aao-rnd` is a typo; `name` is derived from the namespace name.

## Decisions

| Question | Decision | Why |
|---|---|---|
| The shape | The issue's stanzas: `requiredLabels`, `requiredAnnotations`, `extraLabels` and `extraAnnotations` (each with `keys` and `allowOther`), `adoptionLabels` | The owner's words. A key can be a label and an annotation at once (`company.net/app-environment`), so the rules are kept for each kind |
| The old stanzas `governed` and `team` | The loader refuses them and names the new stanzas | Ignoring them would silently stop requiring `cmapi.net/team`. Every copy in the repository moves to the new stanzas in this change, with the same keys, rules and limits |
| A derived key sent by the requester | The same value is accepted; another value, or a removal, is refused with `derived_key` | A client that reads a namespace and sends its labels back must not be refused. A different value is a mistake that the requester should see, not a value cmapi drops in silence |
| What a key can derive from | `namespace`, `environment`, `cluster`, `instance`: the request's target | Each comes from the request's path and the instance, never from the body. `team` (in the issue's list) is not a value cmapi knows: it is the requester's own label, so it is not offered |
| `format: url` or `format: email-in-domains` on a label | Refused by the loader (Fable's review, F1: the email half) | A label value is at most 63 characters of `[A-Za-z0-9_.-]` (Kubernetes' syntax, the same check as `_syntax`), so it cannot hold the `://` of a URL or the `@` of an address: the key would refuse every value its own format accepts. The issue's example put `company.net/mnemonic-group-contact: {format: email-in-domains}` and `company.net/mnemonic-confluence: {format: url}` under `extraLabels`; the owner's sample has both as labels with an empty value, so the company example declares them with no format. The owner chooses: both as labels with no format (as shipped), or both as annotations with their formats |
| An empty value of an optional key | Accepted when the key has no rule; a required key that is empty counts as missing | The owner's sample has `''` for both optional keys, and an empty label value is valid in Kubernetes. The required check is the old one (`not value`) |
| An adoption label | `reserved` for a requester, whatever `allowOther` admits; the loader refuses a system or operator-only key, and a key or value that is not a valid label (Fable's review, F2) | Another tool's mark: a requester must not mark a new namespace as one that the old way made |
| The limits of `allowOther` | Each a whole number, zero or more, or the loader refuses the file (Fable's review, F4) | A negative or missing limit refused every key |
| The class names | `governed` and `team`, unchanged | The approval rules read `keyClasses: [team]` (`approval-rules.yaml` of each instance) |
| The shipped configuration | The same keys as before, in the new stanzas, and `company.net/provisioner: cluster-configs` in `adoptionLabels` | No behaviour change for the keys that exist (the issue). The owner's company keys are an example file, `metadata-keys.company.yaml`, that an organisation uses instead |
| The API document | The `labels` and `annotations` of `NamespaceCreate` and `NamespacePatch` list the configured keys and their rules; the examples of `NamespaceCreate` are the `example` of each required key that the requester sends (Fable's review, F3), so the document shows a body that this instance accepts | One source for every check (the issue's item 3). Each instance serves its own document, as it already does for its environments |

## Fable's review

Fable 5.2 reviewed head `c830276` (`fable-review.md`) and found four defects (F1 to F4) in what the new stanzas accept, each with its fix and test; the coordinator accepted all four, and they are applied unchanged (`test_metadata_review_234.py`: 9 failed before, all pass after; `test_metadata_review_234_api.py`). One question stays the owner's: the two optional company keys as labels with no format, or as annotations with their formats.

## Not built here, each with its issue

- Kyverno policies from the same stanzas, with messages from the same values: #212. The bundle's policy
  (`cmapi/policies/require-team-metadata.yaml`) still names `cmapi.net/team`, `cmapi.net/cluster-id` and
  `cmapi.net/team-dl`, which the shipped stanzas still require.
- The portal's New namespace form from the stanzas: Wave 6 (#20).
- A finding for an existing namespace that misses a new required key: the Policies tab, story #26.

## Proof

| Test | Before (main's `core/metadata.py`, `pipeline.py`, `render/manifests.py`) | After |
|---|---|---|
| `cmapi/tests/core/test_metadata_stanzas.py` (26 cases: the owner's sample renders exactly; each rule; derived keys; one problem with each key and rule; limits; a key in both kinds; adoption labels; the old stanzas refused; ten bad configurations refused; the shipped keys unchanged) | 26 failed | 26 passed |
| `cmapi/tests/service/test_metadata_stanzas_api.py` (the plan fills the derived keys from the target; a body with another derived value and a wrong prefix is refused with each key; the API document names the keys) | see the pull request | see the pull request |
| The reference suite (`examples/tests`, 175 cases before this change) | | unchanged, passed |

Measured on this Mac, no cluster (#157).
