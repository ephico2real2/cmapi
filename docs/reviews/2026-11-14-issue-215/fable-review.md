# Fable review of PR #234 (#215, configurable metadata)

Reviewer: Fable 5.2. Author of the PR: Opus 5.5 (OB1 run 6). Head `c830276`, base `962d7f8`. Date: 2026-11-14.
Everything below was measured on this Mac, with no cluster. The pytest runs went through
`/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run5/tools/suite.sh`, one at a time.

## Verdict: changes needed

Four findings, each with its fix and a test that fails on `c830276` and passes with the fix. None is in the shipped
behaviour of the keys that exist today: the five shipped copies keep their rules (check 2), and the owner's sample
renders as specified (check 1). The findings are in what the new stanzas accept.

| # | Severity | Finding |
|---|---|---|
| F1 | Medium | The loader accepts `format: email-in-domains` on a label. The key then refuses every address and the empty value. The owner's spec has exactly this key |
| F2 | Medium | "A requester cannot set an adoption label" holds only because of the prefixes of the shipped files. Nothing in the code enforces it |
| F3 | Medium | The API document's examples of `labels` and `annotations` are still the model's fixed ones, not from the file. With the company file, the example is one that the instance refuses |
| F4 | Low | `allowOther` limits are not validated: `max: -1` and `maxValueBytes: null` load, and then refuse every key |

One decision is for the owner (check 1): the spec puts two formats on labels that a label cannot hold.

The fix for all four is one diff, `/Users/olasumbo/gitRepos/workbench/cmapi/fable-review/pr-234-files/fix.diff`
(`git apply --check` passes on `c830276`), applied in the worktree
`/Users/olasumbo/gitRepos/workbench/cmapi/fable-review/wt-234-fix`. It changes no generated file: the contract test
passes on the fix without a regeneration.

| Run (log in `pr-234-files/`) | `c830276` | `c830276` + fix |
|---|---|---|
| `tests/core/test_metadata_review_234.py` (11 cases) | 9 failed, 2 passed (`before-review-core.log`) | passed, with the PR's 26: 37 passed (`after-review-core.log`) |
| `tests/service/test_metadata_review_234_api.py` (2 cases) | 1 failed, 1 passed (`before-review-api-2.log`) | passed, with the PR's 3: 5 passed (`after-review-api-2.log`) |
| `tests/service` | 823 passed (`head-full-service.log`) | 825 passed (`fix-full-service.log`) |
| `tests/core` | 201 passed (`head-full-core.log`) | 212 passed (`fix-full-core.log`) |

The 2 cases that pass before are controls: an email format on an annotation still works, and the shipped copies load.
The 1 API case that passes before is evidence for check 3 (`cl: 1`), not a finding.

## Check 1: the spec, rule by rule

Command: `python pr-234-files/probe.py wt-234` (the script is in `pr-234-files/`). The owner's sample `abc-rnd`,
through `validate` and the renderer, with the requester sending only `mnemonic`, `lob`, `cl` and the two optional keys
as `''`:

```yaml
labels:
  cmapi.net/cluster-id: OCP_GF15
  cmapi.net/env: rnd
  cmapi.net/managed: 'true'
  cmapi.net/requested-by-user: ola
  cmapi.net/tier: small
  company.net/app-environment: rnd
  company.net/cl: '1'
  company.net/lob: amgsst
  company.net/mnemonic: abc
  company.net/mnemonic-confluence: ''
  company.net/mnemonic-group-contact: ''
  name: abc-rnd
annotations:
  argocd.argoproj.io/sync-options: Prune=confirm,ServerSideApply=true
  cmapi.net/instance: nonprod
  cmapi.net/request-id: req-1
  cmapi.net/requested-by: ola@company.net
  company.net/app-environment: rnd
```

The same through the API on the fakes (`test_metadata_stanzas_api.py`, namespace `abc-dev` on CRC): 3 passed.

| Spec | Result |
|---|---|
| `name: {value: {from: namespace}}` | Confirmed: `name: abc-rnd`; `name: aao-rnd` in the body is refused with `derived_key` |
| `company.net/app-environment` from the environment, label and annotation | Confirmed, both kinds; `cmapi.net/env` stays beside it (the owner's item 1) |
| `company.net/mnemonic: {pattern, namespacePrefix}` | Confirmed: `abcd` refused by the pattern, `xyz` refused with "abc-rnd does not start with xyz-" |
| `company.net/lob` and `company.net/cl` enums | Confirmed: `retail` and `7` refused, each with its list |
| `allowOther: {prefixes: ["", "*.company.net/"], max: 50}` | Confirmed: 50 other keys pass, 51 give `too_many_keys`; `other.example/x` gives `invalid_key` |
| `adoptionLabels` | Loaded as `{"company.net/provisioner": ("cluster-configs",)}`. Nothing reads it yet (story #26). See F2 |
| Three instances | Confirmed: `examples/instances/` is not in the diff |
| `value.from: team` (in the issue's list) | Not offered; `instance` is. Recorded in the decision record with its reason |
| `extraLabels.keys.company.net/mnemonic-confluence: {format: url}` | **Departure, recorded, and the reason is right** |
| `extraLabels.keys.company.net/mnemonic-group-contact: {format: email-in-domains}` | **Departure, recorded only in a YAML comment, and not enforced: F1** |

**`format: url` on a label.** The owner's spec, loaded verbatim, is refused:

```
1a owner's spec verbatim (url + email on labels): REFUSED ValueError: invalid metadata-keys.yaml:
   extraLabels.company.net/mnemonic-confluence: format url is for annotations only; a label value cannot hold a URL
```

The reason is right. A Kubernetes label value is 63 characters or fewer, empty or starting and ending with
`[a-zA-Z0-9]`, with only `-`, `_`, `.` and alphanumerics between (kubernetes.io, "Labels and Selectors", "Syntax and
character set"). So it cannot hold `:` or `/`, and it cannot hold `@` either. This is from the Kubernetes document and
from cmapi's own `_NAME` check, which is the same rule. I did not measure it on a cluster: no `cmapi-test` kind
cluster exists on this Mac, and I did not use the shared ones.

The PR records the URL half in `docs/reviews/2026-11-14-issue-215/README.md:27` and in docs/02. The company example
keeps both keys as labels with no format (`metadata-keys.company.yaml:33-35`), which matches the owner's sample
(both are labels with `''`).

**What the spec should say, for the owner to decide.** Either of these is consistent; the spec as written is not:

```yaml
# A. Keep the two keys as labels, as in the sample namespace, with no format (what the PR ships):
extraLabels:
  keys:
    company.net/mnemonic-group-contact: {}
    company.net/mnemonic-confluence:    {}
# B. Hold the address and the URL where they fit, in annotations, with their formats:
extraAnnotations:
  keys:
    company.net/mnemonic-group-contact: { format: email-in-domains }
    company.net/mnemonic-confluence:    { format: url }
```

The decision record should name the email half too, and say that the choice between A and B is the owner's.

## Check 2: behaviour preservation of the shipped copies

Command: `python pr-234-files/copies.py /Users/olasumbo/gitRepos/cmapi-design 962d7f8 c830276`. It loads each copy at
both revisions and compares, key by key: kind, required, pattern, format; the prefixes and the four limits; `system`,
`operatorOnly`, `reservedPrefixes`, `sensitiveKeys`, `emailDomains`.

| Copy | Rules | Differences |
|---|---|---|
| `deploy/helm/cmapi/config/metadata-keys.yaml` | 5 -> 5 | none |
| `examples/cluster-configs/policies/metadata-keys.yaml` | 5 -> 5 | none |
| `examples/local/config/metadata-keys.yaml` | 5 -> 5 | none |
| `deploy/manifests/environments/crc/20-config.yaml` | 5 -> 5 | none |
| `deploy/manifests/environments/kind/20-config.yaml` | 5 -> 5 | none |

Each has the limits `["", "*.ephico2real.com/"]`, 50, 50, 4096, 65536, and one new stanza, `adoptionLabels:
{company.net/provisioner: {recognise: [cluster-configs]}}`. Confirmed: no difference. `git grep` finds no other
reader of the old stanza names; `examples/src/cmapi` is a link to `cmapi/src/cmapi`.

Differences in the code's behaviour for a shipped file, none of which changes an outcome:

- A label key sent as an annotation (`cmapi.net/team` in `annotations`) is still `invalid_key`; the detail is now
  "prefix not allowed", it was "cmapi.net/team is a label".
- `missing_required_key` now has `kind` and `detail`; `too_many_keys` is now one error for each kind, with `kind` and `detail`.
- A file with no `extraLabels` stanza now admits no other key (`prefixes` defaults to `[]`). The old default with no
  `team` stanza was `[""]`. Every shipped copy has the stanza.

## Check 3: edge cases

From `probe.py` on `c830276`, and one API test.

| Case | Result on `c830276` |
|---|---|
| Empty required value (`lob: ''`) | Refused, with two errors for the one key: `invalid_value` and `missing_required_key` |
| `cl: 1` (a number) in the request | The API answers 422 `validation-failed`, "body.labels.company.net/cl: Input should be a valid string" (`test_a_number_for_a_label_value_is_a_validation_problem_not_an_error`). `validate` itself raises `TypeError` on a number, as it did on main; only the reference app (`examples/local/app.py`) reaches it without a model |
| `enum: [0, 1, 2, 3]` in the file | Refused: "enum must be a list of strings" |
| `namespacePrefix`, namespace `abc` | Refused: "abc does not start with abc-" |
| `namespacePrefix`, namespace `abcd-rnd` | Refused: "abcd-rnd does not start with abc-" |
| `kubernetes.io/x`, `app.kubernetes.io/name` | `reserved_key` for both |
| 51 other annotations; one of 4097 bytes; 17 of 4096 bytes | `too_many_keys`; `annotations_too_large`; `annotations_too_large`. 16 of 4096 bytes pass (65536 exactly) |
| `cmapi.net/tier`, `cmapi.net/env`, `cmapi.net/requested-by` from a requester | `reserved_key`. `cmapi.net/foo` (not a system key): `invalid_key`, prefix not allowed |
| A system, operator-only or reserved key in any of the four stanzas | The loader refuses each |
| `allowOther.prefixes` with `cmapi.net/` | Loads, and `cmapi.net/owner` is then accepted. Main's `allowedPrefixes` had the same gap; system keys stay refused |
| An adoption label when its prefix is allowed | **Accepted: F2** |
| `max: -1`, `maxValueBytes: null` | **Load: F4** |
| No `sources` passed to `validate` | A wrong derived value and a wrong prefix pass. `pipeline.py` always passes them; `examples/local/app.py:233` does not (the shipped file has no derived key) |

## Check 4: one source for the API document

- **Descriptions: confirmed.** `core/docs.py:395-402` writes the description of `labels` and `annotations` of
  `NamespaceCreate` and `NamespacePatch` from `ctx.cfg.metadata` (`main.py:177`).
- **Examples: refuted: F3.** `models.py:238-239` still holds the fixed examples.
- **The contract gate: confirmed.** `bash cmapi/contract/gate.sh base-openapi.json cmapi/contract/openapi.json`
  answers "No breaking changes to report, but the specs are different", rc 0. `oasdiff diff` shows four changed
  `description` fields and nothing else. A description is not part of the contract that a client depends on.
- The `description` field of a key's rule is read by the loader and used nowhere yet. The issue names it "for the API
  document and the portal form"; the form is Wave 6. I left it out of the fix: putting it in the document changes the
  contract, the portal's types and one of the PR's own assertions.
- On `NamespacePatch` the text starts "Required: ..." for a merge patch, where no key has to be sent. Wording only.

## Check 5: the tests before and after

| Run | Result |
|---|---|
| The PR's 26 core cases on main's code (`main-stanzas-core.log`) | 26 failed |
| The PR's 3 API cases on main's code (`main-stanzas-api.log`) | 3 failed |
| The same on `c830276` | 26 passed, 3 passed |
| `tests/service` on `c830276` | 823 passed in 412.70s. The claim of 823 is confirmed |

The reasons on main, counted from the log:

```
  11 E       TypeError: MetadataKeys.validate() got an unexpected keyword argument 'sources'
  11 E       Failed: DID NOT RAISE <class 'ValueError'>
   2 E       AttributeError: 'MetadataKeys' object has no attribute 'rules'
   1 E       AttributeError: 'MetadataKeys' object has no attribute 'adoption_labels'
   1 E           TypeError: MetadataKeys.check() got an unexpected keyword argument 'sources'
```

So 11 of the 26 fail on behaviour (the loader did not refuse). The other 15 fail because the argument or the attribute
does not exist on main, which any change of signature would also cause. The 3 API cases fail on behaviour: 422 where
200 is expected, other error codes, and the old description. The "before" is real, and the behavioural proof of the
rules is in the API cases more than in the core ones.

To run core and service tests under `suite.sh`, give them in separate calls: both folders have a `conftest.py`, and
one session with both imports the wrong one (my first run failed on that, `head-new-tests.log`).

## The findings

### F1 (Medium): `format: email-in-domains` is accepted on a label, and the key is then unusable

`cmapi/src/cmapi/core/metadata.py:157-159` refuses `format: url` on a label, and not `email-in-domains`, although a
label value cannot hold `@` for the same reason. The owner's spec has `extraLabels.keys.company.net/mnemonic-group-contact:
{format: email-in-domains}`. An organisation that writes it gets a file that loads and a key that no value satisfies:

```
1b email-in-domains on a LABEL loads: MetadataKeys
1b   value team@company.net: [('invalid_value', 'company.net/mnemonic-group-contact', 'not a valid label value')]
1b   value '' (owner's sample): [('invalid_value', 'company.net/mnemonic-group-contact', "not an address in ['company.net']")]
```

Fix: the hunk of `fix.diff` at `metadata.py:157`. Test: `test_the_loader_refuses_an_email_format_on_a_label` (fails on
`c830276` with "DID NOT RAISE"), with the control `test_an_email_format_on_an_annotation_still_loads_and_checks`.
Also add the email half to the decision record's row "`format: url` on a label", and to the sentence of docs/02 that
lists what the loader refuses (live doc first).

### F2 (Medium): an adoption label is refused only by the accident of the prefixes

`deploy/helm/cmapi/config/metadata-keys.yaml:26`, docs/02 and the module's docstring say that a requester cannot set
an adoption label. `metadata.py:111-119` only stores the keys, and `classify` (`metadata.py:202-216`) never reads
them. The PR's test passes because `company.net` is not under `*.company.net/`. An organisation whose keys are all
`company.net/...` can reasonably allow `company.net/`, and then:

```
3h   adoption label set by requester when its prefix is allowed: []
3i system adoption label: <cmapi.core.metadata.MetadataKeys object>      (cmapi.net/managed loads as an adoption label)
```

A requester could then mark a new namespace as one that the old way provisioned, which story #26 will read.
Fix: `classify` answers `reserved` for an adoption label as a label, and the loader checks the key and its values.
This changes the PR's own assertion in `test_adoption_labels_are_read_and_a_requester_cannot_set_them` from
`invalid_key` to `reserved_key`; the diff has that line. Tests:
`test_a_requester_cannot_set_an_adoption_label_when_allow_other_admits_its_prefix` and
`test_the_loader_refuses_a_bad_adoption_label` (3 cases).

### F3 (Medium): the API document's examples are not from the file

Issue #215, item 3: "the OpenAPI description and examples of `labels` and `annotations`". `core/docs.py:395-402` sets
only the description. With the company file, `GET /openapi.json` shows the labels example
`{"cmapi.net/team": "payments"}` (`models.py:238`), which that instance refuses. The `example` field of each rule is
read (`metadata.py:173`) and used nowhere.

```
FAILED tests/service/test_metadata_review_234_api.py::test_the_api_documents_example_is_one_that_this_instance_accepts
```

Fix: `metadata_example` in `core/docs.py`, used for `NamespaceCreate`. For the shipped file it gives the same examples
as the model (`cmapi.net/team: payments`, `cmapi.net/team-dl: payments-team@ephico2real.com`), so
`cmapi/contract/openapi.json` does not change: `tests/service` passes on the fix with the committed contract. The test
also posts the document's own example and expects a plan.

Not covered by this fix: the recorded request samples of `contract/samples.json` are recordings of the shipped file,
and stay so.

### F4 (Low): the limits of `allowOther` are not validated

`metadata.py:185-187`. `max: -1` loads, and every request is then `too_many_keys`, even with no other key; `max: true` loads as 1; `maxValueBytes: null` loads and then every annotation is
`annotations_too_large` (`(None or 0)`); `maxBytesTotal: "64k"` loads and the first annotation raises `TypeError`,
(`'>' not supported between instances of 'int' and 'str'`, measured on `validate`; through the API that is an unhandled error). Main did not validate them either, but this loader now validates every other field.

```
3j max null / maxValueBytes null: [('annotations_too_large', None, None)]
3j max -1: <cmapi.core.metadata.MetadataKeys object>
```

Fix: the hunk at `metadata.py:185`. Test: `test_the_loader_refuses_a_limit_that_is_not_a_whole_number` (4 cases).

## The full fix

`pr-234-files/fix.diff`, against `c830276`:

```diff
diff --git a/cmapi/src/cmapi/core/docs.py b/cmapi/src/cmapi/core/docs.py
index bc87feb..f9c5ae3 100644
--- a/cmapi/src/cmapi/core/docs.py
+++ b/cmapi/src/cmapi/core/docs.py
@@ -392,6 +392,12 @@ def metadata_description(keys: Any, kind: str) -> str:
     return " ".join(parts)
 
 
+def metadata_example(keys: Any, kind: str) -> dict[str, str]:
+    """What a requester sends for one kind: each required key that cmapi does not set, with the example of its rule.
+    A key with no example is left out, so the document never shows a value that the plan would refuse."""
+    return {k: str(r.example) for k, r in keys.rules[kind].items() if r.required and not r.derived and r.example is not None}
+
+
 def _document_metadata(spec: dict[str, Any], keys: Any) -> None:
     """The labels and annotations of NamespaceCreate and NamespacePatch name this instance's keys and rules."""
     schemas = spec.get("components", {}).get("schemas", {})
@@ -400,6 +406,8 @@ def _document_metadata(spec: dict[str, Any], keys: Any) -> None:
         for field, kind in (("labels", "label"), ("annotations", "annotation")):
             if field in props:
                 props[field]["description"] = prefix + metadata_description(keys, kind)
+                if schema == "NamespaceCreate":
+                    props[field]["examples"] = [metadata_example(keys, kind)]
 
 
 def _with_type_base(node: Any, problem_base: str) -> Any:
diff --git a/cmapi/src/cmapi/core/metadata.py b/cmapi/src/cmapi/core/metadata.py
index f8006de..02e8a54 100644
--- a/cmapi/src/cmapi/core/metadata.py
+++ b/cmapi/src/cmapi/core/metadata.py
@@ -116,6 +116,10 @@ class MetadataKeys:
                 continue
             if any(key in self.rules[k] for k in KINDS):
                 problems.append(f"adoptionLabels.{key}: a key that a requester can set is not an adoption label")
+            if self._syntax(key, None, "label") or any(v and (len(v) > 63 or not _NAME.fullmatch(v)) for v in values):
+                problems.append(f"adoptionLabels.{key}: not a valid label key and values")
+            if key in self.system or key in self.operator_only:
+                problems.append(f"adoptionLabels.{key}: a system or operator-only key is not an adoption label")
             self.adoption_labels[key] = tuple(values)
         if problems:
             raise ValueError("invalid metadata-keys.yaml: " + "; ".join(problems))
@@ -154,9 +158,11 @@ class MetadataKeys:
             problems.append(f"{where}: unknown format {fmt}")
         if fmt == "email-in-domains" and not self.email_domains:
             problems.append(f"{where}: format email-in-domains needs emailDomains")
-        if fmt == "url" and kind == "label":
-            # A label value is at most 63 characters of [A-Za-z0-9_.-]: a URL cannot be one.
-            problems.append(f"{where}: format url is for annotations only; a label value cannot hold a URL")
+        if fmt in FORMATS and kind == "label":
+            # A label value is at most 63 characters of [A-Za-z0-9_.-]: it cannot hold the "@" of an address or the
+            # "://" of a URL, so the key would refuse every value that its own format accepts.
+            holds = "a URL" if fmt == "url" else "an address"
+            problems.append(f"{where}: format {fmt} is for annotations only; a label value cannot hold {holds}")
         pattern = spec.get("pattern")
         if pattern is not None:
             try:
@@ -182,9 +188,16 @@ class MetadataKeys:
         if not isinstance(prefixes, list) or not all(isinstance(p, str) for p in prefixes):
             problems.append(f"{stanza}.allowOther.prefixes must be a list")
             prefixes = []
-        return AllowOther(prefixes=tuple(p.rstrip("/") for p in prefixes), max=int(raw.get("max", 50)),
-                          max_value_bytes=raw.get("maxValueBytes", 4096) if kind == "annotation" else None,
-                          max_bytes_total=raw.get("maxBytesTotal", 65536) if kind == "annotation" else None)
+        limits = {"max": raw.get("max", 50)}
+        if kind == "annotation":
+            limits.update(maxValueBytes=raw.get("maxValueBytes", 4096), maxBytesTotal=raw.get("maxBytesTotal", 65536))
+        for name, value in limits.items():
+            # bool is an int in Python; "max: yes" is not a limit
+            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
+                problems.append(f"{stanza}.allowOther.{name} must be a whole number, zero or more")
+                limits[name] = 0
+        return AllowOther(prefixes=tuple(p.rstrip("/") for p in prefixes), max=limits["max"],
+                          max_value_bytes=limits.get("maxValueBytes"), max_bytes_total=limits.get("maxBytesTotal"))
 
     @classmethod
     def load(cls, path: str | Path) -> "MetadataKeys":
@@ -206,6 +219,10 @@ class MetadataKeys:
         if key in self.operator_only:
             return "operatorOnly"
         kinds = KINDS if kind is None else (kind,)
+        if key in self.adoption_labels and "label" in kinds:
+            # Another tool's mark (story #26): reserved even when allowOther admits its prefix, or a requester
+            # could mark a namespace as one that the old way provisioned.
+            return "reserved"
         if any(key in self.rules[k] for k in kinds):
             return "governed"
         prefix = self._prefix(key)
diff --git a/cmapi/tests/core/test_metadata_stanzas.py b/cmapi/tests/core/test_metadata_stanzas.py
index 8193081..54fdfe2 100644
--- a/cmapi/tests/core/test_metadata_stanzas.py
+++ b/cmapi/tests/core/test_metadata_stanzas.py
@@ -98,7 +98,7 @@ def test_a_key_can_be_a_label_and_an_annotation_with_one_rule_each(keys):
 def test_adoption_labels_are_read_and_a_requester_cannot_set_them(keys):
     assert keys.adoption_labels == {"company.net/provisioner": ("cluster-configs",)}
     assert codes(keys.validate({**SENT, "company.net/provisioner": "cluster-configs"}, {}, operator=False,
-                               sources=SOURCES)) == [("invalid_key", "company.net/provisioner")]
+                               sources=SOURCES)) == [("reserved_key", "company.net/provisioner")]
 
 
 def test_the_old_stanzas_stop_the_start_with_the_new_names():
```

## The tests

`cmapi/tests/core/test_metadata_review_234.py`:

```python
"""The Fable review of #234 (#215): a format a label cannot hold, an adoption label under an allowed prefix,
and limits that are not numbers. Each case fails on c830276."""
from __future__ import annotations

import copy

import pytest
import yaml

from cmapi.core.metadata import MetadataKeys
from conftest import EX

COMPANY = EX / "cluster-configs/policies/metadata-keys.company.yaml"
SOURCES = {"namespace": "abc-rnd", "environment": "rnd", "cluster": "OCP_GF15", "instance": "nonprod"}
SENT = {"company.net/mnemonic": "abc", "company.net/lob": "amgsst", "company.net/cl": "1"}


@pytest.fixture
def raw() -> dict:
    return copy.deepcopy(yaml.safe_load(COMPANY.read_text()))


def codes(errs):
    return sorted((e["code"], e.get("key")) for e in errs)


def test_the_loader_refuses_an_email_format_on_a_label(raw):
    # #215's example: extraLabels.keys.company.net/mnemonic-group-contact: {format: email-in-domains}. A label value
    # cannot hold "@", so the key would refuse every address, and the empty value of the owner's sample too.
    raw["extraLabels"]["keys"]["company.net/mnemonic-group-contact"] = {"format": "email-in-domains"}
    with pytest.raises(ValueError, match="format email-in-domains is for annotations only"):
        MetadataKeys(raw)


def test_an_email_format_on_an_annotation_still_loads_and_checks(raw):
    raw["extraAnnotations"]["keys"]["company.net/mnemonic-group-contact"] = {"format": "email-in-domains"}
    keys = MetadataKeys(raw)
    assert keys.validate(SENT, {"company.net/mnemonic-group-contact": "abc-team@company.net"}, operator=False, sources=SOURCES) == []
    assert codes(keys.validate(SENT, {"company.net/mnemonic-group-contact": "abc-team@other.org"}, operator=False,
                               sources=SOURCES)) == [("invalid_value", "company.net/mnemonic-group-contact")]


def test_a_requester_cannot_set_an_adoption_label_when_allow_other_admits_its_prefix(raw):
    raw["extraLabels"]["allowOther"]["prefixes"] = ["", "company.net/"]
    keys = MetadataKeys(raw)
    assert keys.classify("company.net/provisioner", "label") == "reserved"
    assert codes(keys.validate({**SENT, "company.net/provisioner": "cluster-configs"}, {}, operator=False,
                               sources=SOURCES)) == [("reserved_key", "company.net/provisioner")]
    # another key of the same prefix is still a team key
    assert keys.validate({**SENT, "company.net/owner": "ola"}, {}, operator=False, sources=SOURCES) == []


@pytest.mark.parametrize("key, spec, message", [
    ("cmapi.net/managed", {"recognise": ["true"]}, "a system or operator-only key is not an adoption label"),
    ("not a key", {"recognise": ["x"]}, "not a valid label key and values"),
    ("company.net/provisioner", {"recognise": ["cluster configs"]}, "not a valid label key and values"),
])
def test_the_loader_refuses_a_bad_adoption_label(raw, key, spec, message):
    raw["adoptionLabels"] = {key: spec}
    with pytest.raises(ValueError, match=message):
        MetadataKeys(raw)


@pytest.mark.parametrize("stanza, field, value", [
    ("extraLabels", "max", -1),               # c830276: loads, and then every other key is "too many"
    ("extraLabels", "max", True),             # c830276: loads as 1
    ("extraAnnotations", "maxValueBytes", None),   # c830276: loads, and then every annotation is "too large"
    ("extraAnnotations", "maxBytesTotal", "64k"),  # c830276: loads, and the first annotation raises TypeError
])
def test_the_loader_refuses_a_limit_that_is_not_a_whole_number(raw, stanza, field, value):
    raw[stanza]["allowOther"][field] = value
    with pytest.raises(ValueError, match=rf"{stanza}\.allowOther\.{field} must be a whole number"):
        MetadataKeys(raw)


def test_the_shipped_copies_still_load():
    for path in ("cluster-configs/policies/metadata-keys.yaml", "cluster-configs/policies/metadata-keys.company.yaml",
                 "local/config/metadata-keys.yaml"):
        MetadataKeys.load(EX / path)
```

`cmapi/tests/service/test_metadata_review_234_api.py`:

```python
"""The Fable review of #234 (#215), through the API: the example of labels and annotations comes from the file."""
from __future__ import annotations

from conftest import EXAMPLES  # noqa: F401  (the fixtures of test_metadata_stanzas_api need the same conftest)
from test_flow import OLA, auth
from test_metadata_stanzas_api import URL, body, company  # noqa: F401


def test_the_api_documents_example_is_one_that_this_instance_accepts(company):
    client, ctx, git, kube, validator, keys = company
    props = client.get("/openapi.json").json()["components"]["schemas"]["NamespaceCreate"]["properties"]
    # c830276: [{"cmapi.net/team": "payments"}], the model's fixed example, which this instance refuses.
    assert props["labels"]["examples"] == [{"company.net/mnemonic": "abc", "company.net/lob": "amgsst", "company.net/cl": "1"}]
    assert props["annotations"]["examples"] == [{}]
    r = client.post(URL + "?dryRun=true", headers=auth(keys, "ola", **OLA),
                    json=body(labels=props["labels"]["examples"][0], annotations=props["annotations"]["examples"][0]))
    assert r.status_code == 200, r.text


def test_a_number_for_a_label_value_is_a_validation_problem_not_an_error(company):
    """Evidence for the review's edge case (cl: 1 against '1'); passes before and after."""
    client, ctx, git, kube, validator, keys = company
    labels = {"company.net/mnemonic": "abc", "company.net/lob": "amgsst", "company.net/cl": 1}
    r = client.post(URL + "?dryRun=true", json=body(labels=labels), headers=auth(keys, "ola", **OLA))
    assert r.status_code == 422 and r.json()["code"] == "validation-failed", r.text
```

## Noted, with no fix asked

- `_governed`'s branch `rule is None` (`metadata.py:295-297`) cannot be reached now that `classify` takes the kind.
- A derived key whose source is empty is left out of the namespace with no error (`derived`, `metadata.py:224`).
  `pipeline.py` always gives the four sources.
- `examples/local/app.py:233` calls `check` with no `sources`. Passing them, as `pipeline.py:206-209` does, would keep
  the reference app right for a file with derived keys.

## What I did not do

- No cluster run (kind or CRC), no portal suite, no reference suite from `examples/`. `tests/core` is the same set of
  files, run here from `cmapi/`.
- I did not regenerate the portal's API types, because the fix does not change the contract.
- I did not read the live Technical Design v2 (rev 349); I read the export `docs/02-technical-design-v2.md` in the diff.
- Worktrees left in place: `fable-review/wt-234` (the clean head) and `fable-review/wt-234-fix` (the head with the fix
  and the tests, uncommitted). I removed the two others I made. Nothing was pushed or committed.
