# Issue #268: the backup's checks read the dump to its end

**The defect.** The first CRC run stopped at docs/13 step 13 on 2026-11-15T01:50Z (main 9407d8e4dd): `error executing command in container: write |1: broken pipe`, then `pg_restore --list refused the archive`. Nothing reached Keycloak; keycloak-0 and postgres-0 kept 0 restarts.

**Measured cause.** `deploy/crc-backup.sh` streams the dump into `oc exec -i postgres-0 -- sh -c '<check>'`. On PostgreSQL 16, with a 2,970,565-byte custom-format dump on stdin, `pg_restore --list` read 2,052 bytes and exited with rc 0, leaving 2,968,513 unread (`pg_restore --list >/dev/null; wc -c` in one exec). `pg_restore -a -t realm -f -` left the same. `pg_restore -f /dev/null` read it all. The shared Keycloak database is 14 MB, so its dump is far past a 64 KiB pipe buffer, and CRI-O's exec reports the stdin it could not write as an error, so `oc exec` exits non-zero. Podman's exec logs the same write error and still exits 0, which is why `deploy/tests/crc-backup-test.sh` passed; the stub in `crc-scripts-test.sh` drains stdin itself.

**Options.**
1. Drain stdin in the pod after each check, keeping the check's own status. Chosen: it fixes the cause (the exec stream must be consumed), keeps every check as it was, and writes nothing in the pod.
2. Read the archive once with `pg_restore -f -` and derive the count and the realm rows from that stream. Rejected: it rewrites three checks into one parser of pg_restore's SQL output, a larger change for the same result.
3. Copy the file into the pod and run `pg_restore --list` on a seekable file. Rejected: docs/13 holds that nothing is written in the pod.

**The test.** `crc-backup-test.sh`'s `oc` stand-in now fails an `exec -i` whose command leaves any stdin unread, as CRI-O does past the buffer (stricter: any byte), and the seed data makes a dump past 64 KiB (641,305 bytes, asserted). Before the fix, on 9407d8e's `deploy/`: 9 cases fail, the first with CRC's own message, `pg_restore --list refused the archive`. After: 0 fail. Logs: `ob1-run8/logs/268-backup-test-before.log`, `268-backup-test-after.log` in the run's workbench.

**Sources.** pg_restore's documentation: with no file name the archive is read from standard input, and `-l` lists the table of contents (https://www.postgresql.org/docs/16/app-pgrestore.html). Kubernetes #112834 on exec's stdin stream and its close ordering (https://github.com/kubernetes/kubernetes/issues/112834). The read sizes above are this run's measurements.
