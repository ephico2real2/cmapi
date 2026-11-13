"""The portal's map of actions to endpoints agrees with the API contract (#186).

docs/diagrams/portal-architecture/README.md has one row for each action of the mockup, with the endpoint that it needs and
whether that endpoint is built. Wave 6 builds the portal from that map. cmapi/contract/openapi.json is the contract, and
another test keeps it equal to what the service serves. So a row that says built must name an operation of the document,
a row that says not built must name none, and the counts and the list of unused operations in the README must be true.
No database: two files.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
README = ROOT / "docs/diagrams/portal-architecture/README.md"
CONTRACT = ROOT / "cmapi/contract/openapi.json"
# Served by the API and left out of the document on purpose (main.py, include_in_schema=False).
OUTSIDE_THE_DOCUMENT = {"GET /docs", "GET /redoc"}
ENDPOINT = re.compile(r"`((?:GET|POST|PUT|PATCH|DELETE) /[^`]*)`")


def operations() -> set[str]:
    spec = json.loads(CONTRACT.read_text())
    return {f"{method.upper()} {path}" for path, item in spec["paths"].items() for method in item}


def section(title: str) -> str:
    text = README.read_text()
    start = text.index(f"## {title}\n")
    end = text.find("\n## ", start + 1)
    return text[start:end if end != -1 else len(text)]


def action_rows() -> list[tuple[str, list[str], list[str]]]:
    """Each action: its number, its endpoints and the status of each, in the order of the row."""
    rows = []
    for line in section("One row for each action").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 7 or not cells[0].isdigit():
            continue
        endpoints = [] if cells[3] == "None" else ENDPOINT.findall(cells[3])
        statuses = [s.strip() for s in cells[4].split("<br>")]
        rows.append((cells[0], endpoints, statuses))
    return rows


def count(item: str) -> int:
    found = re.search(r"^\| " + re.escape(item) + r" \| (\d+)", section("The counts"), re.M)
    assert found, f"the counts have no row `{item}`"
    return int(found.group(1))


def needed() -> dict[str, set[str]]:
    """Each endpoint that an action needs, with each status that the rows give it."""
    out: dict[str, set[str]] = {}
    for _, endpoints, statuses in action_rows():
        for endpoint, status in zip(endpoints, statuses):
            out.setdefault(endpoint, set()).add(status)
    return out


def test_each_row_has_one_status_for_each_endpoint():
    rows = action_rows()
    assert len(rows) == count("Actions in the mockup")
    for number, endpoints, statuses in rows:
        if not endpoints:
            assert statuses == ["No endpoint"], f"row {number}"
        else:
            assert len(statuses) == len(endpoints) and set(statuses) <= {"built", "not built"}, f"row {number}: {endpoints} {statuses}"
    assert sum(1 for _, endpoints, _ in rows if not endpoints) == count("Actions that make no call")


def test_an_endpoint_has_one_status_in_each_row_that_names_it():
    assert {e: s for e, s in needed().items() if len(s) != 1} == {}


def test_a_row_that_says_built_names_an_operation_of_the_contract_and_not_built_names_none():
    document = operations()
    wrong = []
    for endpoint, statuses in sorted(needed().items()):
        in_document = endpoint in document or endpoint in OUTSIDE_THE_DOCUMENT
        if statuses == {"built"} and not in_document:
            wrong.append(f"{endpoint}: the map says built, and the contract has no such operation")
        if statuses == {"not built"} and in_document:
            wrong.append(f"{endpoint}: the map says not built, and the contract has the operation")
    assert wrong == []


def test_the_counts_of_the_map_are_the_counts_of_its_rows():
    statuses = needed()
    built = {e for e, s in statuses.items() if s == {"built"}}
    assert len(statuses) == count("Endpoints that the actions need")
    assert len(built - OUTSIDE_THE_DOCUMENT) == count("Endpoints built, in `openapi.json`")
    assert len(built & OUTSIDE_THE_DOCUMENT) == count("Endpoints built, not in `openapi.json` (`/docs`, `/redoc`)")
    assert len({e for e, s in statuses.items() if s == {"not built"}}) == count("Endpoints not built")


def test_the_map_says_how_many_operations_the_contract_has():
    said = int(re.search(r"which has (\d+) operations", README.read_text()).group(1))
    assert said == len(operations())


def test_the_operations_that_no_action_calls_are_the_ones_that_the_map_lists():
    """The contract gains an operation: this fails until the map gives it an action or lists it as unused."""
    text = section("Built endpoints that no mockup action calls")
    said = int(re.search(r"these (\d+) operations", text).group(1))
    unused = operations() - set(needed())
    listed = set()
    for line in text.splitlines():
        if not line.startswith("- "):
            continue
        listed |= set(_expand(line[2:]))
    assert listed == unused, f"only in the map: {sorted(listed - unused)}; only in the contract: {sorted(unused - listed)}"
    assert said == len(unused)


def _expand(line: str) -> list[str]:
    """The operations of one list line. Forms: `GET /a`; `GET` and `DELETE /a`; `POST /a:cancel`, `:retry` and `:revert`."""
    out: list[str] = []
    methods: list[str] = []
    last: str | None = None
    for token in re.findall(r"`([^`]+)`", line):
        if token in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            methods.append(token)
        elif token.startswith(":") and last:
            method, path = last.split(" ", 1)
            out.append(f"{method} {path.rsplit(':', 1)[0]}{token}")
        else:
            method, path = token.split(" ", 1)
            for m in [*methods, method]:
                out.append(f"{m} {path}")
            methods, last = [], token
    return out
