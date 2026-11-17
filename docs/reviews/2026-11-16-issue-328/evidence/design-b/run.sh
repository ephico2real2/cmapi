#!/usr/bin/env bash
# Design B for cmapi #328: every measurement, from the prototype in proto/. Read-only on the repository.
# Needs: venv/ (pinned cmapi deps), tools/ (openapi-typescript 7.13.0, the portal's lock), spectral/ (the contract's lock),
# oasdiff 1.37.0 on PATH, go, node; for Swagger UI, the static server on 127.0.0.1:18328 serving site/.
set -uo pipefail
S=$(cd "$(dirname "$0")" && pwd)
R=/Users/olasumbo/gitRepos/cmapi-design
P=$R/examples/cluster-configs/policies
cd "$S"
py() { PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$R/cmapi/src:$S/proto" "$S/venv/bin/python" "$@"; }
py -c "import cmapi.core.metadata as m; print('cmapi imported from', m.__file__)"

echo "== 1. head contract: main's openapi.json with design B's labels and annotations"
py proto/build_head.py "$R/cmapi/contract/openapi.json" "$P/metadata-keys.yaml" head.json
py proto/build_sample.py sample.json
cp head.json sample.json site/

echo "== 2. oasdiff 1.37.0 ($(oasdiff --version))"
bash "$R/cmapi/contract/gate.sh" "$R/cmapi/contract/openapi.json" head.json > oasdiff-gate.txt 2>&1
echo "gate with main's accepted-breaking.txt: exit $? ($(head -1 oasdiff-gate.txt))"
oasdiff breaking --fail-on ERR --err-ignore accepted-breaking.candidate.txt "$R/cmapi/contract/openapi.json" head.json > /dev/null 2>&1
echo "gate with the 14 #328 lines added: exit $?"

echo "== 3. Spectral (the contract's ruleset)"
spectral/node_modules/.bin/spectral lint head.json --ruleset spectral/.spectral.yaml --fail-severity warn > spectral-head.txt 2>&1
echo "head: exit $? ($(tail -1 spectral-head.txt))"

echo "== 4. openapi-typescript 7.13.0 and tsc 5.9.3"
tools/node_modules/.bin/openapi-typescript head.json -o head.ts > /dev/null 2>&1
tools/node_modules/.bin/openapi-typescript sample.json -o sample.ts > /dev/null 2>&1
cp head.ts tscheck/head.ts
for v in base head; do
  (cd tscheck && "$S/tools/node_modules/.bin/tsc" --noEmit --strict --target es2022 --moduleResolution bundler --module esnext "check-$v.ts" > "tsc-$v.txt" 2>&1)
  echo "tsc $v: exit $? ($(grep -c 'error TS' tscheck/tsc-$v.txt) errors)"
done

echo "== 5. differential: core/metadata.py validate() vs ajv 2020 on the generated schema"
for cfg in metadata-keys.yaml:payments-dev:dev metadata-keys.company.yaml:abc-rnd:rnd; do
  IFS=: read -r f ns env <<< "$cfg"
  py proto/differential.py "$P/$f" "$ns" "$env" "cases-$f.json" > /dev/null
  node diff.mjs "cases-$f.json" > "diff-$f.log" 2>&1
  echo "$f: $(head -1 "diff-$f.log")"
  python3 proto/classify.py "diff-$f.log"
done

echo "== 5b. the same, with section 2.3's validator applied (proto/patched_validator.py)"
for cfg in metadata-keys.yaml:payments-dev:dev metadata-keys.company.yaml:abc-rnd:rnd; do
  IFS=: read -r f ns env <<< "$cfg"
  DESIGN_B_VALIDATOR=1 py proto/differential.py "$P/$f" "$ns" "$env" "cases-fixed-$f.json" > /dev/null
  node diff.mjs "cases-fixed-$f.json" > "diff-fixed-$f.log" 2>&1
  echo "$f: $(head -1 "diff-fixed-$f.log")"
  python3 proto/classify.py "diff-fixed-$f.log"
done

echo "== 6. one regex, three engines: Python re.fullmatch, ECMA-262 (u), RE2 (Go regexp)"
py proto/tri_corpus.py tri/corpus.json
node tri/tri.mjs tri/corpus.json | tail -1
(cd tri && GOCACHE="$S/tri/gocache" go run tri.go corpus.json | tail -1)

echo "== 7. Swagger UI 5.34.1 (sha256 of the tarball: $(shasum -a 256 swagger/swagger.tgz | cut -d' ' -f1))"
if curl -sf -o /dev/null http://127.0.0.1:18328/index.html; then
  node drive.mjs http://127.0.0.1:18328 "$S" > swagger-drive.log 2>&1; echo "sample drive: exit $?"
  node drive-contract.mjs http://127.0.0.1:18328 "$S" > swagger-contract.log 2>&1; echo "contract drive: exit $?"
  python3 -c "import json; d=json.load(open('swagger-contract.json')); [print(k, 'required marks:', v['required']) for k, v in d.items()]"
else
  echo "static server not running: python3 -m http.server 18328 --bind 127.0.0.1 --directory $S/site"
fi
