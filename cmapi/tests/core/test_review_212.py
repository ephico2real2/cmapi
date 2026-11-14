"""Reviewer 1 regression and claim probes; real v1.20 CLI, no services."""
import copy
import json
import subprocess
import pytest
import yaml
from cmapi.core.metadata import MetadataKeys
from cmapi.core.policy import PolicySettings
from cmapi.core.policygen import render_bundle, cel
from cmapi.core.validate import _held
from cmapi.tools.policies import main as policies_tool
from test_policygen import (catalog, company, kyverno, owners_sample, write, resources,
                            validator, folder, BASE, SHIPPED, COMPANY)


def checked_cli(kyverno, tmp_path, bundle, ns):
    root = write(tmp_path / 'bundle', bundle)
    r = subprocess.run([kyverno, 'apply', str(root / 'env/rnd'), '-r',
                        str(resources(tmp_path, {'namespace.yaml': ns})[0]), '-p', '--output-format', 'json'],
                       capture_output=True, text=True, timeout=120)
    (tmp_path / 'cli.stdout').write_text(r.stdout)
    (tmp_path / 'cli.stderr').write_text(r.stderr)
    assert r.stdout, (r.returncode, r.stderr)
    return json.loads(r.stdout)['results']


def test_non_bmp_configured_enum_compiles(kyverno, catalog, tmp_path):
    raw = yaml.safe_load(COMPANY.read_text())
    value = 'emoji 😀, quote ", slash \\, newline\n, accent é'
    raw['extraAnnotations']['keys']['company.net/text'] = {'enum': [value]}
    keys = MetadataKeys(raw)
    bundle = render_bundle(catalog, keys, PolicySettings(), {'rnd'}, 'nonprod')
    ns = yaml.safe_load(owners_sample(catalog, keys)['namespace.yaml'])
    ns['metadata']['annotations']['company.net/text'] = value
    got = checked_cli(kyverno, tmp_path, bundle, ns)
    assert {r['result'] for r in got} == {'pass'}, got


def test_configured_instance_is_quoted_in_messages(kyverno, catalog, tmp_path):
    raw = yaml.safe_load(COMPANY.read_text())
    raw['requiredAnnotations']['company.net/instance'] = {'value': {'from': 'instance'}}
    keys = MetadataKeys(raw)
    instance = "owner's instance"
    bundle = render_bundle(catalog, keys, PolicySettings(), {'rnd'}, instance)
    ns = yaml.safe_load(owners_sample(catalog, keys)['namespace.yaml'])
    ns['metadata']['annotations']['company.net/instance'] = 'other'
    got = checked_cli(kyverno, tmp_path, bundle, ns)
    failed = [r for r in got if r['result'] == 'fail']
    assert len(failed) == 1 and instance in failed[0]['message'], got


@pytest.mark.parametrize('key,value', [('cmapi.net/team', 'aa-'), ('cmapi.net/app', '-aa')])
def test_shipped_label_value_agreement(kyverno, catalog, tmp_path, key, value):
    keys = MetadataKeys.load(SHIPPED)
    errors = keys.validate({'cmapi.net/team': 'payments', key: value},
                           {'cmapi.net/team-dl': 'team@ephico2real.com'}, operator=False)
    assert key in {e['key'] for e in errors}
    ns = {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': 'payments-rnd',
          'labels': {'cmapi.net/managed': 'true', 'cmapi.net/cluster-id': 'OCP_GF15',
                     'cmapi.net/env': 'rnd', 'cmapi.net/team': 'payments', key: value},
          'annotations': {'cmapi.net/team-dl': 'team@ephico2real.com'}}}
    got = checked_cli(kyverno, tmp_path, render_bundle(catalog, keys, PolicySettings(), {'rnd'}, 'nonprod'), ns)
    assert any(r['result'] == 'fail' and key.replace('/', '-').replace('.', '-') in r['policy'] for r in got), got


@pytest.mark.parametrize('value', ['https://example.com/a\u00a0b', 'https://example.com/%zz'])
def test_url_rule_agreement(kyverno, catalog, tmp_path, value):
    raw = yaml.safe_load(COMPANY.read_text())
    raw['extraAnnotations']['keys']['company.net/url'] = {'format': 'url'}
    keys = MetadataKeys(raw)
    expected = 'fail' if keys._governed('company.net/url', value, 'annotation', {}) else 'pass'
    ns = yaml.safe_load(owners_sample(catalog, keys)['namespace.yaml'])
    ns['metadata']['annotations']['company.net/url'] = value
    got = checked_cli(kyverno, tmp_path, render_bundle(catalog, keys, PolicySettings(), {'rnd'}, 'nonprod'), ns)
    result = next(r for r in got if r['policy'].endswith('company-net-url-format'))
    assert result['result'] == expected, result


@pytest.mark.parametrize('kind', ['label', 'annotation'])
@pytest.mark.parametrize('value', [1, None, False])
def test_held_metadata_requires_strings(kind, value):
    field = 'labels' if kind == 'label' else 'annotations'
    doc = {'metadata': {field: {'x': value}}}
    assert not _held({'kind': kind, 'key': 'x', 'rule': 'required'}, doc, doc)


def test_limit_order_violation_is_never_held(kyverno, catalog, company, tmp_path):
    files = owners_sample(catalog, company)
    previous = folder(files)
    lr = yaml.safe_load(files['limitrange.yaml'])
    next(i for i in lr['spec']['limits'] if i['type'] == 'Container')['defaultRequest']['cpu'] = '1'
    files['limitrange.yaml'] = yaml.safe_dump(lr)
    v = validator(catalog, company, tmp_path)
    rule = 'cmapi-limits-rnd-limit-limitrange-container-default-cpu-order'
    assert rule in {f.rule for f in v.validate(folder(files), 'OCP_GF15', 'rnd')}
    assert rule in {f.rule for f in v.validate(folder(files), 'OCP_GF15', 'rnd', previous=previous)}


@pytest.mark.parametrize('status', ['warn', 'unknown', None])
def test_non_pass_skip_results_are_errors(catalog, company, tmp_path, monkeypatch, status):
    files = folder(owners_sample(catalog, company))
    v = validator(catalog, company, tmp_path, policy=PolicySettings(default_mode='audit'))
    name = next(p for p in v.index if p.endswith('requests-cpu-max'))
    meta = yaml.safe_load(files[BASE+'resourcequota.yaml'])['metadata']
    report = {'results': [{'policy': name, 'result': status, 'resources': [
        {'kind': 'ResourceQuota', 'namespace': meta['namespace'], 'name': meta['name']}], 'message': 'probe'}]}
    monkeypatch.setattr(v, '_run', lambda cmd: subprocess.CompletedProcess(cmd, 0, json.dumps(report), ''))
    got = v._kyverno({p:p for p in files}, files, 'rnd', files)
    target = [f for f in got if f.rule == name]
    assert len(target) == 1 and target[0].source == 'cmapi' and target[0].path == BASE+'resourcequota.yaml', got


@pytest.mark.parametrize('stdout,code', [('{"results":[]}', 2), ('', 2), ('{}', 0),
                                         ('{"results":{}}', 0), ('{"results":[null]}', 0)])
def test_cli_faults_fail_closed(catalog, company, tmp_path, monkeypatch, stdout, code):
    files = folder(owners_sample(catalog, company))
    v = validator(catalog, company, tmp_path)
    monkeypatch.setattr(v, '_run', lambda cmd: subprocess.CompletedProcess(cmd, code, stdout, 'probe'))
    got = v._kyverno({p:p for p in files}, files, 'rnd', files)
    assert any(f.source == 'cmapi' and f.rule == 'validator' for f in got), got


def test_findings_use_namespace_in_identity(kyverno, catalog, company, tmp_path):
    a = yaml.safe_load(owners_sample(catalog, company)['resourcequota.yaml'])
    a['spec']['hard']['requests.cpu'] = '40'
    b = copy.deepcopy(a)
    b['metadata']['namespace'] = 'xyz-rnd'
    paths = [BASE+'resourcequota.yaml', BASE.replace('abc-rnd', 'xyz-rnd')+'resourcequota.yaml']
    files = dict(zip(paths, (yaml.safe_dump(a), yaml.safe_dump(b))))
    got = validator(catalog, company, tmp_path).validate(files, 'OCP_GF15', 'rnd')
    assert sorted(f.path for f in got if f.source == 'kyverno') == sorted(paths), got
    assert not [f for f in got if f.source == 'cmapi'], got


def test_render_preserves_handwritten_collision(tmp_path, monkeypatch):
    import cmapi.tools.policies as module
    root = tmp_path/'policies'
    target = root/'env/rnd/custom.yaml'
    target.parent.mkdir(parents=True)
    target.write_text('hand-written policy\n')
    monkeypatch.setattr(module, '_render', lambda *a: ({'env/rnd/custom.yaml': '# Rendered by cmapi\nnew\n'}, {'rnd'}))
    with pytest.raises(SystemExit, match='hand-written'):
        policies_tool(['render', '--config-dir', 'unused', '--metadata-keys', 'unused', '--out', str(root)])
    assert target.read_text() == 'hand-written policy\n'


def test_render_does_not_follow_environment_symlink(tmp_path, monkeypatch):
    import cmapi.tools.policies as module
    root, other = tmp_path/'policies', tmp_path/'other-instance'
    (root/'env').mkdir(parents=True)
    other.mkdir()
    target = other/'custom.yaml'
    target.write_text('other instance\n')
    (root/'env/rnd').symlink_to(other, target_is_directory=True)
    monkeypatch.setattr(module, '_render', lambda *a: ({'env/rnd/custom.yaml': '# Rendered by cmapi\nnew\n'}, {'rnd'}))
    with pytest.raises(SystemExit, match='symlink'):
        policies_tool(['render', '--config-dir', 'unused', '--metadata-keys', 'unused', '--out', str(root)])
    assert target.read_text() == 'other instance\n'


def admission_fixture(bundle, old, operation):
    """Bind oldObject and operation in CEL copies: CLI simulation, not live admission."""
    def literal(value):
        # CEL maps/lists are homogeneous unless their values are explicitly dynamic.
        if isinstance(value, dict):
            return '{' + ', '.join(cel(k) + ': dyn(' + literal(v) + ')' for k, v in value.items()) + '}'
        if isinstance(value, list):
            return '[' + ', '.join('dyn(' + literal(v) + ')' for v in value) + ']'
        return 'null' if value is None else cel(value)
    old_literal = '(dyn(' + literal(old) + '))'
    out = {}
    for path, text in bundle.items():
        if not path.endswith('.yaml'):
            continue
        docs = list(yaml.safe_load_all(text))
        for doc in docs:
            spec = doc['spec']
            for field in ('variables', 'matchConditions', 'validations'):
                for entry in spec.get(field, []):
                    for key in ('expression', 'messageExpression'):
                        if key in entry:
                            entry[key] = entry[key].replace('oldObject', old_literal).replace(
                                'request.operation', cel(operation))
        out[path] = yaml.safe_dump_all(docs)
    return out


@pytest.mark.parametrize('family,key,new,old,operation,expected', [
    ('namespace', 'cmapi.net/team', 'bad!', 'bad!', 'UPDATE', 'pass'),
    ('namespace', 'cmapi.net/team', 'bad!', 'good', 'UPDATE', 'fail'),
    ('namespace', 'cmapi.net/team', None, None, 'UPDATE', 'pass'),
    ('namespace', 'cmapi.net/team', None, 'good', 'UPDATE', 'fail'),
    ('namespace', 'cmapi.net/team', 'bad!', None, 'CREATE', 'fail'),
    ('resourcequota', 'requests.cpu', '40000m', '40', 'UPDATE', 'pass'),
    ('resourcequota', 'requests.cpu', '41', '40', 'UPDATE', 'fail'),
    ('resourcequota', 'requests.cpu', '40', None, 'CREATE', 'fail'),
    ('limitrange', 'max.cpu', '20000m', '20', 'UPDATE', 'pass'),
    ('limitrange', 'max.cpu', '21', '20', 'UPDATE', 'fail'),
    ('limitrange', 'max.cpu', '20', None, 'CREATE', 'fail'),
])
def test_rendered_ratchet_with_bound_old_object(kyverno, catalog, tmp_path, family, key, new, old, operation, expected):
    keys = MetadataKeys.load(SHIPPED)
    bundle = render_bundle(catalog, keys, PolicySettings(), {'rnd'}, 'nonprod')
    kind = {'namespace': 'Namespace', 'resourcequota': 'ResourceQuota', 'limitrange': 'LimitRange'}[family]
    doc = {'apiVersion': 'v1', 'kind': kind, 'metadata': {'name': 'payments-rnd',
           'labels': {'cmapi.net/managed': 'true', 'cmapi.net/team': 'payments',
                      'cmapi.net/cluster-id': 'OCP_GF15', 'cmapi.net/env': 'rnd'},
           'annotations': {'cmapi.net/team-dl': 'team@ephico2real.com'}}}
    if family == 'resourcequota':
        doc['metadata']['namespace'] = 'payments-rnd'
        doc['spec'] = {'hard': {}}
    if family == 'limitrange':
        doc['metadata']['namespace'] = 'payments-rnd'
        doc['spec'] = {'limits': [{'type': 'Container', 'max': {}}]}
    previous = copy.deepcopy(doc)
    def put(d, v):
        field = d['metadata']['labels'] if family == 'namespace' else (
            d['spec']['hard'] if family == 'resourcequota' else d['spec']['limits'][0]['max'])
        name = key if family != 'limitrange' else 'cpu'
        field.pop(name, None)
        if v is not None:
            field[name] = v
    put(doc, new)
    put(previous, old)
    adapted = admission_fixture(bundle, previous if operation == 'UPDATE' else None, operation)
    got = checked_cli(kyverno, tmp_path, adapted, doc)
    suffix = {'namespace': 'label-cmapi-net-team-pattern', 'resourcequota': 'quota-requests-cpu-max',
              'limitrange': 'limit-limitrange-container-max-cpu-max'}[family]
    target = next(r for r in got if r['policy'].endswith(suffix))
    assert target['result'] == expected, got


@pytest.mark.parametrize('labels', [None, {}])
def test_missing_managed_label_is_skip(kyverno, catalog, company, tmp_path, labels):
    ns = {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': 'unmanaged'}}
    if labels is not None:
        ns['metadata']['labels'] = labels
    bundle = render_bundle(catalog, company, PolicySettings(), {'rnd'}, 'nonprod')
    assert {r['result'] for r in checked_cli(kyverno, tmp_path, bundle, ns)} == {'skip'}


@pytest.mark.parametrize('filename', ['namespace.yaml', 'resourcequota.yaml', 'limitrange.yaml'])
def test_removing_managed_label_still_matches_old_object(kyverno, catalog, company, tmp_path, filename):
    old = yaml.safe_load(owners_sample(catalog, company)[filename])
    new = copy.deepcopy(old)
    del new['metadata']['labels']['cmapi.net/managed']
    bundle = admission_fixture(render_bundle(catalog, company, PolicySettings(), {'rnd'}, 'nonprod'), old, 'UPDATE')
    got = checked_cli(kyverno, tmp_path, bundle, new)
    assert not [r for r in got if r['result'] in ('skip', 'error')], got
    expected = ['cmapi-metadata-rnd-label-cmapi-net-managed-required'] if filename == 'namespace.yaml' else []
    assert [r['policy'] for r in got if r['result'] == 'fail'] == expected


@pytest.mark.parametrize('mode', ['enforce', 'audit'])
def test_cel_error_with_same_previous_value_is_never_held(kyverno, catalog, company, tmp_path, mode):
    files = owners_sample(catalog, company)
    quota = yaml.safe_load(files['resourcequota.yaml'])
    quota['spec']['hard']['requests.cpu'] = 'invalid'
    files['resourcequota.yaml'] = yaml.safe_dump(quota)
    files = folder(files)
    got = validator(catalog, company, tmp_path, policy=PolicySettings(default_mode=mode)).validate(
        files, 'OCP_GF15', 'rnd', previous=files)
    assert [(f.source, f.severity) for f in got if f.rule.endswith('requests-cpu-max')] == [('cmapi', 'error')]


def test_exit_two_with_complete_passing_report_is_error(catalog, company, tmp_path, monkeypatch):
    from cmapi.core.validate import _matched_kinds
    files = folder(owners_sample(catalog, company))
    v = validator(catalog, company, tmp_path)
    results = []
    for name, kinds in _matched_kinds(v.policies_for('rnd')).items():
        for text in files.values():
            doc = yaml.safe_load(text)
            if doc['kind'] in kinds:
                results.append({'policy': name, 'result': 'pass', 'resources': [
                    {'kind': doc['kind'], 'name': doc['metadata']['name'],
                     'namespace': doc['metadata'].get('namespace', '')}]})
    monkeypatch.setattr(v, '_run', lambda cmd: subprocess.CompletedProcess(cmd, 2, json.dumps({'results': results}), 'fault'))
    got = v._kyverno({p:p for p in files}, files, 'rnd', {})
    assert any(f.source == 'cmapi' and 'exited 2' in f.message for f in got), got


@pytest.mark.parametrize('kind,key,spec', [
    ('quota', 'requests.cpu', {'hard': {'requests.cpu': 'invalid'}}),
    ('limit', 'limitRange.container.max.cpu', {'limits': [{'type': 'Container', 'max': {'cpu': 'invalid'}}]}),
])
def test_held_requires_a_real_amount(kind, key, spec):
    doc = {'spec': spec}
    assert not _held({'kind': kind, 'key': key, 'rule': 'max'}, doc, doc)


def test_unkeyed_expiry_failure_is_never_held(kyverno, catalog, tmp_path):
    from cmapi.core.validate import CliValidator
    keys = MetadataKeys.load(SHIPPED)
    ns = {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': 'prod-ns',
          'annotations': {'cmapi.net/expires-at': ''}}}
    files = {BASE+'namespace.yaml': yaml.safe_dump(ns)}
    v = CliValidator(tmp_path/'no-hand-written', kubeconform='true', bundle=render_bundle(
        catalog, keys, PolicySettings(), {'prod'}, 'prod'))
    got = v.validate(files, 'OCP_GF15', 'prod', previous=files)
    assert [(f.source, f.rule) for f in got] == [('kyverno', 'deny-expiry-in-prod')]


def test_missing_wildcard_policy_result_is_guard_error(kyverno, catalog, company, tmp_path):
    from cmapi.core.validate import CliValidator
    hand = tmp_path/'hand'
    hand.mkdir()
    (hand/'unknown.yaml').write_text(yaml.safe_dump({
        'apiVersion': 'policies.kyverno.io/v9', 'kind': 'ValidatingPolicy',
        'metadata': {'name': 'unknown-wildcard'}, 'spec': {'validationActions': ['Deny'],
        'matchConstraints': {'resourceRules': [{'apiGroups': [''], 'apiVersions': ['v1'],
                                              'operations': ['CREATE', 'UPDATE'], 'resources': ['*']}]},
        'validations': [{'expression': 'true'}]}}))
    files = {BASE+'namespace.yaml': owners_sample(catalog, company)['namespace.yaml']}
    v = CliValidator(hand, kubeconform='true', policy=PolicySettings(default_mode='audit'),
                     bundle=render_bundle(catalog, company, PolicySettings(), {'rnd'}, 'nonprod'))
    got = v.validate(files, 'OCP_GF15', 'rnd', previous=files)
    assert [(f.source, f.rule, f.path, f.severity) for f in got] == [
        ('cmapi', 'unknown-wildcard', BASE+'namespace.yaml', 'error')], got
