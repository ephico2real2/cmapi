# Local CI

The owner, 2026-11-13: "use local ci for all work and forget the githiub". The jobs of `.github/workflows/ci.yml` run on
this Mac with act and Podman, and a local run is the merge gate. `act-ci.sh` and `Dockerfile.runner` are copies from
`diagram-kit/skill/setup-local-ci`. That skill (`/setup-local-ci`, alias `/local-ci`) is the one source of the steps and
the gotchas. `/local-ci-web` shows the runs in a browser at `http://127.0.0.1:2026/`.

## Requirements

| Tool | Version | Why | Install |
|---|---|---|---|
| Podman | 5.5 or later, with a running machine | The container engine that act uses | `brew install podman` |
| act | 0.2.89 or later (the skill measured 0.2.97) | Runs the jobs of `ci.yml` | `brew install act` |
| yq, gh, shellcheck | current | `act-ci.sh` reads the workflow with yq and gets the token with gh | `brew install yq gh shellcheck` |
| oasdiff | 1.37.0, the version that CI pins | `cmapi/contract/gate.sh` and `changelog.py` call it. Another version can print a breaking change in other words, and then `accepted-breaking.txt` does not match CI | See below |

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

## The merge gate

A pull request merges when every job exits 0 on its exact head commit. Its body says that the gate was local CI, and
gives the commit, each job's result, and the differences from a GitHub run (section 6 of the skill).

## Rules

- A local run never starts a kind cluster and never touches CRC.
- Do not remove the `act-*` containers of a run that you did not start (G13).
- A failure caused by act or Podman is a defect: match it to the skill's gotcha table, then file it.
- After a change to `act-ci.sh`, run `shellcheck -S style act-ci.sh` and keep it the same as the kit, or change the kit.
