# Reviewer 1

## HIGH — LDAP measurements can disappear or hash empty input and still pass

`repo/examples/cmapi-sso/ldap/apply-test-identities.sh:118-134`

The `others` and `gate` digests are pipelines whose status is the final `sed`, not `sha256sum` or `grep`. If digest production fails, `others=` can be absent before and after; `same_rest` compares two empty `value_of` results and reports success. If the gate search succeeds but returns no readable membership attribute, line 121 hashes empty input and treats that hash as proof of the gate. A write can therefore continue or be accepted without either proof being computable. The fix validates each measurement inside `measure()`, so an invalid before-measurement stops before a write.

Command and output before the fix:

```text
$ output/tests/ldap-measurements-fail-closed.sh repo/examples/cmapi-sso/ldap/apply-test-identities.sh
FAIL: measurement proof is not fail-closed (6 required guards absent)
$ echo $?
1
```

Exact fix:

```sh
grep -iE "^(member|uniqueMember):" "$w/gate" > "$w/gate-members" || true
[ -s "$w/gate-members" ] || { echo "FAIL: the gate group $2 has no readable members: a digest of nothing would prove nothing" >&2; exit 1; }
LC_ALL=C sort "$w/gate-members" | sha256sum | cut -d" " -f1 | sed "s/^/gate=/"
```

```sh
in_pod "$measure_prog" _ "$2" "$gate_dn" <"$1" > "$tmp/measured"
for key in others gate idp idp_cmapi; do
  [ "$(grep -c "^$key=" "$tmp/measured" || true)" = 1 ] || die "measurement $key is missing or repeated"
  [ -n "$(sed -n "s/^$key=//p" "$tmp/measured")" ] || die "measurement $key is empty"
done
cat "$tmp/measured"
```

Patch: [`fixes/ldap-measurements-fail-closed.patch`](fixes/ldap-measurements-fail-closed.patch)

Test: [`tests/ldap-measurements-fail-closed.sh`](tests/ldap-measurements-fail-closed.sh)

After applying the patch to a scratch copy with `patch -p1`:

```text
$ output/tests/ldap-measurements-fail-closed.sh output/patch-check-revised/repo/examples/cmapi-sso/ldap/apply-test-identities.sh
PASS: empty gate input and absent measurement fields are rejected
```

## HIGH — a failed password-attribute read is accepted as proof that no hash is readable

`repo/examples/cmapi-sso/ldap/apply-test-identities.sh:307-315`

`as_bind_prog` has `set -u`, not `pipefail`. If the line-313 `ldapsearch` fails, `grep -ci` prints `0`; `check` compares that with expected `0`, leaves `fail=0`, and the pod program exits successfully. The run therefore accepts a failed LDAP read as proof that the bind user cannot read password hashes.

Command and output before the fix:

```text
$ output/tests/ldap-bind-password-read-fail-closed.sh repo/examples/cmapi-sso/ldap/apply-test-identities.sh
FAIL: password-hash visibility proof can accept an LDAP read failure (3 required guards absent)
$ echo $?
1
```

Exact fix:

```sh
f=$(mktemp); result="$f.result"; trap "rm -f \"$f\" \"$result\"" EXIT; cat > "$f"
```

```sh
as_bind -b "ou=People,$LDAP_BASE_DN" "(uid=cmapi.*)" userPassword > "$result" || { echo "FAIL: the bind user could not check whether a password hash is readable" >&2; exit 1; }
check "the bind user sees no password hash" "$(grep -ci "^userPassword" "$result" || true)" 0
```

Patch: [`fixes/ldap-bind-password-read-fail-closed.patch`](fixes/ldap-bind-password-read-fail-closed.patch)

Test: [`tests/ldap-bind-password-read-fail-closed.sh`](tests/ldap-bind-password-read-fail-closed.sh)

After applying the patch to the same scratch copy with `patch -p1`:

```text
$ output/tests/ldap-bind-password-read-fail-closed.sh output/patch-check-final/repo/examples/cmapi-sso/ldap/apply-test-identities.sh
PASS: LDAP read must succeed before zero visible password hashes is accepted
```

Both patches applied in sequence with `patch -p1`; the patched script also passed `sh -n`.

## Unproven worries

- None.

## Verdicts

1. **REFUTED** — the two HIGH findings above. Commands: the two finding tests. The focused before/after run ended with `BEFORE measurements_rc=1 bind_rc=1` and `AFTER syntax_rc=0 measurements_rc=0 bind_rc=0`.
2. **NOT REFUTED** — command: `output/tests/verdicts.py 2`. Output: `PASS claim2 groups=10 user_role_unions=13 approval_group=app-cmapi-rbac-approver-platform legacy_paths=0 stored_path_accepts_inside_rejects_outside=true`.
3. **NOT REFUTED** — command: `output/tests/verdicts.py 3`. Output: `PASS claim3 failed_or_empty_rejected=5 exact_13=true wrong_14=false PUT_absent=[] PUT_present=[filter]`.
4. **NOT REFUTED** — command: `output/tests/verdicts.py 4`. Output: `PASS claim4 mode=remove-test-identities input=new_group_dns+new_user_dns recursive=false trusted_apps=false`.
5. **NOT REFUTED** — command: `output/tests/verdicts.py 5`. Output: `PASS claim5 syntax=true token_fail_path=true viewer_control_first=true secrets_via_stdin=true`.
6. **NOT REFUTED** — command: `output/tests/verdicts.py 6`. Output: `PASS claim6 pipeline_stop=true next_step_gate=true trust=one-cert,CA,fingerprint,ssl-only`.

Not tested: the nine-minute OpenLDAP integration test; a live OpenLDAP or Keycloak; any cluster, `oc` server, CRC, kubeconfig, browser, or macOS keychain operation. No container was started. Testing was limited to the named files, local syntax/assertion tests, extracted pure functions, and patch application to scratch copies.
