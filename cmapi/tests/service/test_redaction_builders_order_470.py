"""Exercise each secret-form construction site in independent hash-seeded interpreters (#470)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap


def test_every_builder_orders_ties_across_hash_seeds():
    source = Path(__file__).resolve().parents[2] / "src"
    script = textwrap.dedent(r'''
        import json
        from cmapi.core.clients.redact import secret_forms, sent_forms
        from cmapi.core.git.github import GitHubProvider
        from cmapi.core.git.gitea import GiteaProvider
        import cmapi.core.git.oplog as oplog
        from cmapi.core.registry import _diagnostic_forms
        import cmapi.tools.realm_sync as realm_sync

        values = ["Credential/with+special&characters-123\\", "Credential/with+special&characters-123\\-tail"]
        snapshots = {
            "secret_forms": secret_forms(values[0]),
            "sent_forms": sent_forms(values[0]),
        }
        for provider in (GitHubProvider, GiteaProvider):
            for basic_auth in (None, ("review-bot", values[1])):
                host = provider("https://review.invalid", "o/r", values[0], basic_auth=basic_auth)
                try:
                    snapshots[f"{provider.__name__}/{bool(basic_auth)}"] = host._forms
                finally:
                    host._client.close()
        for reverse in (False, True):
            oplog._FORMS = ()
            realm_sync._SENT = ()
            ordered = list(reversed(values)) if reverse else values
            for value in ordered:
                oplog.register_secret(value)
                realm_sync.sends(value)
            snapshots[f"oplog/{reverse}"] = oplog._FORMS
            snapshots[f"realm_sync/{reverse}"] = realm_sync._SENT
            snapshots[f"diagnostic/{reverse}"] = _diagnostic_forms({"data": dict(enumerate(ordered))})
        print(json.dumps(snapshots))
    ''')
    results = []
    for seed in (0, 1, 7, 22, 30):
        output = subprocess.check_output(
            [sys.executable, "-c", script],
            env={**os.environ, "PYTHONPATH": str(source), "PYTHONHASHSEED": str(seed)},
            text=True,
            timeout=20,
        )
        snapshots = json.loads(output)
        for name, forms in snapshots.items():
            assert len(forms) == len(set(forms)), (seed, name)
            assert len({len(form) for form in forms}) < len(forms), (seed, name)
            assert forms == sorted(forms, key=lambda form: (-len(form), form)), (seed, name)
        for name in ("oplog", "realm_sync", "diagnostic"):
            assert snapshots[f"{name}/False"] == snapshots[f"{name}/True"]
        results.append(snapshots)
    assert all(result == results[0] for result in results[1:])
