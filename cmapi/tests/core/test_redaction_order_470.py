"""Secret form ordering must not depend on the process's hash seed (#470)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_secret_forms_with_equal_lengths_have_the_same_order_under_different_hash_seeds():
    source = Path(__file__).resolve().parents[2] / "src"
    script = (
        "import json, sys; "
        "from cmapi.core.clients.redact import secret_forms, sent_forms; "
        "print(json.dumps([secret_forms(sys.argv[1]), sent_forms(sys.argv[1])]))"
    )
    results = []
    for seed in (0, 1, 7, 22, 30):
        output = subprocess.check_output(
            [sys.executable, "-c", script, "Credential/with+special&characters-123"],
            env={**os.environ, "PYTHONPATH": str(source), "PYTHONHASHSEED": str(seed)},
            text=True,
            timeout=10,
        )
        results.append(json.loads(output))

    # The encoded spelling ties with a twice-escaped spelling: exercise a real tie.
    sent = results[0][1]
    assert len({len(form) for form in sent}) < len(sent)
    assert all(forms == results[0] for forms in results[1:])
