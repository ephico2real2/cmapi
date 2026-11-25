# PR #667 (closes #650): reviewer 1 report

Reviewer 1: Fable 5.2, adversarial, 2026-11-25. Head `5769429`, base `160bd83`. Opus 5.5 wrote the change; I did not.
Everything here ran in the export `review-667/`. No image was built or run. The cluster was read only for five
namespaces' annotations. No git repository and nothing on GitHub was written.

## Result

The check works as built: CI shows it refusing a 0600 file in three jobs and passing after the revert, and the Containerfile
diff adds no `chmod` or `chown`. Four findings, none High. The fix for all of them is one patch,
`r1-outputs/fix.diff` (329 lines, 8 files), which applies to a fresh copy of `head/` with `patch -p1 -F0`.

| # | Severity | Finding | Test, before the fix | After |
|---|---|---|---|---|
| R1-1 | Medium | `ci-guard.py` compares clauses of the RUN, not the RUN: 7 weakened checks pass it | 7 mutants survive | killed |
| R1-2 | Low | The guard cannot place a `COPY` destination given through a variable or in the JSON form, and counts it as inside | 2 mutants survive | killed |
| R1-3 | Medium | UID 1000690000 is not mapped in a rootless build, so `podman build` (`deploy/release-crc.sh:57`) stops at the new RUN. Inferred, not built | guard case fails for 1000690000 | passes for 54321 |
| R1-4 | Low | The check skips links, so a link to an unreadable file outside the checked paths passes | 4 of 30 cases fail | 30 of 30 pass |
| R1-5 | Low | Three statements in the record are wrong or unproven | see below | corrected in the README |

**Not tested, and it matters:** no image has been built with the patch. The UID change and the new link clause run first
in CI on the patched head. The lines to read are `image modes (#650)` in `images-pr` (both) and `front-door`.

## Sources, each read 2026-11-25

Saved copies are in `r1-outputs/sources/`.

- **OpenShift, "Support arbitrary user ids"**, openshift-docs `modules/images-create-guide-openshift.adoc`, last commit
  `6afb7b34d9` (2026-10-22), <https://raw.githubusercontent.com/openshift/openshift-docs/main/modules/images-create-guide-openshift.adoc>:
  "By default, {product-title} runs containers using an arbitrarily assigned user ID." "For an image to support running as
  an arbitrary user, directories and files that are written to by processes in the image must be owned by the root group and
  be read/writable by that group. Files to be executed must also have group execute permissions." Example: `RUN chgrp -R 0
  /some/directory && chmod -R g=u /some/directory`. "Because the container user is always a member of the root group, the
  container user can read and write these files."
- **`restricted-v2` SCC**, openshift-docs `modules/security-context-constraints-about.adoc`,
  <https://raw.githubusercontent.com/openshift/openshift-docs/main/modules/security-context-constraints-about.adoc>. The
  `restricted` SCC: "Requires that a pod is run as a user in a pre-allocated range of UIDs", "Requires that a pod is run with
  a preallocated FSGroup", "Allows pods to use any supplemental group". `restricted-v2`: "Like the `restricted` SCC, but
  with the following differences: `ALL` capabilities are dropped from containers." And
  `modules/security-context-constraints-pre-allocated-values.adoc`: "A `RunAsUser` strategy of `MustRunAsRange` with no
  minimum or maximum set. Admission looks for the `openshift.io/sa.scc.uid-range` annotation to populate range fields."
  "`MustRunAsRange` and `MustRunAs` (range-based) strategies provide the minimum value of the range." So the SCC does supply
  a group: the namespace's `fsGroup`, as a supplementary group of the pod.
- **Dockerfile reference, USER**, moby/buildkit `frontend/dockerfile/docs/reference.md`,
  <https://raw.githubusercontent.com/moby/buildkit/master/frontend/dockerfile/docs/reference.md>: "`USER <UID>[:<GID>]`";
  "The specified user is used for `RUN` instructions and at runtime runs the relevant `ENTRYPOINT` and `CMD` commands.";
  "Note that when specifying a group for the user, the user will have _only_ the specified group membership. Any other
  configured group memberships will be ignored."; "When the user doesn't have a primary group then the image (or the next
  instructions) will be run with the `root` group." Containerfile(5), containers/common: "USER [user | user:group | uid |
  uid:gid | user:gid | uid:group ]".
- **coreutils, "Copying Existing Permissions"**. www.gnu.org refused the connection twice (curl timeout, then
  `ECONNREFUSED 209.51.188.116:443`), so I read the manual's source in the coreutils mirror,
  <https://raw.githubusercontent.com/coreutils/coreutils/master/doc/perm.texi>: "instead of using a series of 'r', 'w', or
  'x' letters after the operator, you use the letter 'u', 'g', or 'o'"; "If the file had started out as mode 741
  (rwxr----x), the above mode would change it to mode 745 (rwxr--r-x). The '-' and '=' operations work analogously." And
  `doc/coreutils.texi`: "chmod ignores symbolic links encountered during recursive directory traversals." I did not verify
  the record's version number, 9.12.
- **nginx-unprivileged**, nginxinc/docker-nginx-unprivileged at `main`, `stable/alpine-slim/Dockerfile` and `entrypoint/`:
  the Dockerfile itself runs `chown -R $UID:0 /etc/nginx && chmod -R g+w /etc/nginx` (lines 124-125), comment "nginx user
  must own the cache and etc directory to write cache and tweak the nginx config". `20-envsubst-on-templates.sh:42-44`:
  `if [ ! -w "$output_dir" ]; then entrypoint_log "$ME: ERROR: $template_dir exists, but $output_dir is not writable";
  return 0`. `30-tune-worker-processes.sh:12`: `touch /etc/nginx/nginx.conf 2>/dev/null || { echo >&2 "$ME: error: can not
  modify /etc/nginx/nginx.conf (read-only file system?)"; exit 0; }`, and line 188 edits with `sed -i.bak`, a new file in
  `/etc/nginx`. `docker-entrypoint.sh` sources or runs a script only `if [ -x "$f" ]`.
- **Podman, troubleshooting 10**, <https://raw.githubusercontent.com/containers/podman/main/troubleshooting.md>: "rootless
  setup user: invalid argument ... A user, either via --user or through the default configured for the image, is not mapped
  inside the namespace. `$ podman run --rm -ti --user 1000000 alpine echo hi` Error: container create failed: ... "setup
  user: invalid argument"". setuid(2), <https://man7.org/linux/man-pages/man2/setuid.2.html>: "EINVAL The user ID specified
  in uid is not valid in this user namespace." shadow `etc/login.defs`: `SUB_UID_COUNT 65536`.

## The record's quotes, verified

| Claim in `docs/reviews/2026-11-25-issue-650/` | Result |
|---|---|
| Starlette 1.10.0: start at `responses.py:427`, open at `:433`; ranges 446/450 and 474/478; `staticfiles.py:124-125`, `os.stat` at `:176` | Confirmed in the installed 1.10.0 file |
| Starlette main at `63d868e` (2026-11-22): lines 429 and 435 | Confirmed: `63d868e1b8`, 2026-11-22T13:18:34Z; also 448/452 and 476/480. The start-before-open order is real in both |
| #1220 merged 2021-10-05; #3594 closed unmerged by its author 2026-10-06 | Confirmed by the GitHub API (closed by `HassanRady`, the author) |
| `docs/contributing.md` "Potential Issue"; `blank_issues_enabled: false` | Confirmed |
| OpenShift quotes at `6afb7b34d9` (2026-10-22) | Confirmed, word for word |
| Dockerfile USER quotes | Confirmed |
| coreutils quotes | Confirmed in the manual's source; the version not verified |
| Alpine 3.24 busybox: `FIND_EXEC_PLUS`, `FIND_PERM`, `FIND_NOT`, `FIND_PAREN` | Confirmed; also `FIND_TYPE`, `MKTEMP` |
| cmapi base has GNU find, 291,760 bytes | Confirmed in the pinned base's layers |
| CI: mutant run 45549565321 failed on `6eca40b`, run 45551885303 passed on `fd5eeae`, the quoted lines and job numbers | Confirmed from the logs (`r1-outputs/ci-log-*.txt`). Head run 45554471919 on `5769429`: success, same lines |
| "A pod's `fsGroup` or supplemental groups can only add access" | Not true in general, true here: see R1-5 |
| The Containerfile comment gives "has no capabilities" to the image guidelines | The guidelines do not say it; the SCC page does |
| The upstream draft's line ranges (428-435 main, 426-433 in 1.10.0) | Consistent: they run from the `def` to the open |

## The five questions

### 1. Does the check model the real runtime?

- **Is `1000690000:0` what CRC assigns? No.** Measured on CRC (`oc get ns <ns> -o jsonpath='{.metadata.annotations}'`):

  | Namespace | `openshift.io/sa.scc.uid-range` | `sa.scc.supplemental-groups` |
  |---|---|---|
  | `cmapi` | 1000720000/10000 | 1000720000/10000 |
  | `cmapi-system` | 1000810000/10000 | 1000810000/10000 |
  | `cmap-live-g-dev` | 1000830000/10000 | 1000830000/10000 |
  | `cmapi-live-a` | 1000790000/10000 | 1000790000/10000 |
  | `cmapi-imports` | 1000800000/10000 | 1000800000/10000 |

  By the SCC page a pod in `cmapi` runs as 1000720000 unless it asks for another UID of the range.
- **Does a different UID change anything? No**, as long as it owns no file. The kernel picks the owner's bits only when the
  UID owns the file, else the group's bits when one of the process's groups is the file's. The pinned bases' files belong to
  UIDs 0 and 1001 (cmapi) and 0 and 101 (the portal), read from their layers (`r1-outputs/base-layers-*.txt`). The decisive
  run is the implementer's: in run 45549565321 a 0600 file owned by 1001 (and by 101) was refused.
- **Are supplementary groups added?** In the build, no: with `USER uid:gid` the user has "only the specified group
  membership". In a pod under `restricted-v2`, yes: the namespace's `fsGroup`. It takes nothing away here, because no file
  of either image has that GID (the bases' GIDs are 0, 12 and 42). I did not read a pod's groups on CRC: the brief limits
  cluster reads to namespaces.
- **A second runtime, not modelled:** kind and plain Docker run the image as its own user (1001, 101), the owner. The
  owner is refused where the arbitrary UID is not only on a file whose owner bits are less than its group bits. `chmod -R
  g=u` rules that out for `/opt/app-root`, and the bases' modes under the portal's paths are 644, 664, 755 and 775. No fix
  proposed; the README now says it.

### 2. Can the check pass while the real image still fails?

- **A COPY after the check:** refused by the guard (implementer's mutants 3, 11, 13; confirmed).
- **A later stage:** refused. I appended `FROM scratch` and `COPY --from=1 / /`: three cases fail, before and after my
  patch (`r1-outputs/guard-later-stage.txt`).
- **Symlinks: yes, a gap.** R1-4.
- **Files outside the checked paths.** cmapi also uses `/usr/bin/git`, `ssh`, `libnss_wrapper.so` and `/etc/passwd`. The
  Containerfile already asserts `/etc/passwd` is 644, and the rest are RPM files that no instruction of the Containerfile
  touches. The guard's COPY rule keeps new files inside the checked paths, once R1-2 is fixed. No finding.
- **Runtime mounts: acceptable.** The image cannot know them. In `deploy/manifests` the only mount over an image path is
  the portal's `config.json` by `subPath`, a ConfigMap with the default mode, served by nginx and not by Starlette. Nothing
  mounts over `/opt/app-root/static`. The Secret mounts with `defaultMode: 0440` sit under `/etc/cmapi/git-bot*` and are
  read by the worker, not served.

### 3. Can the check fail falsely?

- **Build cache:** a cached RUN is keyed by its parent layers and its text, so a cache hit means the same files and modes.
  Reasoned, not tested.
- **Files meant to be unreadable:** neither image holds one; secrets arrive by mounts. A key added to the image under a
  checked path would fail the build, which is the right answer.
- **The nginx writes:** right and safe. The entrypoint's scripts do write there and fail silently when they cannot (quotes
  above). The diff adds no `chmod` or `chown`: `cmapi-portal-ui/Containerfile:55` is unchanged context, and the pinned base
  already has `/etc/nginx` 775, `conf.d` 775 and `nginx.conf` 664, owner 101, group 0, as upstream's own Dockerfile sets.
  The check asserts a permission; it grants none.
- **A new false failure: yes**, R1-3, in a rootless build.

### 4. Over-build

Ruling: the implementer's argument holds. A `find -perm -g=r` as root passes a file of group 1001 with `g+r`, which the
arbitrary UID cannot read, and says nothing of a directory without `x` above the file. To be right it would have to restate
the kernel's rule (owner, group, other, each ancestor, capabilities). The RUN is shorter than that and cannot disagree with
the kernel. The canary is the price of asking the kernel, one line. The part that had grown past its need was the guard's
clause list, which R1-1 replaces with one comparison.

### 5. `ci-guard.py`

All 14 of the implementer's mutants are killed, each by the case that names the weakness
(`r1-outputs/guard-mutants-before.txt`). Nine weakenings still passed. R1-1 and R1-2.

## Findings

### R1-1 (Medium): the guard compares clauses, not the RUN

`deploy/tests/ci-guard.py:180-195` at the head requires seven substrings in the RUN. A RUN that holds all seven and never
reads a mode passes. The portal's write check is in no clause at all.

Survivors at `5769429` (`python r1-outputs/guard-mutants-r1.py head <python>`, exit 1, `survivors: 9`: these seven and R1-2's two):

1. portal: the write check removed
2. cmapi: `bad="";` before `if [ -n "$bad" ]`
3. cmapi: `exit 0;` after `set -eu;`
4. cmapi: the finds inside `if false; then ... fi`
5. cmapi: `paths="/opt/app-root /etc/cmapi /usr/local/bin -maxdepth 0"`, so find reads three directories and stops
6. cmapi: `/etc/cmapi` narrowed to `/etc/cmapi/policies`
7. portal: `/docker-entrypoint.sh` dropped from `paths`

**Fix** (`fix.diff`, `deploy/tests/ci-guard.py`): `modes_run(paths, more, wrote)` builds the whole RUN for each image, and
the case is `" ".join(run.split()) == modes_run(...)`. The paths and the portal's write clause now live in the guard, so
changing the check means changing the guard in the same pull request.

**Test:** `guard-mutants-r1.py` on the patched tree: 25 mutants, `survivors: 0` (`r1-outputs/guard-mutants-after.txt`). The
record's own probe, `probes/guard-mutants.py`, has the same 25 and its output is regenerated in the patch.

### R1-2 (Low): a COPY destination the guard cannot place counts as inside

`ci-guard.py:206-207` joins the last word of a COPY to the WORKDIR. `ENV OUT=/srv` then `COPY policies $OUT/policies`
becomes `/opt/app-root/src/$OUT/policies`, inside. The JSON form becomes `/opt/app-root/src/"/srv/policies"]`, inside.

**Fix:** a destination with `$` in it, or a COPY in the JSON form, is listed as outside.
**Test:** mutants "a COPY to a variable outside the checked paths" and "a JSON-form COPY outside the checked paths": both survive before, both killed after.

### R1-3 (Medium): UID 1000690000 is not mapped in a rootless build

- Measured on this Mac: `podman info --format '{{.Host.Security.Rootless}} {{.Host.IDMappings.UIDMap}}'` gives `true` and
  `[{0 501 1} {1 100000 1000000}]`. The build has UIDs 0 to 1000000. Shadow's default is 65536.
- Podman's guide names the result: "setup user: invalid argument".
- `deploy/release-crc.sh:57` and `:63` run `podman build` on these Containerfiles, and the portal's Containerfile gives the
  command in its header.
- **Inferred, not measured:** I built nothing, by the owner's rule. CI is not affected: its BuildKit is rootful.
- The large UID buys nothing: it is not in any `cmapi` namespace's range, and question 1 shows any UID that owns nothing
  answers alike.

**Fix:** `USER 54321:0` in both Containerfiles, with the reason in the comment. The guard holds `MODES_USER` to group 0,
`0 < uid < 65534`, and not 1001 or 101. 65534 is excluded because it is the overflow UID that unmapped owners show as.

**Test:** with `MODES_USER` and both Containerfiles set to `1000690000:0`, the guard fails one case, "the modes check's user
(1000690000:0) is in group 0, is not an image's own user, and is a UID that a rootless build maps"
(`r1-outputs/guard-uid-bound.txt`); with 54321 it passes. This tests the bound, not a build.

### R1-4 (Low): links are skipped

`find $paths ! -type l` never reads a link, and the search-or-run find takes `-type d` and `-type f` only. A link under a
checked path to an unreadable file outside them passes. Exposure today is small: the bases' five links under the checked
paths end at readable targets, and the build context has no link.

**Fix**, one line in each RUN:

```
find $paths -type l -exec sh -c 'for p; do [ ! -e "$p" ] || [ -r "$p" ] || echo "cannot read $p (a link: its target)"; done' sh {} +; \
```

A dangling link stays allowed. Not caught: a link whose target sits in a directory the user cannot search, which looks
dangling; if that directory is under a checked path, the directory itself is reported.

**Test:** `python3 r1-outputs/modes-check-test.py <tree>` takes each RUN from the Containerfile, moves its paths under a
temporary root, and runs it under `/bin/sh` and `/bin/dash` on eight trees. At the head: `cases failed: 4`, the link case
in both images and both shells (`modes-check-before.txt`). Patched: `cases failed: 0` (`modes-check-after.txt`). It runs as
the trees' owner, so it proves the logic and not group 0.

### R1-5 (Low): the record

- "A pod's `fsGroup` or supplemental groups can only add access": a group can remove access from a file it owns that gives
  the group less than others. True for these images only because no file has such a GID. Reworded, with the source.
- "as OpenShift runs it" for 1000690000: CRC's ranges are measured above and do not hold it. The README now gives them.
- "fails 6 cases" on main: 4 with the patched guard, which no longer reads the paths from the check. Updated, and
  `guard-before.txt`, `guard-after.txt` and `guard-mutants.txt` are regenerated from the patched tree.

The CI outputs in the record stay as they are: they are true of UID 1000690000 and the README says so.

## What the patch changes

| File | Change |
|---|---|
| `cmapi/Containerfile`, `cmapi-portal-ui/Containerfile` | `USER 54321:0`; the link clause; the comment |
| `deploy/tests/ci-guard.py` | the whole-RUN comparison, the UID's bounds, the COPY rule |
| `docs/reviews/2026-11-25-issue-650/README.md` | the corrections and a "Review 1" section |
| `.../probes/guard-mutants.py`, `.../outputs/guard-{before,after,mutants}.txt` | 25 mutants; outputs regenerated |

Verified on a fresh copy of `head/` after `patch -p1 -F0`: `ci-guard.py` ends `ci cases failed: 0`, the mutant run ends
`survivors: 0`, the modes cases end `cases failed: 0`, and the copy equals my working tree.

## Not tested

- No build with the patch, on any builder. CI on the new head decides R1-3's UID and R1-4's clause in the real images.
- A rootless `podman build` of the head, which R1-3 predicts fails.
- The canary's refusal: it needs a build with `CAP_DAC_OVERRIDE`, which the guard forbids. It has never fired, in CI or here.
- A pod's actual groups on CRC.
- The layers that the build adds (pip's packages, the portal's `dist`): I read the bases' layers only.

## Files

- `review-667/r1-outputs/fix.diff`
- `review-667/r1-outputs/guard-mutants-r1.py`, `guard-mutants-before.txt`, `guard-mutants-after.txt`
- `review-667/r1-outputs/modes-check-test.py`, `modes-check-before.txt`, `modes-check-after.txt`
- `review-667/r1-outputs/guard-uid-bound.txt`, `guard-later-stage.txt`
- `review-667/r1-outputs/base-layers-cmapi.txt`, `base-layers-portal.txt`
- `review-667/r1-outputs/ci-log-45549565321.txt`, `ci-log-45551885303.txt`, `ci-log-45554471919.txt`
- `review-667/r1-outputs/sources/`
