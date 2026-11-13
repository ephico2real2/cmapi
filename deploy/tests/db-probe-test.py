#!/usr/bin/env python3
"""Execute kind-test's pod generator, including against manifests from before #91.
No cluster: the fake k transports actual Deployment JSON in and generated Pod JSON out.
This verifies the proof's CA injection, not libpq or Kubernetes TLS behavior.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile

import yaml

ROOT = Path(__file__).resolve().parents[2]
script = (ROOT / 'deploy/kind-test.sh').read_text()
function = script[script.index('db_pod() {'):script.index('\ndb_read() {')]


def projected_file(pod, c, path):
    """Resolve what source kubelet would project at the container's effective CA path."""
    for mount in c.get('volumeMounts', []):
        parent = mount['mountPath'].rstrip('/') + '/'
        if not path.startswith(parent):
            continue
        volume = next(v for v in pod['volumes'] if v['name'] == mount['name'])
        for source in volume.get('projected', {}).get('sources', []):
            for kind, ref in source.items():
                for item in ref.get('items', []):
                    if item['path'] == path[len(parent):]:
                        return kind, ref['name'], item['key']
    return None


with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)
    for component, filename in [('api', '20-api.yaml'), ('worker', '30-worker.yaml')]:
        deployment = next(d for d in yaml.safe_load_all((ROOT / 'deploy/manifests/components/cmapi' / filename).read_text()) if d['kind'] == 'Deployment')
        for before in (False, True):
            d = json.loads(json.dumps(deployment))
            spec = d['spec']['template']['spec']
            if before:
                for c in spec['initContainers'] + spec['containers']:
                    c['env'] = [e for e in c['env'] if e['name'] not in ('PGSSLMODE', 'PGSSLROOTCERT')]
                for v in spec['volumes']:
                    if 'projected' in v:
                        v['projected']['sources'] = [s for s in v['projected']['sources'] if 'secret' not in s]
            (t / 'deployment.json').write_text(json.dumps(d))
            for where in ('initContainers', 'containers'):
                for wrong in (False, True):
                    body = '''set -euo pipefail
k() {
  case " $* " in
    *" get deploy "*) cat "$PROBE_TMP/deployment.json";;
    *" apply "*) cat >"$PROBE_TMP/pod.json";;
    *) return 99;;
  esac
}
DB_CHECK='print("probe")'
''' + function + '\ndb_pod probe cmapi-' + component + ' ' + where + ' ' + str(wrong).lower() + '\n'
                    subprocess.run(['bash', '-c', body], env={**os.environ, 'PROBE_TMP': tmp}, check=True, capture_output=True)
                    pod = json.loads((t / 'pod.json').read_text())['spec']
                    c = pod['containers'][0]
                    env = {e['name']: e.get('value') for e in c['env']}
                    original = spec[where][0]
                    original_env = {e['name']: e.get('value') for e in original['env']}
                    assert env.get('PGSSLMODE') == original_env.get('PGSSLMODE'), 'proof must preserve the deployed sslmode'
                    if wrong:
                        source = projected_file(pod, c, env.get('PGSSLROOTCERT', ''))
                        assert source == ('configMap', 'cmapi-trust', 'ca-bundle.crt'), (component, where, before, 'wrong CA not supplied at effective libpq path', source)
                    else:
                        assert c['env'] == original['env'], 'positive probe must use the deployed environment'
                        assert pod['volumes'] == spec['volumes'], 'positive probe must use deployed volumes'
                    print('ok', component, where, 'pre-fix' if before else 'WIP', 'wrong-CA' if wrong else 'as-deployed')
