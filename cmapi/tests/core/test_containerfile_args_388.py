"""#388: each ARG that a build stage uses has a value in that stage, and the image sets the Kyverno version it pins.

An ARG is scoped to its build stage. A default given inside one stage does not reach another: "To use an argument in
multiple distinct stages, each stage must include the ARG instruction" (Dockerfile reference, "Scope"), and to use the
default of an ARG declared before the first FROM, a stage declares it again "without a value" (Dockerfile reference,
"Understand how ARG and FROM interact"; Buildah's Containerfile(5) says the same for a second FROM). cmapi/Containerfile
gave KYVERNO_VERSION its default in the tools stage only, so the final stage's bare ARG was empty, CMAPI_KYVERNO_VERSION
was empty in every image, kyvernoVersion was null and the start check of the pinned CLI was off.

stages() reads a Containerfile's stages with those rules. test_the_model_agrees_with_a_real_builder holds the model to
a real builder: it builds the Containerfile's FROM, ARG, ENV and LABEL lines on scratch, which runs nothing and pulls
nothing, and compares the image's environment with the model's. That test is skipped with no container engine, and
fails instead under CMAPI_REQUIRE_CONTAINER_ENGINE=1, as CI sets it. The start-check test needs the pinned Kyverno CLI
(CMAPI_REQUIRE_KYVERNO=1 in CI).
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from cmapi.core.policy import PolicySettings
from cmapi.core.validate import CliValidator, PolicyEngineMissing

ROOT = Path(__file__).resolve().parents[3]
CONTAINERFILES = ("cmapi/Containerfile", "cmapi-portal-ui/Containerfile")
# ${NAME}, ${NAME:-word}, ${NAME%%pattern} (a shell expansion in RUN) and $NAME: group 1 or 2 is the name
REFERENCE = re.compile(r"\$\{(\w+)[^}]*\}|\$(\w+)")


@dataclass
class Stage:
    name: str | None
    args: dict[str, str] = field(default_factory=dict)  # the ARGs in scope, and the value each has with no --build-arg
    env: dict[str, str] = field(default_factory=dict)
    uses: list[tuple[str, str]] = field(default_factory=list)  # (instruction, name) for each $NAME the stage holds


def instructions(text: str) -> list[tuple[str, str]]:
    """(INSTRUCTION, rest) for each logical line: continuations joined, comments and blank lines dropped."""
    out, buf = [], ""
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if s.endswith("\\"):
            buf += s[:-1] + " "
            continue
        line = (buf + s).strip()
        buf = ""
        word, _, rest = line.partition(" ")
        out.append((word.upper(), rest.strip()))
    assert not buf, "the file ends inside a continuation"
    return out


def expand(value: str, scope: dict[str, str]) -> str:
    return REFERENCE.sub(lambda m: scope.get(m[1] or m[2], ""), value)


def stages(text: str) -> tuple[dict[str, str], list[Stage]]:
    """The global ARGs (before the first FROM) and each stage, with the scoping rules of the Dockerfile reference."""
    globals_: dict[str, str | None] = {}
    out: list[Stage] = []
    for word, rest in instructions(text):
        if word == "FROM":
            tokens = [t for t in rest.split() if not t.startswith("--")]
            name = tokens[2].lower() if len(tokens) == 3 and tokens[1].upper() == "AS" else None
            base = next((s for s in out if s.name and s.name == tokens[0].lower()), None)
            # A stage based on an earlier stage inherits its ARGs and ENV; any other stage starts with none.
            out.append(Stage(name, dict(base.args) if base else {}, dict(base.env) if base else {}))
            continue
        stage = out[-1] if out else None
        if word == "ARG":
            key, eq, default = rest.partition("=")
            key = key.strip()
            if stage is None:
                globals_[key] = default if eq else None
            else:
                scope = {**stage.args, **stage.env}
                stage.args[key] = expand(default, scope) if eq else (globals_.get(key) or "")
            continue
        assert stage is not None, f"{word} before the first FROM"
        stage.uses += [(word, m[1] or m[2]) for m in REFERENCE.finditer(rest)]
        if word == "ENV":
            pairs = shlex.split(rest)
            if "=" not in pairs[0]:  # the legacy form, ENV key value
                pairs = [f"{pairs[0]}={' '.join(pairs[1:])}"]
            for pair in pairs:
                key, _, value = pair.partition("=")
                stage.env[key] = expand(value, {**stage.args, **stage.env})
    return {k: v or "" for k, v in globals_.items()}, out


def pinned_kyverno() -> str:
    """The one `ARG KYVERNO_VERSION=` line, which CI's `sed -n 's/^ARG KYVERNO_VERSION=//p'` also reads."""
    found = re.findall(r"^ARG KYVERNO_VERSION=(\S+)$", (ROOT / "cmapi/Containerfile").read_text(), re.M)
    assert len(found) == 1, f"CI's sed and docs_assets read one ARG KYVERNO_VERSION= line; the Containerfile has {found}"
    return found[0]


@pytest.mark.parametrize("path", CONTAINERFILES)
def test_every_arg_a_stage_uses_has_a_value_in_that_stage(path):
    """An ARG used in a stage where it has no value expands to the empty string, with no error from the builder."""
    text = (ROOT / path).read_text()
    _, built = stages(text)
    declared = {k for w, r in instructions(text) if w == "ARG" for k in [r.partition("=")[0].strip()]}
    empty = [(s.name or f"stage {i}", w, n) for i, s in enumerate(built) for w, n in s.uses
             if n in declared and n not in s.env and not s.args.get(n)]
    assert empty == [], f"{path}: ARGs used where they have no value: {empty}"


def test_the_image_sets_the_kyverno_version_that_its_tools_stage_downloads():
    _, built = stages((ROOT / "cmapi/Containerfile").read_text())
    tools, final = next(s for s in built if s.name == "tools"), built[-1]
    assert tools.args["KYVERNO_VERSION"] == pinned_kyverno()
    assert final.env["CMAPI_KYVERNO_VERSION"] == pinned_kyverno()


def test_the_model_reads_the_documented_scoping_rules():
    """The examples of the Dockerfile reference, "Scope" and "Understand how ARG and FROM interact"."""
    g, built = stages("ARG V=1\nARG W\nFROM a AS one\nARG V\nARG L=x\nENV E=${V}${L}\n"
                      "FROM one AS two\nENV E2=${L}\nFROM b\nARG L\nARG W\nENV E3=${V}${L}${W} E4=$V\n")
    assert g == {"V": "1", "W": ""}
    assert built[0].env == {"E": "1x"}
    assert built[1].env == {"E": "1x", "E2": "x"}, "a stage based on another inherits its ARGs and ENV"
    assert built[2].env == {"E3": "", "E4": ""} and built[2].args == {"L": "", "W": ""}, \
        "an unrelated stage sees neither the global V, which it does not declare, nor the other stage's L"


@pytest.fixture(scope="module")
def engine() -> str:
    names = [os.environ["CMAPI_CONTAINER_ENGINE"]] if os.environ.get("CMAPI_CONTAINER_ENGINE") else ["docker", "podman"]
    for name in names:
        found = shutil.which(name)
        if found and subprocess.run([found, "info"], capture_output=True, timeout=60).returncode == 0:
            return found
    if os.environ.get("CMAPI_REQUIRE_CONTAINER_ENGINE") == "1":
        pytest.fail(f"CMAPI_REQUIRE_CONTAINER_ENGINE=1 and none of {names} answers `info`")
    pytest.skip(f"none of {names} answers `info`")


def on_scratch(text: str) -> str:
    """The FROM, ARG, ENV and LABEL lines, each external base replaced by scratch: the build runs and pulls nothing."""
    names: set[str] = set()
    out = []
    for word, rest in instructions(text):
        if word == "FROM":
            tokens = [t for t in rest.split() if not t.startswith("--")]
            alias = tokens[2].lower() if len(tokens) == 3 else None
            out.append(f"FROM {tokens[0] if tokens[0].lower() in names else 'scratch'}" + (f" AS {alias}" if alias else ""))
            if alias:
                names.add(alias)
        elif word in ("ARG", "ENV", "LABEL"):
            out.append(f"{word} {rest}")
    return "\n".join(out) + "\n"


@pytest.mark.parametrize("path", CONTAINERFILES)
def test_the_model_agrees_with_a_real_builder(engine, path, tmp_path):
    text = (ROOT / path).read_text()
    (tmp_path / "Containerfile").write_text(on_scratch(text))
    r = subprocess.run([engine, "build", "-q", "-f", str(tmp_path / "Containerfile"), str(tmp_path)],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    image = r.stdout.split()[-1]
    try:
        r = subprocess.run([engine, "image", "inspect", "--format", "{{json .Config.Env}}", image],
                           capture_output=True, text=True, timeout=60, check=True)
    finally:
        subprocess.run([engine, "rmi", "-f", image], capture_output=True, timeout=60)
    real = dict(e.partition("=")[::2] for e in json.loads(r.stdout) or [])
    model = stages(text)[1][-1].env
    assert {k: real.get(k) for k in model} == model


def test_the_image_env_turns_the_start_check_on_and_the_pinned_cli_passes_it(tmp_path, monkeypatch):
    """With the environment the image sets, kyvernoVersion is the pin, the pinned CLI passes the start check, and
    another CLI stops the start (core/validate/__init__.py)."""
    kyverno = shutil.which("kyverno")
    if not kyverno:
        if os.environ.get("CMAPI_REQUIRE_KYVERNO") == "1":
            pytest.fail("CMAPI_REQUIRE_KYVERNO=1 and no kyverno on PATH")
        pytest.skip("no kyverno on PATH")
    pin = pinned_kyverno()
    monkeypatch.setenv("CMAPI_KYVERNO_VERSION", stages((ROOT / "cmapi/Containerfile").read_text())[1][-1].env[
        "CMAPI_KYVERNO_VERSION"])
    policy = PolicySettings()
    assert policy.view({"rnd"})["kyvernoVersion"] == pin
    CliValidator(tmp_path, kyverno=kyverno, policy=policy, environments={"rnd"})
    other = tmp_path / "kyverno-other"
    other.write_text("#!/bin/sh\necho 'Version: v1.19.9'\n")
    other.chmod(0o755)
    with pytest.raises(PolicyEngineMissing, match=rf"is not the pinned {re.escape(pin)} \(Version: v1.19.9\)"):
        CliValidator(tmp_path, kyverno=str(other), policy=policy, environments={"rnd"})
