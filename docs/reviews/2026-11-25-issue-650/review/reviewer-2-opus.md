# PR #667 (closes #650): reviewer 2 report

Reviewer 2: Opus 5.5 at `high`, 2026-11-25. Head `5769429`, base `160bd83`. I did not write the change or reviewer 1's
review. Everything ran in the export `review-667/`: `r2/` is `head/` plus reviewer 1's patch plus mine. No image was built or
run. No git repository, no GitHub, no cluster was touched. The one host command outside the export was `podman info`.

## Result

Reviewer 1's (Fable 5.2) four findings hold, and its patch applies and passes. I keep all of it and extend it in four places.
Each ruling below is decided by a test.

| # | Finding | Ruling | Test before | After |
|---|---|---|---|---|
| R1-1 | The guard compares clauses, not the RUN | **Accepted**, whole-RUN comparison kept | 9 survivors at the head (reviewer 1's run, reproduced) | 0 of 35 |
| R1-2 | A COPY destination given through a variable or in JSON form counts as checked | **Accepted**, and **extended** (R2-2) | 2 survivors at the head | 0 |
| R1-3 | UID 1000690000 is not mapped in a rootless build | **Accepted**: `54321:0`. **Extended** (R2-4): the RUN now asserts the stand-in's premise | 4 behaviour cases fail on reviewer 1's fix | 54 of 54 pass |
| R1-4 | Links are skipped | **Accepted**: no loop, and a dangling link is allowed. **Extended** (R2-3): a link's target is also searched or run | 8 behaviour cases fail on reviewer 1's fix | pass |
| R1-5 | Corrections to the record | **Accepted**, plus one stale line it missed (R2-6) | n/a | corrected |
| R2-1 | `SHELL` before the check turns it into a no-op | **New**, Medium | 2 survivors on reviewer 1's fix | killed |
| R2-2 | A relative COPY under `WORKDIR $VAR` counts as inside | **New**, Low | 2 survivors on reviewer 1's fix | killed |
| R2-3 | A linked directory is not searched, and a linked program is not run | **New**, Low | 8 behaviour cases fail (2 cases x 2 shells x 2 images) | pass |
| R2-4 | Nothing checks that the fixed UID owns nothing and is in group 0 alone | **New**, Medium | 8 behaviour cases fail | pass |
| R2-5 | No CI log line shows which UID ran the check (BuildKit does not print `USER`) | **New**, Low | n/a | the success line prints `$(id -u)` |
| R2-6 | The record's "Not tested" still says the check runs "as UID 1000690000" | **New**, Low | n/a | corrected |

The patch is `r2-outputs/fix.diff`: 604 lines, 10 files, against `head/`. It covers only `cmapi/Containerfile`,
`cmapi-portal-ui/Containerfile`, `deploy/tests/ci-guard.py` and `docs/reviews/2026-11-25-issue-650/`, and is
reviewer 1's patch with mine on top. I applied it to a fresh copy of `head/` with `patch -p1 -F0` (all hunks applied), and
`diff -r` of that copy against `r2/` is empty.

## Sources, each fetched 2026-11-25 (saved in `r2-outputs/sources/`)

- **Podman troubleshooting, 10**, <https://raw.githubusercontent.com/containers/podman/main/troubleshooting.md>, lines 252-262:
  "### 10) rootless setup user: invalid argument. Rootless Podman requires the user running it to have a range of UIDs listed
  in /etc/subuid and /etc/subgid." "A user, either via --user or through the default configured for the image, is not
  mapped inside the namespace." Example: `podman run --rm -ti --user 1000000 alpine echo hi` gives `"setup user: invalid
  argument"`. Reviewer 1's quote is confirmed word for word.
- **Podman rootless tutorial**, <https://raw.githubusercontent.com/containers/podman/main/docs/tutorials/rootless_tutorial.md>:
  "`johndoe:100000:65536`"; "This means the user `johndoe` is allocated UIDs 100000-165535 as well as their standard UID".
  So a default rootless namespace holds container UIDs 0 (the user) and 1 to 65536.
- **shadow**: `man/login.defs.d/SUB_UID_COUNT.xml` says "The default values for SUB_UID_MIN, SUB_UID_MAX, SUB_UID_COUNT are
  respectively 100000, 600100000 and 65536." `etc/login.defs:228` reads `SUB_UID_COUNT 65536`
  (<https://github.com/shadow-maint/shadow>, master).
- **Measured on this Mac**: `podman info --format '{{.Host.Security.Rootless}} uid={{.Host.IDMappings.UIDMap}}'` gives
  `true uid=[{0 501 1} {1 100000 1000000}] gid=[{0 1000 1} {1 100000 1000000}]`, Podman 5.5.2. The default connection is
  `podman-machine-default` (`core@`, rootless), so this build maps container UIDs 0 to 1000000. 54321 is mapped and
  1000690000 is not. `deploy/release-crc.sh:57` and `:63` run `podman build` on both Containerfiles. CI builds with
  `docker/setup-buildx-action` and `docker/build-push-action` (`ci.yml:179,189,246,266,329`), whose BuildKit is rootful; head
  run 45554471919 passed with 1000690000. The R1-3 failure is inferred from the source and the map. It was not built (the
  owner's rule).
- **OpenShift SCCs**, openshift-docs `modules/security-context-constraints-about.adoc` and
  `...-pre-allocated-values.adoc` (main): `restricted` "Requires that a pod is run as a user in a pre-allocated range of UIDs",
  "Requires that a pod is run with a preallocated FSGroup", "Allows pods to use any supplemental group"; `restricted-v2` is
  "Like the `restricted` SCC" with "`ALL` capabilities are dropped". "A `RunAsUser` strategy of `MustRunAsRange` with no
  minimum or maximum set. Admission looks for the `openshift.io/sa.scc.uid-range` annotation"; "`MustRunAsRange` and
  `MustRunAs` (range-based) strategies provide the minimum value of the range." So the arbitrary UID is the namespace range's
  minimum (1000720000 for `cmapi`, reviewer 1's measurement), and an `fsGroup` is added. The same page now also lists
  `restricted-v3` (pods in a user namespace, `hostUsers: false`), "used by default for authenticated users" on new installs. I
  did not check how that changes the UID inside the pod, and it does not change the rule the check models. Recorded here, not
  in the record.
- **OpenShift image guidelines**, `modules/images-create-guide-openshift.adoc` (main): "By default, {product-title} runs
  containers using an arbitrarily assigned user ID." "Files to be executed must also have group execute permissions."
  "Because the container user is always a member of the root group". Confirmed.
- **Dockerfile reference** (moby/buildkit `frontend/dockerfile/docs/reference.md`): USER "when specifying a group for the user,
  the user will have _only_ the specified group membership". Environment replacement: "Environment variables are supported
  by the following list of instructions ... `USER`". USER takes only `ENV` and `ARG` values; nothing computed from the image's
  files can set it. SHELL: "allows the default shell used for the shell form of commands to be overridden".
- **Buildah** `run_common.go:286-291` (main), `configureUIDGID`: `g.SetProcessGID(user.GID); g.AddProcessAdditionalGid(user.GID);
  for _, gid := range user.AdditionalGids { g.AddProcessAdditionalGid(gid) }`. Buildah does add supplementary groups, and
  Docker's sentence does not govern it. I could not locate `userForRun`, where `AdditionalGids` is filled, so I do not claim
  which groups it adds. For that reason the check now measures its groups instead of trusting either builder (R2-4).
- **busybox 1.37.0** (Alpine 3.24's; `aports` 3.24-stable `busyboxconfig`: `# Busybox version: 1.37.0`, `CONFIG_ID=y`,
  `CONFIG_FEATURE_FIND_USER=y`, `CONFIG_FEATURE_FIND_MAXDEPTH=y`): `findutils/find.c` from the release tarball
  (busybox.net/downloads/busybox-1.37.0.tar.bz2): usage `"[-HL] [PATH]..."`, `-H ...on command line only`, and `-user` parses
  a number first (`ap->uid = bb_strtou(arg1, NULL, 10); if (errno) ap->uid = xuname2uid(arg1);`).
- **POSIX `find`** (<https://pubs.opengroup.org/onlinepubs/9799919799/utilities/find.html>): `-H` "Cause the file information
  and file type evaluated for each symbolic link encountered as a path operand on the command line to be those of the file
  referenced by the link"; `-user`: "If uname is a decimal integer and the getpwnam() ... does not return a valid user name,
  uname shall be interpreted as a user ID."
- **`id -G`**, coreutils `src/group-list.c` and busybox `coreutils/id.c`: both print the real GID, then the effective one if
  different, then each supplementary group that is neither. So for a process in group 0 alone, `id -G` prints `0`.
- **The pinned bases, read by digest** (`r2-outputs/probes/base-tools.py` on the OCI layouts in `wt-663-outputs/`, digests
  `b99faaadaf10` and `f5116ed4606f`, tar headers only): cmapi has `/usr/bin/id` (coreutils, 0555), `/usr/bin/find`,
  `/usr/bin/mktemp`, and `sh` is bash. The portal has `id`, `find`, `mktemp` and `sh` as busybox links. **No file of either base
  is owned by 54321.** File owners: UIDs 0 and 1001 (cmapi), 0 and 101 (portal).

## Rulings

### R1-1: is comparing the whole RUN brittle? Kept.

What it costs: any edit to the check must change `modes_run` in the guard, in the same pull request. That is the guarantee
the guard exists for: the check cannot change, or be weakened, without a reviewer seeing a guard diff. It is also the
guard's existing style. The lines above it pin `skopeo_calls` by exact equality (`ci-guard.py:156-158`).

A behaviour test in CI would have to extract the RUN, rewrite its absolute paths under a temporary root (a regex over the
RUN, which is fragile too), and still pin `paths`, the UID and the position, because a behaviour test cannot see
`-maxdepth 0` added to `paths` or `/etc/cmapi` narrowed. It would add a second mechanism without removing the first. That is
over-building, and the owner's rule allows it only when nothing simpler works. Here the whole-RUN comparison kills all 35
mutants. The behaviour proof belongs in the record, and it is there: `probes/modes-check.py` (reviewer 1's test, extended),
54 cases.

### R1-3: is `54321:0` a sound stand-in? Yes, once the RUN asserts the premise (R2-4).

- The kernel's DAC rule depends on two things only: whether the UID owns the file, and whether one of its groups is the
  file's group. So any UID that is in group 0 alone and owns nothing answers exactly as OpenShift's 1000720000 does.
- **Can the UID be read from the build instead?** Not by `USER`, which takes only `ENV` and `ARG` values (Dockerfile
  reference, above). Dropping privileges inside a RUN (`setpriv`, `su-exec`) would need the tool in both bases, and to run as
  root first. That is over-building, and it would not remove the premise.
- **"A fixed UID could one day own a file":** today it owns none (measured above), but a base update or a `chown` could
  change that, and nothing would notice. Reviewer 1's guard bounds only the number. So the RUN now asserts both halves of the
  premise before it reads anything:

  ```sh
  bad=$( { [ "$(id -G)" = 0 ] || echo "the check runs in groups $(id -G), not in group 0 alone"; \
           find $paths -user "$(id -u)" -exec echo "owned by the check UID, so the kernel read its owner bits:" {} +; \
  ```

  If a base ever gives 54321 a file under the checked paths, the build fails and names the file. If a builder adds a
  supplementary group (Buildah adds `AdditionalGids`), the build fails and names the groups. The kernel answers both
  questions, which is the PR's own design principle.
- The bound `0 < uid < 65534` (reviewer 1) matches the sources: default maps hold container UIDs up to 65536, and 65534 is
  the overflow UID.

### R1-4: does the link clause follow links safely? Yes. Does it refuse a dangling link the app never opens? No, rightly.

- `find $paths -type l` does not follow links (`-P` is find's default). For each link, `test -e` follows the chain and is false
  on a cycle (ELOOP) or a missing target, so the clause moves on. Tested: the case "r2 a link cycle (no loop, no finding)"
  exits 0 under `/bin/sh` and `/bin/dash`, within the probe's 60 s timeout.
- A dangling link passes. The app gets ENOENT from it, which is not a modes failure, and refusing it would fail builds on
  harmless links. Kept.
- **Gap (R2-3):** reviewer 1's clause only reads the target. It does not search a linked directory or run a linked program,
  but the clause for plain paths does both. The bases have exactly these links: `/opt/app-root/bin/python3.12` to
  `/usr/bin/python3.12` (the interpreter) and `/etc/nginx/modules` to `/usr/lib/nginx/modules`. Now:

  ```sh
  find $paths -type l -exec sh -c 'for p; do [ -e "$p" ] || continue; [ -r "$p" ] || echo "cannot read $p (a link: its target)"; if [ -d "$p" ] || [ -n "$(find -H "$p" -maxdepth 0 -type f -perm -100)" ]; then [ -x "$p" ] || echo "cannot search or run $p (a link: its target)"; fi; done' sh {} +; \
  ```

  `find -H` takes the target's type and mode (POSIX, busybox 1.37.0 and GNU all support it). Directories are tested with
  `test -d` rather than `find`. My first version used find, and BSD find printed "Permission denied" for an unsearchable
  linked directory instead of the clause's message. I saw that in a run of the modes probe; its output was overwritten by the rerun and is not kept. The fix is in this patch.
- Not caught, as reviewer 1 said: a target behind an ancestor directory that cannot be searched looks dangling.

### R2-1 (Medium): `SHELL` turns the check into a no-op

`SHELL ["/bin/true"]` (or `["/bin/sh", "-c", "exit 0"]`) before `USER 54321:0` makes the RUN an argument of a command that
exits 0, so nothing is read. Reviewer 1's guard passes both (`r2-outputs/guard-mutants-before.txt`: `SURVIVED`). Fix: the
guard refuses a `SHELL` in the final stage. Neither Containerfile uses one.

### R2-2 (Low): a COPY under a WORKDIR with a variable

`ENV OUT=/srv`, `WORKDIR $OUT`, `COPY policies policies`: the guard joins to `/opt/app-root/src/$OUT/policies` and counts it
as inside. The same happens with `WORKDIR ${OUT}/x`. Both survive reviewer 1's fix. Fix: a relative destination under a
`WORKDIR` that holds `$` counts as outside.

### R2-5 (Low): the CI log cannot show the UID

BuildKit prints the RUN's text but not `USER`. So no line in run 45554471919 shows 1000690000, and none would show 54321. The
success line is now `image modes (#650): an arbitrary UID ($(id -u)) in group 0 reads ...`, and the guard pins it.

### R2-6 (Low): the record

`README.md`, "Not tested": "The check runs at build, in CI, as UID 1000690000 in group 0". Reviewer 1 changed the UID but not
this line. It now names 54321, and notes that 1000690000 ran in the CI runs under "Proof". The README also gains a "Review 2"
section, the `SHELL` rule, the premise, the links and the modes probe.

## Tests (all with `/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python`)

| Test | On reviewer 1's fix | On the final fix (`r2/`) |
|---|---|---|
| `deploy/tests/ci-guard.py .github/workflows/ci.yml` | `ci cases failed: 0` | `ci cases failed: 0` (`r2-outputs/guard-after.txt`) |
| The same guard on `main`'s Containerfiles | 4 fail (reviewer 1) | 4 fail: the check missing, nothing after it, both images (`r2-outputs/guard-before-main.txt`) |
| `r2-outputs/probes/guard-mutants-r2.py r2 <py>`: 14 implementer + 11 reviewer 1 + 10 reviewer 2 mutants | `survivors: 4` (the two SHELLs, the two WORKDIRs; my 5 premise/link mutants n/a) (`guard-mutants-before.txt`) | `survivors: 0`, 35 killed (`guard-mutants-after.txt`) |
| `r1-outputs/modes-check-test.py r2` (reviewer 1's own) | `cases failed: 0` | superseded by the next row, which runs its 8 cases too |
| `r2-outputs/probes/modes-check-r2.py r2`: 13 cases (14 portal) x `/bin/sh`, `/bin/dash` x 2 images | `cases failed: 16` (`modes-check-before.txt`) | `cases failed: 0`, 54 ok (`modes-check-after.txt`) |
| `r2-outputs/probes/behaviour-mutants-r2.py r2 <py>`: 7 mutants of the new clauses x 2 images, each run through the modes cases | n/a | `survivors: 0`, 14 killed, each by the case that names it (`behaviour-mutants-after.txt`) |
| The record's own `probes/guard-mutants.py` (35 mutants), run as `r2-outputs/probes/guard-mutants-record-nogit.py`, a copy that uses `copytree` for `git ls-files` (the export has no git) | n/a | `survivors: 0` (`docs/.../outputs/guard-mutants.txt`) |
| `patch -p1 -F0 < r2-outputs/fix.diff` on a fresh `head/`, then `diff -r` against `r2/` | n/a | applies; no difference |

The behaviour mutants are: the group premise removed; the owner premise removed; the owner premise asking UID 0; links not
searched or run; linked directories not searched; `find -H` without `-H`; and the `test -e` guard removed, which the dangling
and cycle cases kill.

How the modes probe models identity: it runs as this Mac's user, who owns the trees and is in many groups, so the premise is
false by construction. In every case but two, it puts `"54321"` for `"$(id -u)"` and `0` for `$(id -G)`. The two premise cases
keep the real calls and must fail. The case for a linked program needs a file of another owner with mode `rwxr--r--`; the
probe finds one on the machine (here `/Library/Application Support/Apple/Spotlight/MailUsesCoreSpotlight`, root, 0744) and
reports `n/a` if there is none.

## The CI lines that will prove it

The UID, the premise and the link clause can be proven only by a CI build of the patched head. Read these lines in the
`images-pr (cmapi, cmapi/Containerfile, cmapi)` job, the `images-pr (cmapi-portal, cmapi-portal-ui/Containerfile, .)` job
and the `front-door` job:

1. The step header `#NN [stage-1 k/n] RUN set -eu; canary=$(mktemp); ...` holds `[ "$(id -G)" = 0 ]`, `find $paths -user "$(id -u)"`
   and `find -H "$p" -maxdepth 0 -type f -perm -100`. This proves the new RUN ran.
2. Then, in cmapi:
   `#NN 0.xxx image modes (#650): an arbitrary UID (54321) in group 0 reads every file and searches every directory under /opt/app-root /etc/cmapi /usr/local/bin`
   In the portal (both jobs):
   `#NN 0.xxx image modes (#650): an arbitrary UID (54321) in group 0 reads every file and searches every directory under /usr/share/nginx/html /etc/nginx /docker-entrypoint.sh /docker-entrypoint.d, and writes the entrypoint's files`
   The `(54321)` proves the UID. The line prints only when `bad` is empty, so it also proves that the groups were 0 alone,
   that 54321 owned nothing under the paths, and that every link with a target was read, and searched or run as needed.
3. In `manifests`, `ci-guard.py` prints `ok   the modes check's user (54321:0) is in group 0, ...`, `ok   <path>: as USER
   54321:0, the build runs the modes check and nothing else, ...`, `ok   <path>: the final stage keeps the default shell, ...`,
   and ends `ci cases failed: 0`.

The `images` job, which runs on main only, runs the same RUN at the merge.

**If CI fails on the first run**, the message names the cause, and either one is a real finding, not noise. "the check runs
in groups ..., not in group 0 alone" means the builder adds groups. "cannot ... (a link: its target)" means a link that the
pip layer or the base adds points at a file the arbitrary UID cannot use. Either is filed and fixed under the owner's
same-session rule.

## Not tested

- No image was built, rootless or in CI, with either patch. The rootless failure of 1000690000 is inferred from Podman's
  documentation and the measured map. CI decides the rest.
- The canary's refusal still has never run. It needs `CAP_DAC_OVERRIDE`, which the guard forbids.
- The `id -G` and `-user` clauses were run under macOS `/bin/sh` (bash 3.2) and `/bin/dash`, with BSD find, not under
  busybox ash or GNU find. Their busybox and GNU support is read from source, not run.
- A pod's groups on CRC, and `restricted-v3`'s effect on the pod's UID.
- Links that the build's own layers add (pip, the portal's `dist`). Only the bases' links were read.

## Who wrote what

- Reviewer 1 (Fable 5.2): `USER 54321:0`, `modes_run` and the whole-RUN comparison, the UID bound, the JSON and `$`
  destination rule, the read-only link clause, and its README corrections. All of it is kept in `fix.diff`.
- Reviewer 2 (Opus 5.5 high, me): the premise clauses, the link search-or-run test, the `SHELL` rule, the `WORKDIR` rule,
  the UID in the success line, the Containerfile comments, the README "Review 2" section and the stale line, 10 mutants in
  `probes/guard-mutants.py`, `probes/modes-check.py` (reviewer 1's test, extended with 6 cases), and the regenerated
  `outputs/guard-{before,after,mutants}.txt` and `outputs/modes-check.txt`.

## Files

- `review-667/r2-outputs/fix.diff`: the patch against `head/`
- `review-667/r2/`: `head/` with the patch applied
- `review-667/r2-outputs/probes/`: `guard-mutants-r2.py`, `modes-check-r2.py`, `behaviour-mutants-r2.py`, `base-tools.py`,
  `guard-mutants-record-nogit.py`
- `review-667/r2-outputs/`: `guard-after.txt`, `guard-before-main.txt`, `guard-mutants-before.txt`, `guard-mutants-after.txt`,
  `modes-check-before.txt`, `modes-check-after.txt`, `behaviour-mutants-after.txt`
- `review-667/r2-outputs/sources/`: the fetched sources quoted above
