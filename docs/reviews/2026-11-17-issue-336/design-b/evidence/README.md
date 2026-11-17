# Evidence for design.md (#336, design B)

Base: `origin/main` c7ab6c4, exported with `git -C <repo> archive origin/main | tar -x -C <export>`. The Python
scripts import cmapi from that export (`PYTHONPATH=<export>/cmapi/src`; each prints or uses the imported path) with a
Python that has `google-re2==1.1.20251105` (here `/Users/olasumbo/gitRepos/workbench/cmapi/ob-348/venv`). The browser
scripts use the portal's installed Playwright (`cmapi-portal-ui/node_modules`, Chromium 156.0.8078.4). Node 26.9.0.
Run from the folder that holds `<export>` as `main`:

| Script | Command | Output |
|---|---|---|
| `gen_response.py` | `PYTHONPATH=main/cmapi/src python ../evidence/gen_response.py main` | `response-{reference,company}.json`: main's generator as it is |
| `designed_response.py` | same form | `designed-response-*.json`: the body design.md specifies (D5, D6) |
| `bodies.py` | same form | `bodies.log`: the validator on the bodies the form sends and must not send |
| `corpus.py` | same form | `corpus.json` (7.2 MB, deterministic, seed 336; deleted after the run, rerun to get it) |
| `client_check.mjs` | `node client_check.mjs` (needs `corpus.json`) | `client_check.log`: 0 stricter, 0 pattern differences, 9 of 12 fail with `v` |
| `noflag.mjs` | `node noflag.mjs` | `noflag.log` |
| `redos.py`, `redos.mjs` | the Python form; `node redos.mjs` | `redos-loader.log`, `redos-v8.log` |
| `large.py`, `large.mjs` | the Python form, then `node large.mjs` | `large.log` (the large bodies are deleted after) |
| `browser.mjs` | `node browser.mjs <repo>/cmapi-portal-ui/node_modules` | `browser.log` |
| `url_verdicts.py`, `browser_url.mjs` | the Python form, then `node browser_url.mjs <node_modules>` | `url_verdicts.json`, `browser_url.log` (last line: the value of mutant M12) |
