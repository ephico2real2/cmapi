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
change to its files, now runs as `USER 1000690000:0`, a UID that owns nothing in group 0, as OpenShift runs it, and fails the
build on a path it cannot read, a directory it cannot search, or a file that its owner may run and it cannot. A canary of mode
000 first proves that the check sees modes: a user with `CAP_DAC_OVERRIDE` reads it, and the check would then pass anything.
The image then goes back to its runtime user (1001, 101). It is a `RUN`, so every job that builds the image runs it:
`images` (the published images), `images-pr` and `front-door`.

- **cmapi** checks `/opt/app-root` (the static bundles, the schemas, the Python environment), `/etc/cmapi` (the policies) and
  `/usr/local/bin` (kyverno, kubeconform).
- **The portal** checks `/usr/share/nginx/html`, `/etc/nginx`, `/docker-entrypoint.sh` and `/docker-entrypoint.d`, and also
  that the user can write what the entrypoint writes at start: `/etc/nginx/conf.d` (20-envsubst-on-templates.sh), and
  `/etc/nginx/nginx.conf` and `/etc/nginx`, which 30-tune-worker-processes.sh edits with `sed -i`. That script exits 0 when
  it cannot write, so nginx would start with the stock worker count and no error.

`deploy/tests/ci-guard.py` requires the check in both final stages, each clause whole, nothing but metadata after it, the
runtime user restored, and every `COPY` of the final stage under a path the check reads, so a new `COPY` elsewhere fails CI
until the check covers it.

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
  Containerfiles fails 6 cases (the check missing, nothing after it, and the COPYs outside it, in both images); on this
  branch it passes, `ci cases failed: 0`.
- **The guard's mutants** (`outputs/guard-mutants.txt`, `probes/guard-mutants.py`): 14 mutants of the Containerfiles, all
  killed: the check removed (each image), moved before `COPY policies`, run as root, a path dropped (each image), the canary
  removed, the read test made `true`, a finding that does not fail the build, the search-or-run test removed, a COPY after
  the check, a COPY outside the checked paths, a RUN after the check, and the runtime user not restored.
- **The check's logic on this Mac** (`/bin/sh`, as the owner): a tree with a file of mode 000, a write-only file, a
  directory of mode 0600 and one of mode 000 is refused with each path named; a clean tree with a dangling symlink passes.
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

- The images on CRC under `restricted-v2`. The check runs at build, in CI, as UID 1000690000 in group 0; no image was run on
  this Mac (the owner's rule: CI builds the images for CRC).
- Supplementary groups: the build's user has group 0 only. A pod's `fsGroup` or supplemental groups can only add access.
- Files that the cluster mounts at run time (ConfigMaps, Secrets, the portal's `config.json`): their modes come from the
  manifests, not the image.
- The Starlette report is a draft; nothing was filed upstream.
