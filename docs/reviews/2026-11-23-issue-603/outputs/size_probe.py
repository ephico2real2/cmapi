"""#603 probe: 0009 on 200,000 rows, and the lookup's plans at 0008 (release 1's statements) and at 0009 (this code's).

Run from cmapi/ with PYTHONPATH=src. Uses the schema `probe603` of the database in CMAPI_PROBE_URL, and drops it after."""
import json
import os
import subprocess
import sys

import psycopg

BASE = os.environ["CMAPI_PROBE_URL"]
URL = BASE + "?options=-csearch_path%3Dprobe603"
MIG = "import sys; from cmapi.core.db.migrate import run; run(sys.argv[1:])"


def migrate(*args):
    p = subprocess.run([sys.executable, "-c", MIG, *args], env={**os.environ, "CMAPI_DATABASE_URL": URL},
                       capture_output=True, text=True)
    assert p.returncode == 0, (p.stdout + p.stderr)[-1500:]
    return next(json.loads(line) for line in p.stdout.splitlines() if '"migrated"' in line)


def plan(c, sql):
    c.execute("BEGIN")
    rows = c.execute("EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON) " + sql).fetchall()
    c.execute("ROLLBACK")
    return "\n".join("    " + r[0] for r in rows)


with psycopg.connect(BASE, autocommit=True) as c:
    c.execute("DROP SCHEMA IF EXISTS probe603 CASCADE")
    c.execute("CREATE SCHEMA probe603")
print("0008:", migrate("0008")["revision"])
with psycopg.connect(URL, autocommit=True) as c:
    # 200,000 rows: 120,000 keyed by release 1's code (person's own and a service's for a person), 2,000 keyed by 0007
    # pods (no idempotency_sub), 30,000 expired keys, the rest with no key.
    c.execute("""
        INSERT INTO change_requests (request_id, instance, cluster_id, namespace, env, plugin, action, status, plan,
               plan_hash, requester, requester_sub, requester_kind, requester_client, requester_username, idempotency_key,
               idempotency_fingerprint, idempotency_sub, created_at)
        SELECT 'req-' || i, 'test', 'CRC', 'ns-' || i, 'dev', 'namespaces', 'create', 'cancelled', '{}', 'h',
               CASE WHEN i % 3 = 0 THEN jsonb_build_object('requester', jsonb_build_object('sub', 'sub-p' || (i % 5000)),
                         'submittedBy', 'svc', 'submittedBySub', 'sub-svc' || (i % 50), 'submittedByClient', 'svc')
                    ELSE jsonb_build_object('requester', jsonb_build_object('sub', 'sub-p' || (i % 5000))) END,
               'sub-p' || (i % 5000), 'user', 'c', 'p' || (i % 5000),
               CASE WHEN i <= 152000 THEN 'key-' || i END,
               CASE WHEN i <= 152000 THEN 'fp-' || i END,
               CASE WHEN i <= 150000 AND i > 30000 THEN
                    CASE WHEN i % 3 = 0 THEN 'sub-svc' || (i % 50) ELSE 'sub-p' || (i % 5000) END END,
               CASE WHEN i <= 30000 THEN now() - interval '30 hours' ELSE now() - make_interval(secs => i % 80000) END
          FROM generate_series(1, 200000) i""")
    c.execute("ANALYZE change_requests")
    print("rows:", c.execute("SELECT count(*), count(idempotency_key), count(idempotency_key) FILTER (WHERE idempotency_sub IS NULL), "
                             "count(*) FILTER (WHERE idempotency_key IS NOT NULL AND created_at < now() - interval '24 hours') "
                             "FROM change_requests").fetchone(), "(all, keyed, keyed with no caller, expired keys)")
    # Release 1's statements (repo.py at cb59e19), for the caller of req-90000 (a service, every third row).
    print("\n0008, release 1's expiry UPDATE (every expired row of the key):")
    print(plan(c, "UPDATE change_requests SET idempotency_key = NULL, idempotency_fingerprint = NULL, idempotency_sub = NULL "
                  "WHERE idempotency_key = 'key-90000' AND created_at < now() - interval '24 hours'"))
    print("\n0008, release 1's SELECT (key_owner):")
    print(plan(c, "SELECT * FROM change_requests WHERE idempotency_key = 'key-90000' AND coalesce(idempotency_sub, "
                  "requester ->> 'submittedBySub', requester_sub) = 'sub-svc0' ORDER BY created_at, request_id LIMIT 1"))

e = migrate("head")
print("\n0009 on these rows:", json.dumps({k: e[k] for k in ("from_revision", "revision", "applied", "transaction_seconds",
                                                                  "total_seconds")}))
with psycopg.connect(URL, autocommit=True) as c:
    c.execute("ANALYZE change_requests")
    print("after 0009:", c.execute("SELECT count(idempotency_key), count(idempotency_key) FILTER (WHERE idempotency_sub IS NULL) "
                                   "FROM change_requests").fetchone(), "(keyed, keyed with no caller)")
    print("\n0009, this code's expiry UPDATE (the caller's row):")
    print(plan(c, "UPDATE change_requests SET idempotency_key = NULL, idempotency_fingerprint = NULL, idempotency_sub = NULL "
                  "WHERE idempotency_sub = 'sub-svc0' AND idempotency_key = 'key-90000' "
                  "AND created_at < now() - interval '24 hours'"))
    print("\n0009, this code's SELECT:")
    print(plan(c, "SELECT * FROM change_requests WHERE idempotency_sub = 'sub-svc0' AND idempotency_key = 'key-90000'"))
e = migrate("0008", "--downgrade")
print("\n0009 downgrade on these rows:", json.dumps({k: e[k] for k in ("from_revision", "revision", "transaction_seconds")}))
with psycopg.connect(BASE, autocommit=True) as c:
    c.execute("DROP SCHEMA probe603 CASCADE")
