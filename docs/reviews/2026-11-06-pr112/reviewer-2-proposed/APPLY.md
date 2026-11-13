# Applying reviewer 2's patches

On a clean checkout of `be66382`, from the repository root, in this order:

```sh
for p in 01-stored-requirement-test-moves-to-service \
         02-a-row-with-no-group-path-is-the-old-constant \
         03-measurements-fail-closed \
         04-a-failed-hash-read-is-not-zero-hashes \
         05-a-name-in-base64-is-still-a-name \
         06-the-bind-user-reads-groups-before-any-write \
         07-old-groups-stay-until-the-new-set-is-proven \
         08-removal-leaves-what-it-did-not-write \
         09-a-failed-openssl-makes-no-secret \
         10-mac-ca-keeps-working-with-an-extra-ca \
         11-apply-bind-user-a-failed-read-is-not-a-pass; do
  patch -p1 --fuzz=0 < "output/final/$p.patch" || break
done
```

No patch creates a file or changes a mode. Each builds on the one before it, so they do not apply out of order. Reviewer 1's two patches are replaced by 03 and 04: do not apply those as well. Its measurements patch does not apply at `--fuzz=0`.

## Who wrote what

All eleven: reviewer 2, Opus 5.5 at `high`. 03 and 04 start from reviewer 1's (Codex) snippets: 04's script change is reviewer 1's unchanged, and 03 keeps its host-side check and its gate check and replaces its digest pipeline.

## The fast check

```sh
CONTAINER=podman deploy/tests/ldap-identities-test.sh failures   # the new cases alone, one container, about 3 minutes here. It says that no mutant ran.
CONTAINER=podman deploy/tests/ldap-identities-test.sh            # everything, with the mutants: what CI runs, with docker
```

To see them fail before: keep this set's test file and put back `be66382`'s `apply-test-identities.sh` and `apply-bind-user.sh`.
