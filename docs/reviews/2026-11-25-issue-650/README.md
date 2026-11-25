# #650: each image's build checks its modes as OpenShift's arbitrary UID in group 0

The implementer's record: Opus 5.5 at `high`, 2026-11-25, on `fix/650-static-file-modes` from `160bd83`. The reviews go
beside it when they are done.

## What is wrong

**Measured, 2026-11-25, on this Mac (macOS, Python 3.12.14, Starlette 1.10.0, uvicorn 0.32.1, as UID 501).** A StaticFiles
directory with a 100,000-byte file of mode 000, fetched through uvicorn on a raw socket (`probes/starlette_open_order_repro.py`, output in `outputs/repro-starlette-1.10.0.txt`):

```
HTTP/1.1 200 OK
content-type: text/javascript; charset=utf-8
accept-ranges: bytes
content-length: 100000
...
--- content-length 100000, body bytes received 0, then the connection closed
```

and uvicorn logs `PermissionError: [Errno 13] Permission denied` from `_open_file` (`responses.py:418`), called by
`_handle_simple` (`responses.py:433`). The issue's diagnosis holds on Starlette 1.10.0, which #654 moved cmapi to: nothing in
it is retracted. Only its line numbers moved: the Containerfile's `chown`/`chmod` is now line 105, not 97, and StaticFiles'
401 is `staticfiles.py:124-125`.

**Where it can happen in cmapi.** Not in the image as built before this change (`chown -R 1001:0 /opt/app-root && chmod -R
g=u /opt/app-root`), and no manifest mounts a volume over `/opt/app-root/static` (the mounts of `deploy/manifests` are under
`/etc/cmapi`, `/var/cache/cmapi/git`, `/tmp`, and the portal's `config.json`). It needs a build that changes those modes. That
is the cause, and nothing checked it.

## Sources

Each read 2026-11-25.

- **Starlette 1.10.0**, installed (`site-packages/starlette/responses.py`): `_handle_simple` sends first, then opens:
  line 427 `await send({"type": "http.response.start", "status": self.status_code, "headers": self.raw_headers})`, line 433
  `async with self._open_file() as file:`. `_handle_single_range` (446, 450) and `_handle_multiple_ranges` (474, 478) have the
  same order. `staticfiles.py:124-125`: `except PermissionError: raise HTTPException(status_code=401)`, around the lookup,
  which only calls `os.stat` (`:176`).
- **Starlette main**, `Kludex/starlette` at `63d868e` (2026-11-22; `encode/starlette` redirects there),
  <https://raw.githubusercontent.com/encode/starlette/main/starlette/responses.py>: the same order, lines 429 and 435.
- **Upstream reports.** Searched issues, pull requests and discussions of `Kludex/starlette` for FileResponse and StaticFiles
  with permission, PermissionError, open and 401. None reports this order. #1220 (merged 2021-10-05) made a PermissionError
  of the lookup a 401. #3594, "fix: Prevent StaticFiles path replacement races", opened static files before building the
  response and would have fixed this order as a side effect; its author closed it unmerged on 2026-10-06. Starlette asks for a
  bug to start as a "Potential Issue" discussion (`docs/contributing.md`: "Contributions should generally start out with a
  discussion. Possible bugs may be raised as a "Potential Issue" discussion"). The report is drafted, not filed:
  `upstream-report-draft.md`.
- **OpenShift, "Support arbitrary user ids"** (openshift-docs `modules/images-create-guide-openshift.adoc` at `6afb7b34d9`,
  2026-10-22, the source of the "Creating images" guidelines; docs.redhat.com answered 403 to a fetch): "By default,
  {product-title} runs containers using an arbitrarily assigned user ID." "For an image to support running as an arbitrary
  user, directories and files that are written to by processes in the image must be owned by the root group and be
  read/writable by that group. Files to be executed must also have group execute permissions." Its example is `RUN chgrp -R 0
  /some/directory && chmod -R g=u /some/directory`, because "the container user is always a member of the root group".
- **GNU coreutils 9.12, "Copying Existing Permissions"**
  (<https://www.gnu.org/software/coreutils/manual/html_node/Copying-Permissions.html>): "instead of using a series of 'r',
  'w', or 'x' letters after the operator, you use the letter 'u', 'g', or 'o'"; its example `o+g` turns 741 into 745. So
  `g=u` gives the group exactly the owner's bits: a file its owner cannot read stays unreadable to group 0, so the line does
  not by itself guarantee what OpenShift needs. **"chmod invocation"**: "chmod ignores symbolic links encountered during
  recursive directory traversals."
- **Dockerfile reference, USER** (<https://docs.docker.com/reference/dockerfile/>): "USER <UID>[:<GID>]"; "The specified
  user is used for RUN instructions"; with no primary group, the root group.
- **Alpine 3.24 busybox** (`aports/main/busybox/busyboxconfig`, 3.24-stable; the portal's base is Alpine 3.24.2):
  `CONFIG_FEATURE_FIND_EXEC_PLUS=y`, `CONFIG_FEATURE_FIND_PERM=y`, `CONFIG_FEATURE_FIND_NOT=y`, `CONFIG_FEATURE_FIND_PAREN=y`;
  busybox's find has no `-readable`, so the check reads each mode with the shell's `test`. The cmapi base has GNU find
  (`usr/bin/find`, a 291,760-byte binary), and both bases have `sh` and `test` (read from their layers with skopeo, by
  digest; nothing was run).

## The choice

The cause is the image's modes, so the fix is in each Containerfile, where the modes are set. Its final stage, after the last
change to its files, now runs as `USER 54321:0`, a UID that owns nothing in group 0, as OpenShift runs it, and fails the
build on a path it cannot read, a directory it cannot search, or a file that its owner may run and it cannot. A link is
followed to its target, which is read, and searched or run, as a file of the checked paths would be; a dangling link or a
cycle passes, as the app cannot open either. Before it reads, the check asserts its own premise: its groups are 0 alone, and
it owns no file under the checked paths. (The UID was `1000690000` until review 1, below; the CI runs under "Proof" used that
one.) A canary of mode 000 first proves that the check sees modes: a user with `CAP_DAC_OVERRIDE` reads it, and the check
would then pass anything.
The image then goes back to its runtime user (1001, 101). It is a `RUN`, so every job that builds the image runs it:
`images` (the published images), `images-pr` and `front-door`.

- **cmapi** checks `/opt/app-root` (the static bundles, the schemas, the Python environment), `/etc/cmapi` (the policies) and
  `/usr/local/bin` (kyverno, kubeconform).
- **The portal** checks `/usr/share/nginx/html`, `/etc/nginx`, `/docker-entrypoint.sh` and `/docker-entrypoint.d`, and also
  that the user can write what the entrypoint writes at start: `/etc/nginx/conf.d` (20-envsubst-on-templates.sh), and
  `/etc/nginx/nginx.conf` and `/etc/nginx`, which 30-tune-worker-processes.sh edits with `sed -i`. That script exits 0 when
  it cannot write, so nginx would start with the stock worker count and no error.

`deploy/tests/ci-guard.py` requires the check in both final stages, the `RUN` whole and nothing else in it, the default
shell (no `SHELL` in the final stage), nothing but metadata after it, the runtime user restored, and every `COPY` of the
final stage, by a literal path, under a path the check reads, so a new `COPY` elsewhere fails CI until the check covers it.

Rejected:

- **A `find -perm -g=r` as root**, as the issue proposed. It models the kernel's rule instead of asking it: a file of group
  1001 with `g+r` passes and is still unreadable to the arbitrary UID, and a directory without `x` is not seen. Running as the
  user asks the kernel.
- **A check of the running image in CI** (`docker run`). It works in the jobs that load the image, but not in `images`, which
  pushes by digest and loads nothing, and it is a second place that has to know the paths. A `RUN` cannot be skipped by any
  job that builds the image.
- **A FileResponse in cmapi that opens before it starts.** A re-implementation of the framework's file sending for a state
  that the image can rule out, and it would still serve a 401 (internal-error) for a file of the image. The order is reported
  upstream instead (draft), for the upgrade to take.

## Proof

- **The guard, before and after** (`outputs/guard-before.txt`, `outputs/guard-after.txt`): the new guard on `main`'s
  Containerfiles fails 4 cases (the check missing and nothing after it, in both images; 6 before review 1, when the guard
  read the paths from the check and so counted the COPYs as outside); on this branch it passes, `ci cases failed: 0`.
- **The guard's mutants** (`outputs/guard-mutants.txt`, `probes/guard-mutants.py`): 14 mutants of the Containerfiles (25
  after review 1, 35 after review 2, below), all killed: the check removed (each image), moved before `COPY policies`, run as root, a path dropped (each image), the canary
  removed, the read test made `true`, a finding that does not fail the build, the search-or-run test removed, a COPY after
  the check, a COPY outside the checked paths, a RUN after the check, and the runtime user not restored.
- **The check's logic on this Mac** (`/bin/sh`, as the owner): a tree with a file of mode 000, a write-only file, a
  directory of mode 0600 and one of mode 000 is refused with each path named; a clean tree with a dangling symlink passes.
  After review 2, `probes/modes-check.py` runs each image's `RUN`, taken from its Containerfile, on 13 trees (14 for the
  portal) under `/bin/sh` and `/bin/dash`: `cases failed: 0` (`outputs/modes-check.txt`).
- **CI, the mutant: before.** Commit `6eca40b` added `RUN chmod 0600 /opt/app-root/static/redoc/redoc.standalone.js` to
  cmapi and `RUN chmod 0600 /usr/share/nginx/html/mockup/portal.html` to the portal, before the check. Run 45549565321: the
  three builds failed at the check, and each named only the mutated file, so nothing in the bases fails it
  (`outputs/ci-mutant-run-45549565321.txt`). From `images-pr (cmapi, ...)`, job 138987216159:

  ```
  #21 0.155 Not usable by an arbitrary UID in group 0 (#650):
  #21 0.155 cannot read /opt/app-root/static/redoc/redoc.standalone.js
  ```

  and `cannot read /usr/share/nginx/html/mockup/portal.html` in `images-pr (cmapi-portal, ...)`, job 138987216121, and in
  `front-door`, job 138987215785. The canary passed in all three, so the build's user had no capability that reads past
  modes. Commit `fd5eeae` reverts the mutant; the tree is then `e528fd3`'s.
- **CI, the fix: after.** Run 45551885303 on `fd5eeae`: every job green (`outputs/ci-fix-run-45551885303.txt`). The line
  that proves it, in `images-pr (cmapi, cmapi/Containerfile, cmapi)`, job 138994721202:

  ```
  #20 0.114 image modes (#650): an arbitrary UID in group 0 reads every file and searches every directory under /opt/app-root /etc/cmapi /usr/local/bin
  ```

  and the portal's line in `images-pr (cmapi-portal, ...)`, job 138994721230, and `front-door`, job 138994721195, with
  `ci-guard.py`'s six new cases ok in `manifests`, job 138994721283. The `images` job (main only) builds from the same
  Containerfiles and runs the same `RUN`; it runs at the merge.

## Not tested

- The images on CRC under `restricted-v2`. The check runs at build, in CI, as UID 54321 in group 0 (1000690000 in the CI
  runs under "Proof"); no image was run on this Mac (the owner's rule: CI builds the images for CRC).
- Supplementary groups: the build's user has group 0 only (Dockerfile reference, USER: "the user will have _only_ the
  specified group membership"). Under `restricted-v2` a pod also gets the namespace's `fsGroup` as a supplementary group
  ("Requires that a pod is run with a preallocated FSGroup"; for `cmapi` on CRC, 1000720000). A group can take access away
  only from a file that it owns and that gives the group less than others; no file of either image has such a GID (the bases'
  files have GIDs 0, 12 and 42), so here it adds nothing and removes nothing.
- The image's own user (1001, 101), as kind and plain Docker run it. The check asks as a UID that owns nothing. The owner is
  refused where the arbitrary UID is not only on a file whose owner bits are less than its group bits, which `chmod -R g=u`
  (cmapi) and the bases' 644, 664, 755 and 775 (the portal) do not leave.
- Files that the cluster mounts at run time (ConfigMaps, Secrets, the portal's `config.json`): their modes come from the
  manifests, not the image.
- The Starlette report is a draft; nothing was filed upstream.

## Review 1 (Fable 5.2), 2026-11-25

Reviewer 1's findings and their fixes, applied to this branch; its report has the sources and the outputs.

- **The guard compared clauses, not the RUN (R1-1, R1-2).** Nine mutants passed the guard at `5769429`: the portal's write
  check removed, `bad="";` before the findings are read, `exit 0;` after `set -eu;`, the check inside `if false`,
  `-maxdepth 0` in `paths`, `/etc/cmapi` narrowed to `/etc/cmapi/policies`, `/docker-entrypoint.sh` dropped, and a `COPY`
  outside the checked paths in the JSON form or through an `ENV`. The guard now compares the whole `RUN` of each image, and a
  `COPY` destination it cannot place counts as outside. `probes/guard-mutants.py` has 25 mutants, all killed
  (`outputs/guard-mutants.txt`).
- **UID 1000690000 is not mapped in a rootless build (R1-3).** Podman's troubleshooting guide, 10, "rootless setup user:
  invalid argument": "A user, either via --user or through the default configured for the image, is not mapped inside the
  namespace." (<https://github.com/containers/podman/blob/main/troubleshooting.md>, read 2026-11-25). Measured on this Mac:
  `podman info` gives the map `[{0 501 1} {1 100000 1000000}]`, so UIDs above 1000000 do not exist in the build, and shadow's
  default is 65536 (`SUB_UID_COUNT`). Not measured by a build (the owner's rule). No `cmapi` namespace on CRC has that UID in
  its range either (measured: `cmapi` 1000720000/10000, `cmapi-system` 1000810000/10000, `cmap-live-g-dev` 1000830000/10000),
  and none needs to: the kernel asks whether the UID owns the file and whether one of its groups is the file's, so any UID that
  owns nothing answers alike. The bases' files belong to UIDs 0 and 1001 (cmapi) and 0 and 101 (the portal), read from their
  layers. The check now runs as `54321:0`, and the guard holds the UID below 65534.
- **Links were skipped (R1-4).** `! -type l` left a link's target unread when it lies outside the checked paths. The check now
  reads each link whose target exists through to it. The bases' links under the checked paths all end at a readable target
  (`/opt/app-root/bin/python3.12` to `/usr/bin/python3.12`, `lib64` to `lib`, `/etc/nginx/modules` to `/usr/lib/nginx/modules`).
- **Not tested after these changes:** no image was built with them. CI on the new head is the proof; the lines to read are
  `image modes (#650)` in `images-pr` (both) and `front-door`. The canary's refusal has never run: it needs a build as a user
  with `CAP_DAC_OVERRIDE`, which the guard forbids.

## Review 2 (Opus 5.5), 2026-11-25

Reviewer 2 checked review 1's findings and its patch, and ruled on each with a test; its report has the sources and outputs.

- **The whole-`RUN` comparison stays (R1-1).** Any edit to the check must change the guard in the same pull request; that is
  the guarantee, as for the pinned `skopeo` calls above it in the guard. A behaviour test in CI would have to rewrite the
  `RUN`'s paths and still pin them; `probes/modes-check.py` keeps the behaviour proof in the record instead.
- **The fixed UID stays, and the check now proves its premise (R1-3).** `USER` cannot take a UID read from the image: the
  Dockerfile reference lists `USER` among the instructions that take `ENV` and `ARG` values, nothing computed from files. So
  the `RUN` asserts what makes 54321 a stand-in for OpenShift's UID: `[ "$(id -G)" = 0 ]` (Docker documents "_only_ the
  specified group membership"; Buildah's `configureUIDGID` adds `user.AdditionalGids`, `run_common.go:289-291`), and no file under
  the checked paths owned by `$(id -u)`. If a base one day gives 54321 a file, the build fails and names it. Measured: no file
  of either pinned base belongs to 54321 (their layers, read by digest), and this Mac's rootless map is
  `[{0 501 1} {1 100000 1000000}]` (`podman info`). `deploy/release-crc.sh:57,63` runs `podman build` with that map; CI's
  BuildKit is rootful.
- **Links are searched and run too (R1-4).** Review 1's clause read a link's target but did not search a linked directory or
  run a linked program. `/opt/app-root/bin/python3.12` links to `/usr/bin/python3.12`, and `/etc/nginx/modules` to
  `/usr/lib/nginx/modules`. The clause now applies the same tests as for a file of the checked paths. `find` does not follow
  links, and `test -e` is false on a cycle, so a cycle neither loops nor fails (a case of `probes/modes-check.py`).
- **Four mutants passed review 1's guard:** `SHELL ["/bin/true"]` or `SHELL ["/bin/sh", "-c", "exit 0"]` before the check (the
  `RUN` becomes an argument and runs nothing), and a `COPY` to a relative path under `WORKDIR $OUT` or `${OUT}`. The guard now
  refuses a `SHELL` in the final stage and counts a relative destination under a `WORKDIR` with a variable as outside. 35
  mutants, all killed (`outputs/guard-mutants.txt`).
- **The success line names the UID** (`an arbitrary UID ($(id -u)) in group 0`), so the build log shows which UID ran; BuildKit
  does not print `USER`.
- **Not tested:** no image was built with these changes. In CI, `image modes (#650): an arbitrary UID (54321) in group 0` in
  `images-pr` (both) and `front-door`, after a step header that holds `[ "$(id -G)" = 0 ]` and `find -H`, proves that the new
  `RUN` ran as 54321, that its premise held (group 0 alone, nothing owned) and that every link with a target passed.

## Coordinator's rulings and the CI gate

- **Rulings (Opus 5.5).** All findings of reviewer 1 (Fable 5.2) and of reviewer 2 (Opus 5.5 high) are accepted. Reviewer 2's patch was applied with `patch -p1 -F0`.
- **CI gate**, run 45583165533 on head `5fbffb8`: every job is green.
  - Each image build printed its success line:
    - `images-pr (cmapi)`: `image modes (#650): an arbitrary UID (54321) in group 0 reads every file and searches every directory under /opt/app-root /etc/cmapi /usr/local/bin`.
    - `images-pr (cmapi-portal)` and `front-door`: the same line, for `/usr/share/nginx/html /etc/nginx /docker-entrypoint.sh` and the rest of the portal's paths.
  - The logs hold no real refusal. Lines that contain "cannot read" are the check's own source, which BuildKit echoes.
  - `manifests` printed:
    - `ok   the modes check's user (54321:0)`;
    - `ok   …: the final stage keeps the default shell`, for both images;
    - `ci cases failed: 0`.
