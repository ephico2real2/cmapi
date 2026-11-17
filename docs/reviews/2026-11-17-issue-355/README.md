# #355: the renderer writes y, Y, n and N unquoted, which Kubernetes tooling reads as booleans

Part of #328. Found while building #333 (PR #354). Opus 5.5 (`high`), the implementer, wrote the code, the tests and this
record on 2026-11-17. One model family for this step: Fable is paused by the owner.

## What was wrong

`core/render/manifests.py` `_dump` and `core/policygen.py` `_yaml_all` wrote with `yaml.safe_dump`. PyYAML quotes a
string only when its own resolver would read the plain form as another type, and its resolver is not the one that reads
cmapi's files:

- kubectl, Argo CD and the Kyverno CLI read YAML through `sigs.k8s.io/yaml`, which is go-yaml v2 (YAML 1.1).
- PyYAML's bool set leaves out `y`, `Y`, `n` and `N`, which YAML 1.1 has (yaml.org/type/bool.html:
  `y|Y|yes|Yes|YES|n|N|no|No|NO|true|True|TRUE|false|False|FALSE|on|On|ON|off|Off|OFF`).
- go-yaml resolves numbers through Go's `strconv`, after removing every `_`, and PyYAML's regular expressions do not match
  all of them: `0o17`, `0O17`, `0X1F`, `0B1`, `089`, `1e3`, `+.5` were written plain and read as numbers.
- go-yaml v3 (YAML 1.2, kustomize's kyaml) also reads a short date such as `2026-1-2` as a timestamp.

Measured on main (c7ab6c4) with the real readers (`cmapi/tests/core/yamlread`, sigs.k8s.io/yaml v1.6.0 and
go.yaml.in/yaml/v3 v3.0.4): of the 38,322 strings of the property test, written as values, the YAML 1.1 reader read 111
back as something else, and the YAML 1.2 reader 111 (not the same 111: y and n are strings in YAML 1.2, 2026-1-2 a
timestamp). Written as keys too, a retyped key also collides with another (`y` becomes the key `true`). `kubectl create --dry-run=client` (v1.37.1) on a namespace.yaml with such a team label:
`json: cannot unmarshal bool into Go struct field ObjectMeta.metadata.annotations of type string`
([evidence/kubectl-client.txt](evidence/kubectl-client.txt)). The Kyverno CLI v1.20.0 on the same file with the #354
bundle: `error: no such overload: bytes(bool)` on the annotation byte policies.

## The choice: quote what a reader would retype, as go-yaml's own encoder does

`core/kube_yaml.py` `KubeSafeDumper` is PyYAML's `SafeDumper` with one override, `resolve`: when PyYAML would write a
string plain, `foreign_tag` asks whether go-yaml v2 or v3 would resolve that plain text to another tag, and if so the
emitter quotes it. `foreign_tag` follows go-yaml's `resolve.go` step by step: the table (YAML 1.1 bools including y and
n, nulls, `.inf`, `.nan`, `<<`), then by the first character a float (`.`) or a timestamp, int or float (a digit or a
sign) through the shapes `strconv.ParseInt`/`ParseUint` (base 0), `yamlStyleFloat` and the `0b`/`0o` fallbacks accept.
`yamlStyleFloat` is also YAML 1.2.2's core-schema float (section 10.3.2), and the base-0 int shapes include its `0o` and
`0x` ints, so the YAML 1.2 core schema is covered too. PyYAML's own resolvers, which follow yaml.org/type for int (with
base 60), float, null, timestamp, merge and value, still run first.

This is the rule go-yaml's encoder applies (`encode.go` `stringv`: plain only when `resolve` gives `!!str` back), and
the rule Helm's `toYaml` inherits through sigs.k8s.io/yaml. Every other value is written exactly as before, so Git diffs,
the plan hash and `cmapi-tools policies check` see no change for ordinary values.

The match is by shape, not range: a number too large for 64 bits (`8E959`) or a date that `time.Parse` refuses
(`2026-13-45`) is quoted too. That only adds quotes, and YAML 1.2 calls the number a float anyway.

### Not taken

| Option | Why not |
|---|---|
| Quote every string (`default_style="'"`) | Changes every line of every file in Git: one large diff on every namespace, plan hashes change, and nothing in it is needed |
| ruamel.yaml with `version=(1, 1)` | A new dependency and a different emitter (other line breaks and indentation), so every file changes; its 1.1 bool set also leaves out y and n |
| Add only `y|Y|n|N` to PyYAML's bool resolver | Fixes the symptom of the issue only: `0o17`, `0X1F`, `089`, `1e3`, `+.5` and `2026-1-2` stay wrong (measured) |
| Write JSON (valid YAML) | Every file changes and stops being readable in a pull request |
| Refuse such values in `validate` | `y` is a valid label value, and the owner's rule is never to block a capability (#211) |
| The YAML 1.1 float regex as written on yaml.org/type/float.html (`[-+]?([0-9][0-9_]*)?\.[0-9.]*...`) | It matches `1.2.3`, `4.18.0` and `.`, which no reader of Kubernetes manifests (go-yaml v2, v3, PyYAML) reads as a float: measured, they stay strings. Quoting them would change common version values for nothing |

## What changed

| Where | Change |
|---|---|
| `core/kube_yaml.py` (new) | `KubeSafeDumper`, `foreign_tag`, `dump`, `dump_all` |
| `core/render/manifests.py` `_dump` | Writes through `kube_yaml.dump` |
| `core/policygen.py` `_yaml_all` | Writes through `kube_yaml.dump_all` |
| `tests/core/yamlread/` (new) | The Go reader: `sigs.k8s.io/yaml.YAMLToJSON` and go-yaml v3, every non-string spelled `<type value>` |
| `tests/core/kube_readers.py` (new) | Builds it once per run; skipped without `go`, failing instead under `CMAPI_REQUIRE_GO=1` |
| `.github/workflows/ci.yml` | `actions/setup-go` v7.0.0 (pinned by commit) and `CMAPI_REQUIRE_GO=1` in the reference-code and service jobs |

`jobs/apply.py` and `jobs/watch_sync.py` still dump with `yaml.safe_dump_all`: that text only goes back into PyYAML
(`ApplyDelivery.prune_objects`), never to a Go reader.

## Render diff against main

[evidence/corpus.py](evidence/corpus.py) renders the policy bundle of each example instance with both metadata-keys
files (30 files) and four namespace folders (one with 43 values as team labels and annotations, one with a
ServiceAccount named `y`). The whole diff is [evidence/render-diff.txt](evidence/render-diff.txt): the bundle is
byte-identical, and the only lines that change are the values `y`, `Y`, `n`, `N`, `0o17`, `1e3`, `089`, `0X1F`, `0B1`,
`+.5` and `2026-1-2`, and the ServiceAccount name `y`, each now in single quotes. The committed example bundle passes
`test_the_committed_example_bundle_is_the_render_of_each_instance` unchanged.

## Tests

| Test | Before (main's source) | After |
|---|---|---|
| `test_yaml_quoting_355.py::test_each_yaml11_form_in_a_rendered_namespace_reads_back_as_the_same_string` | fail | pass |
| `::test_every_short_string_reads_back_as_itself_as_a_key_and_as_a_value` (38,322 strings) | fail: 124 wrong in YAML 1.1 (keys and values; the count moves by one or two with Go's map order on colliding keys) | pass: 0 wrong in both readers |
| `::test_only_a_string_that_a_reader_would_retype_gains_quotes` | pass | pass (guard: one extra quote, `8E959`) |
| `::test_the_policy_bundle_writes_through_the_same_dumper` | pass | pass (guard: the shipped bundle has no such value) |
| `::test_kyverno_evaluates_the_byte_policies_on_a_label_y_and_an_annotation_n` | fail: `error: no such overload: bytes(bool)` | pass |
| `tests/service/test_yaml_quoting_355_api.py` (`policy.engine: none`, dry run 200) | fail: `'<bool true>' == 'y'` | pass |

Measured on this Mac (Go 1.27.3, Kyverno CLI v1.20.0, PostgreSQL 16 for the API test). Not run: `kubectl create
--dry-run=client` against an API server (no cluster was up; the decode step, which is where main fails, passes, and the
readers are the library kubectl uses), Argo CD, and CRC.
