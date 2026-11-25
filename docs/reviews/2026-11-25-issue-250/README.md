# #250 and #680: folder files with several documents or no valid YAML, and folders with several ResourceQuotas

- **Implementer:** Opus 5.5 high.
- **Review:** two reviewers (reviewer 1 Codex, reviewer 2 a separate Opus 5.5 high). The change is over 50 lines of code and
  touches the write path, so the rule of 2026-11-25 for one reviewer does not apply.
- **Parent:** story #17.

## What was wrong, measured on main c2b89f5

The issue was filed against the code before #253 (`_doc` in `core/pipeline.py` read `resourcequota.yaml` with
`yaml.safe_load`, d5d8bb4^). #253 replaced that read with `objects_of`, which reads every document, so a label change of a
folder with two ResourceQuotas no longer answered 500. It did something worse, measured with the service suite's fakes before
this change (the "before" run below):

1. **A label change removed a ResourceQuota.** The renderer wrote only cmapi's `<ns>-quota` and removed `resourcequota.yaml`,
   which held the other one too. In delivery mode `apply`, `watch_sync` prunes each object of a removed file that no planned
   file keeps, so the second quota left the cluster as well.
2. **Two quotas and none of them cmapi's:** a label change removed both and added `<ns>-quota` from the tier. On tier
   `custom` it was refused with 422 `custom-quota-required`, because there was no approved quota to keep.
3. **A quota change was planned over one of them**, with no word about the other, which Kubernetes still enforces.
4. **A LimitRange cmapi does not own** was removed by any change.
5. **`namespace.yaml` with a second document**, even only a trailing `---`, answered 500 on GET and on every change:
   `namespace_doc` still read it with `yaml.safe_load`.

## Sources, read on 2026-11-25

- PyYAML 6.0.2, `lib/yaml/__init__.py` (<https://raw.githubusercontent.com/yaml/pyyaml/6.0.2/lib/yaml/__init__.py>):
  `safe_load` is "Parse the first YAML document in a stream", and `safe_load_all` is "Parse all YAML documents in a stream
  and produce corresponding Python objects". `lib/yaml/composer.py`, `get_single_node`: "Ensure that the stream contains no
  more documents", raising `ComposerError("expected a single document in the stream", ...)`. Measured with the suite's PyYAML
  6.0.2: `safe_load("a: 1\n---\n")` raises it, and `safe_load_all` gives `[{'a': 1}, None]`.
- Kubernetes, "Resource Quotas" (<https://raw.githubusercontent.com/kubernetes/website/main/content/en/docs/concepts/policy/resource-quotas.md>):
  "A cluster administrator creates at least one ResourceQuota for each namespace." Several are allowed, and each binds. The
  page does not say so in words; the quota admission plugin does: it "makes decisions by evaluating the incoming object
  against all defined **ResourceQuota.Status.Hard** resource limits in the request namespace" (the design,
  <https://raw.githubusercontent.com/kubernetes/design-proposals-archive/main/resource-management/admission_control_resource_quota.md>),
  and `CheckRequest` refuses with "exceeded quota: <name>" at the first quota of the namespace that the request exceeds
  (`staging/src/k8s.io/apiserver/pkg/admission/plugin/resourcequota/controller.go`, read by reviewer 1 on 2026-11-25).
  cmapi's capacity ledger already counts "the smallest bound among its unscoped quotas" (`core/capacity_ledger.py`, docs/16).
- Kubernetes, "Limit Ranges" (<https://raw.githubusercontent.com/kubernetes/website/main/content/en/docs/concepts/policy/limit-range.md>):
  "If two or more LimitRange objects exist in the namespace, it is not deterministic which default value will be applied."
- RFC 9110, section 15.5.10 (<https://www.rfc-editor.org/rfc/rfc9110.txt>): "The 409 (Conflict) status code indicates that the
  request could not be completed due to a conflict with the current state of the target resource. This code is used in
  situations where the user might be able to resolve the conflict and resubmit the request. The server SHOULD generate content
  that includes enough information for a user to recognize the source of the conflict."
- The adoption design, docs/reviews/2026-11-14-issue-26-adoption/README.md (short form in docs/02, "Quotas and LimitRanges,
  free-form"). D8: "A folder written before this layout (`resourcequota.yaml`, `limitrange.yaml`) is still read, as a stream of
  documents. The next change of that namespace removes the old file and writes the named files in one commit, each object's
  text unchanged; no commit holds an object in two files." D9: "When the namespace has exactly one object of the kind, the
  name may be left out, as today. With several and no name, the plan refuses it with a problem that names the objects. [...]
  Any other request, a change of a label for example, leaves every object unchanged." Build row B10: "A folder with two
  ResourceQuotas: an update of a label passes; the next change writes `resourcequota-<name>.yaml` files".

## Decisions

1. **One reader.** `kube_yaml.load_all(text)`, beside the writer `kube_yaml.dump`: every document that is a mapping, in order.
   An empty document and one that is not a mapping are no Kubernetes object, so no reader is handed one. Every parse of a
   namespace folder's files goes through it: `render/manifests.py` (`objects_of`, the renderer's previous folder),
   `pipeline.py` (`namespace_doc`, service accounts, grants), `sync.py` (apply, prune, the Application's object keys),
   `validate/__init__.py` (the files checked, the previous objects), `jobs/apply.py` and `jobs/watch_sync.py` (the prune of a
   removed file), and `policygen.py` (the renderer's probe). The parses of the policy bundle and of configuration files are
   not folder files and are unchanged. Rejected: `safe_load_all` inline at each site, as before. That is how
   `namespace_doc` kept `safe_load`, and each site filtered empty and non-mapping documents its own way.
2. **cmapi changes only its own objects.** Its ResourceQuota is `<ns>-quota`. A lone ResourceQuota of another name is the
   one that a change of the quota, the tier or the limits acts on (#253, unchanged; D9: "When the namespace has exactly one
   object of the kind, the name may be left out, as today"), and decision 3 keeps it on any other change.
   Its LimitRanges are `<ns>-limits-<resource>` and the `<ns>-limits` of before #253, each with the `cmapi.net/tier-hash`
   that every rendering of a tier writes. Every other ResourceQuota and LimitRange is kept as Git holds it, in its own file
   (D8). Where the object is already alone in its named file, the file is not touched. Where it moves out of a file of
   several documents, the object is written unchanged with the writer (Argo CD and the API server compare objects, not
   text; D8's "each object's text unchanged" holds for the object, and a comment of the old file is not carried). An
   object that the tier renders now is replaced whatever it carries and wherever it is, because an object with that name
   is the same Kubernetes object. A LimitRange is not claimed by its name alone (reviewer 1): `<ns>-limits-*` is open, since
   a container resource of any name gets its own object, and a team's `<ns>-limits-gpu` would be removed from Git and from
   the cluster. A kept object whose name is no file name (empty, `.`, `..`, or with `/`) is written under the hash form of
   `object_file`, inside the folder.
3. **ResourceQuotas and none of them cmapi's** (`manifests.quotas_kept`): with several, or with one and a request that
   sends no `quota`, no move of the tier and no `limitRange` (a change of labels, annotations or the expiry), the renderer
   renders no quota and no LimitRange of the tier beside them, and keeps every ResourceQuota and LimitRange. A second quota
   would bind with the others, and cmapi's LimitRanges beside foreign ones would make the defaults "not deterministic". The
   plan sizes nothing: no capacity delta, no exposure, no beyond-tier key. D9: "Any other request, a change of a label for
   example, leaves every object unchanged." Before reviewer 2's fix, a lone quota was taken as cmapi's on every change:
   a label change of a folder whose only quota was a team's `compute` (`requests.cpu: 3`) removed it from Git, pruned it
   from the cluster and wrote the tier's `<ns>-quota` (`requests.cpu: 8`), while the plan sized no change, so no capacity
   rule saw the raise. A scoped quota became an unscoped one, and on tier custom the change answered 422. The pipeline
   passes the request's kind to the renderer as `NamespaceSpec.changes_quota`, true by default, so a plan stored before
   the fix renders again as its plan hash was taken.
4. **The refusal.** With several ResourceQuotas, a request that sends `quota` or moves the tier is 409
   `several-resource-quotas`, with the names in `resourceQuotas`. When none of them is cmapi's, `limitRange` is refused too.
   409, not 422: the body is valid, and the conflict is with the folder's state, which the caller can resolve in Git (RFC 9110,
   15.5.10), as `folder-holds-submodule` and `folder-not-utf8` are. A change of labels, annotations or the expiry passes.
   Naming the object in the request (`resourceQuotas: {<name>: ...}`) is D9's build item B3 with the adoption plugin, not this
   fix.

5. **A folder file that is not YAML (#680, found while fixing this).** `Pipeline._read_folder` parses each file once with the
   reader. A file it cannot parse is refused with 409 `folder-not-yaml`, with each such file in `paths` and the parser's
   problem and line in `detail`. Before, the parser's `yaml.YAMLError` reached no handler, so GET, every change and every
   delete answered 500 `internal-error`. PyYAML 6.0.2 `lib/yaml/error.py`: `class YAMLError(Exception)` and
   `class MarkedYAMLError(YAMLError)`, the base of `ParserError`, `ScannerError`, `ComposerError` and `ConstructorError`.
   A value that a standard tag cannot construct raises Python's own error instead (`construct_yaml_timestamp` calls
   `datetime.date(year, month, day)`, so a plain `2026-02-30` is a ValueError), so the reader turns ValueError, TypeError,
   KeyError and AttributeError of a constructor into a `ConstructorError` at that value, with the tag's name and never the
   value (reviewer 1). A file nested some hundreds of levels deep (500, measured by reviewer 2 with PyYAML 6.0.2 on Python
   3.12) exhausts the stack in PyYAML's parser and composer, and the reader turns that RecursionError into a
   `MarkedYAMLError` too.
   This follows `folder-not-utf8` (#626): the folder's state conflicts with every plan, and the caller can fix it in Git.

## Tests

`cmapi/tests/service/test_multidoc_quota_250.py` has 13 cases: 10 for #250 and 3 for #680 (GET, PATCH, DELETE).

- **Before** (`cmapi/src` stashed in the worktree): 13 failed.
- **After:** 13 passed.

With the review's fixes the file has 31 cases: reviewer 1 added 12 and reviewer 2 added 6 (B1 three times, two guards and the
nested file). On the PR head 15 of the 18 fail; the three guards pass on both, on purpose. With the fixes, 31 passed.

The runs are `before.txt` and `after.txt` beside this file. `contract-checks.txt` and `suites-after.txt` hold the contract
checks and the related suites.

## Behaviour that changed beyond the defect

- A `namespace.yaml` whose documents include none of `kind: Namespace` is now read as no namespace (404). Before, its first
  document was taken whatever its kind. cmapi always writes `kind`, and D8 says that readers find objects by kind.
- A LimitRange that cmapi did not render is kept, where every change used to remove it (D9).
- A lone ResourceQuota that is not `<ns>-quota` is kept on a change of labels, annotations or the expiry, where every change
  used to replace it with the tier's `<ns>-quota` (D9; reviewer 2's B1). A change of the quota, the tier or the limits still
  acts on it as before.
- A `namespace.yaml` that holds the Namespace and objects of other kinds: a change used to answer 500, and now writes the
  file with the Namespace alone, so the other objects leave Git (a ResourceQuota or LimitRange among them is kept in its
  own file). That is what a change already does to a file of the folder that cmapi does not write, `networkpolicy.yaml`
  for example (measured by reviewer 1 on the PR head: the plan removes it).
