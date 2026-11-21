#!/usr/bin/env python3
"""No cluster: the mutation harness must read its written scripts through Bash.

Keep both copied scripts open for writing, as an unrelated forked child could,
and remove execute permission so direct execution fails on every host, not just
Linux. Run the real unmutated secrets cases, including every secrets.sh caller.
"""
import ast
from contextlib import ExitStack
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
harness = HERE / "mutate-secrets.py"
# Load just the worker, without starting the module's full mutation pool.
tree = ast.parse(harness.read_text(), filename=str(harness))
worker = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "one")
namespace = dict(os=os, shutil=shutil, subprocess=subprocess, sys=sys, tempfile=tempfile,
                 HERE=str(HERE), SRC=str(HERE.parent))
exec(compile(ast.Module(body=[worker], type_ignores=[]), str(harness), "exec"), namespace)

copy = shutil.copy
with ExitStack() as writers:
    copied = set()

    def copy_open(src, dst):
        p = copy(src, dst)
        os.chmod(p, 0o600)
        writers.enter_context(open(p, "r+"))
        copied.add(Path(p).name)
        return p

    with patch.object(shutil, "copy", side_effect=copy_open):
        _, rc, fails = namespace["one"](("base (no mutation)", []))
    assert copied == {"secrets.sh", "secrets-test.sh"}, copied
    assert rc == 0 and not fails, (rc, fails)
print("ok: all secrets cases pass with both harness-written scripts open for writing and non-executable")
