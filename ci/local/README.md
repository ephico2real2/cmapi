# Local CI

The owner, 2026-11-13: "use local ci for all work and forget the githiub". The jobs of `.github/workflows/ci.yml` run on
this Mac with act and Podman, and a local run is the merge gate. `act-ci.sh` and `Dockerfile.runner` are copies from
`diagram-kit/skill/setup-local-ci`. That skill (`/setup-local-ci`, alias `/local-ci`) is the one source of the steps and
the gotchas. `/local-ci-web` shows the runs in a browser at `http://127.0.0.1:2026/`.

## Requirements

| Tool | Version | What it does here | Install |
|---|---|---|---|
| Podman | 5.5 or later, machine running | Runs the job containers | `brew install podman` |
| act | 0.2.89 or later | Runs the jobs of `ci.yml` on this Mac | `brew install act` |
| yq | current | Reads the jobs from `ci.yml` for `act-ci.sh` | `brew install yq` |
| gh | current | Gives act a GitHub token, and downloads release files | `brew install gh` |
| shellcheck | current | Lints the shell scripts | `brew install shellcheck` |
| oasdiff | 1.37.0, the same as CI | Finds breaking changes in the API contract, and writes its changelog | From its release, below |

Use oasdiff 1.37.0 only: another version can word a breaking change differently, and then `accepted-breaking.txt` no
longer matches CI.

Install oasdiff from its release, not from Homebrew (Homebrew has 1.35.0). The archive is checked against the
release's `checksums.txt` before it is installed:

```sh
d=$(mktemp -d) && cd "$d" \
  && gh release download v1.37.0 -R oasdiff/oasdiff -p 'oasdiff_1.37.0_darwin_all.tar.gz' -p checksums.txt \
  && grep ' oasdiff_1.37.0_darwin_all.tar.gz$' checksums.txt | shasum -a 256 -c - \
  && tar xzf oasdiff_1.37.0_darwin_all.tar.gz oasdiff && mv oasdiff /usr/local/bin/oasdiff \
  && oasdiff --version
```

When CI changes its oasdiff pin, change the version here in the same pull request.

## Run

This Mac is Intel, so the runner image is amd64. Build it once, in this folder:

```sh
podman build --platform linux/amd64 -t act-runner:ubuntu-24.04 -f Dockerfile.runner .
```

Run the jobs in a clone of the branch with no remote, in a folder named `cmapi` (gotcha G12):

```sh
git clone -q --no-hardlinks -b <branch> <path of this repository> <folder>/cmapi
git -C <folder>/cmapi remote remove origin
ci/local/act-ci.sh -r <folder>/cmapi -b <base commit of the pull request> -o <folder>/act-<run name>
```

The jobs are `reference-code`, `service`, `portal-mockup`, `portal-ui`, `api-contract` and `manifests`. Give `-j <job>`
to run one. Never run `act` with no arguments.

## Ports

A port that a service job publishes is a placeholder in `ci.yml`: `"${{ vars.CMAPI_CI_PG_PORT || '55432' }}:5432"` (#170).
GitHub has no such variable, so it uses 55432. Locally, `act-ci.sh` finds each `vars.<NAME>_PORT` in the workflow and gives
it a port that is free on this Mac and in the Podman machine, from 12026 upward (`ACT_CI_PORT_BASE` changes the start). It
writes the ports to `<log folder>/ports.txt`. So a local run does not clash with `cmapi-test-pg` on 55432, and nothing has
to be stopped. A new service port in `ci.yml` follows the same form, with a name that ends in `_PORT`.

## The merge gate

A pull request merges when every job exits 0 on its exact head commit. Its body says that the gate was local CI, and
gives the commit, each job's result, and the differences from a GitHub run (section 6 of the skill).

## Rules

- A local run never starts a kind cluster and never touches CRC.
- Do not remove the `act-*` containers of a run that you did not start (G13).
- A failure caused by act or Podman is a defect: match it to the skill's gotcha table, then file it.
- After a change to `act-ci.sh`, run `shellcheck -S style act-ci.sh` and keep it the same as the kit, or change the kit.
