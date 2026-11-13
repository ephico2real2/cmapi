"""One paging, search, filter, sort and export contract for every list (docs/01, Lists).

Used by GET /api/v1/quotas, /requests, /expirations, /tiers/{tier}/namespaces, /policies/results and
any plugin's list. Rows are plain dicts with at least `name` and `clusterId`; they come from the
watch cache joined in memory, so this module never touches a cluster or the database.

    envelope   {items, page: {limit, total, from, to, nextCursor, prevCursor}, letters}
    cursor     keyset on (sort value, name, clusterId), signed, carrying a hash of filters and sort;
               reused after either changes -> 400 invalid-cursor
    limit      25, 50 (default) or 100, at most 200
    startsWith with sort=name, the page starts at the first name from that letter
    q / suggest  names starting with the text, then containing it, then team or app label matches
"""
from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator, Mapping

from cmapi.core.errors import Problem

LIMITS = (25, 50, 100)
MAX_LIMIT = 200
EXPORT_CAP = 10_000


@dataclass(frozen=True)
class ListQuery:
    q: str = ""
    filters: Mapping[str, str] = field(default_factory=dict)    # env=, clusterId=, team=, tier=, ...
    sort: str = "name"
    limit: int = 50
    cursor: str | None = None
    starts_with: str | None = None
    context: Mapping[str, str] = field(default_factory=dict)   # scope applied by the caller (status=, approver=me), bound into the cursor

    def key(self) -> str:
        """Hash of what the cursor depends on."""
        return hashlib.sha256(json.dumps({"q": self.q.lower(), "f": dict(sorted(self.filters.items())),
                                          "s": self.sort, "c": dict(sorted(self.context.items()))}).encode()).hexdigest()[:16]


@dataclass(frozen=True)
class Sorts:
    """Sort keys a list offers: name is always ascending; the others sort high-first."""
    extra: Mapping[str, Callable[[Mapping[str, Any]], float]] = field(default_factory=dict)

    def keyfn(self, sort: str) -> Callable[[Mapping[str, Any]], tuple]:
        if sort == "name":
            return lambda r: ("", r["name"], r["clusterId"])
        if sort not in self.extra:
            raise Problem.bad_request("invalid-sort", f"Unknown sort {sort}")
        f = self.extra[sort]
        return lambda r: (-f(r), r["name"], r["clusterId"])


def severity(used: float) -> int:
    """How urgent a namespace's quota is, from its highest use (used divided by hard): 3 at 95% or more, 2 at 80% or more, else 0.
    The portal's level 1 (a recommendation, idle or oversized) needs the usage analysis, which is not built."""
    return 3 if used >= 0.95 else 2 if used >= 0.8 else 0


def match_rank(row: Mapping[str, Any], text: str) -> tuple[int, str] | None:
    t = text.lower()
    name = row["name"].lower()
    if name.startswith(t):
        return 0, "name starts with"
    if t in name:
        return 1, "name contains"
    for label in ("team", "app"):
        v = str(row.get(label) or "").lower()
        if v and (v.startswith(t) or t in v):
            return 2, f"{label} {row.get(label)}"
    return None


class Lister:
    def __init__(self, secret: bytes, sorts: Sorts | None = None):
        self.secret, self.sorts = secret, sorts or Sorts()

    # ---- cursor
    def _sign(self, payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, separators=(",", ":")).encode()
        mac = hmac.new(self.secret, raw, hashlib.sha256).digest()[:12]
        return base64.urlsafe_b64encode(raw + mac).decode().rstrip("=")

    def _open(self, token: str, query: ListQuery) -> dict[str, Any]:
        try:
            blob = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
            raw, mac = blob[:-12], blob[-12:]
            if not hmac.compare_digest(mac, hmac.new(self.secret, raw, hashlib.sha256).digest()[:12]):
                raise ValueError("signature")
            payload = json.loads(raw)
        except Exception as exc:                                     # noqa: BLE001
            raise Problem.bad_request("invalid-cursor", "The cursor is not valid") from exc
        if payload.get("h") != query.key():
            raise Problem.bad_request("invalid-cursor", "Filters or sort changed since this cursor was issued")
        return payload

    # ---- the list
    def filtered(self, rows: Iterable[Mapping[str, Any]], query: ListQuery) -> list[Mapping[str, Any]]:
        out = []
        for r in rows:
            if any(str(r.get(k)) != v for k, v in query.filters.items() if v not in (None, "")):
                continue
            if query.q and match_rank(r, query.q) is None:
                continue
            out.append(r)
        return sorted(out, key=self.sorts.keyfn(query.sort))

    def page(self, rows: Iterable[Mapping[str, Any]], query: ListQuery,
             facets: Mapping[str, Callable[[Mapping[str, Any]], bool]] | None = None) -> dict[str, Any]:
        """facets: name -> predicate, counted over every row matching the filters (the quota view's
        attention counts: quota-tight, near-limit, recommendation, oversized, idle, open-request)."""
        if query.limit not in LIMITS and not (0 < query.limit <= MAX_LIMIT):
            raise Problem.bad_request("invalid-limit", f"limit is one of {LIMITS}, at most {MAX_LIMIT}")
        keyfn = self.sorts.keyfn(query.sort)
        ordered = self.filtered(rows, query)
        keys = [list(keyfn(r)) for r in ordered]
        total = len(ordered)
        if query.cursor:
            c = self._open(query.cursor, query)
            k = c["k"]
            if c["d"] == "next":
                start = next((i for i, kk in enumerate(keys) if kk > k), total)
                end_i = min(total, start + query.limit)
            else:                                       # prev: the rows strictly before the cursor
                end_i = next((i for i, kk in enumerate(keys) if kk >= k), total)
                start = max(0, end_i - query.limit)
        elif query.starts_with and query.sort == "name":
            s = query.starts_with.lower()
            start = next((i for i, r in enumerate(ordered) if r["name"].lower() >= s), total)
            end_i = min(total, start + query.limit)
        else:
            start, end_i = 0, min(total, query.limit)
        items = ordered[start:end_i]
        h = query.key()
        nxt = self._sign({"k": keys[end_i - 1], "d": "next", "h": h}) if items and end_i < total else None
        prv = self._sign({"k": keys[start], "d": "prev", "h": h}) if items and start > 0 else None
        letters: dict[str, int] = {}
        for r in ordered:
            ch = r["name"][:1].upper()
            letters[ch] = letters.get(ch, 0) + 1
        out = {"items": list(items),
               "page": {"limit": query.limit, "total": total, "from": start + 1 if items else 0,
                        "to": end_i, "nextCursor": nxt, "prevCursor": prv},
               "letters": letters}
        if facets:
            out["facets"] = {name: sum(1 for r in ordered if pred(r)) for name, pred in facets.items()}
        return out

    def suggest(self, rows: Iterable[Mapping[str, Any]], text: str, limit: int = 10) -> list[dict[str, Any]]:
        if len(text.strip()) < 2:
            return []
        ranked = []
        for r in rows:
            m = match_rank(r, text.strip())
            if m:
                ranked.append((m[0], r["name"], r["clusterId"], m[1]))
        ranked.sort()
        return [{"name": n, "clusterId": c, "why": why} for _, n, c, why in ranked[:limit]]

    def export_csv(self, rows: Iterable[Mapping[str, Any]], query: ListQuery,
                   columns: list[str]) -> Iterator[str]:
        """Same filters and order as the list, capped at 10,000 rows. The caller audits the export."""
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(columns)
        yield buf.getvalue()
        for i, r in enumerate(self.filtered(rows, query)):
            if i >= EXPORT_CAP:
                break
            buf.seek(0)
            buf.truncate()
            w.writerow([r.get(c, "") for c in columns])
            yield buf.getvalue()
