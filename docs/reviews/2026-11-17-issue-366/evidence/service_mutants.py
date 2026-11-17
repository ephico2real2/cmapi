"""#366 service mutants: each breaks one claim; the named tests must fail. The source is restored after each."""
import os, subprocess, sys
from pathlib import Path

ROOT = Path("/Users/olasumbo/gitRepos/workbench/cmapi/wt-366/cmapi")
T = "tests/service/test_protected_366.py"
MUTANTS = [
    ("#374 operator-only keys are not carried forward", "src/cmapi/core/pipeline.py",
     'kept = ("governed", "team", "operatorOnly")', 'kept = ("governed", "team")', f"{T}::test_a_requesters_change_keeps_the_protection_and_the_delete_stays_refused"),
    ("/me reads role names", "src/cmapi/routers/me.py",
     '"operator": roles.is_operator(who),', '"operator": bool({"cmapi-operator", "cmapi-admin"} & who.roles),', f"{T}::test_an_operator_is_a_permission_not_a_role_name"),
    ("the pipeline reads role names", "src/cmapi/core/pipeline.py",
     "operator = self.cfg.roles.is_operator(who, env)", 'operator = bool({"cmapi-operator", "cmapi-admin"} & who.roles)', f"{T}::test_the_pipeline_and_me_ask_one_function"),
    ("the operator check ignores the environment", "src/cmapi/core/pipeline.py",
     "operator = self.cfg.roles.is_operator(who, env)", "operator = self.cfg.roles.is_operator(who)", f"{T}::test_an_operator_is_a_permission_not_a_role_name"),
    ("protection is read from the live labels", "src/cmapi/plugins/namespaces/router.py",
     'c.cfg.approvals.protected_by(_git_labels(files))', 'c.cfg.approvals.protected_by(obj["metadata"].get("labels") or {})', f"{T}::test_protection_is_read_from_git_the_input_of_a_delete"),
    ("any value of a protection label is stored", "src/cmapi/core/pipeline.py",
     "for k, v in labels.items() if k in want and v is not None and v != want[k]]", "for k, v in labels.items() if False]", f"{T}::test_only_the_value_that_protects_is_accepted"),
]
env = {**os.environ, "PYTHONPATH": "src:tests/service", "CMAPI_TEST_DATABASE_URL": "postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi_ob366"}
survived = 0
for what, rel, old, new, test in MUTANTS:
    path = ROOT / rel
    src = path.read_text()
    assert src.count(old) == 1, (what, src.count(old))
    path.write_text(src.replace(old, new))
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", test, "-q", "-W", "ignore", "-p", "no:cacheprovider", "-x"], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=600)
    finally:
        path.write_text(src)
    killed = r.returncode != 0
    survived += not killed
    tail = [l for l in r.stdout.splitlines() if "passed" in l or "failed" in l or "error" in l][-1:]
    print(("ok   " if killed else "FAIL ") + what + " - " + (tail[0] if tail else "?"), flush=True)
print(f"{len(MUTANTS)} service mutants, {len(MUTANTS) - survived} killed, {survived} survived")
sys.exit(1 if survived else 0)
