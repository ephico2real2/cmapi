# #671: every environment-not-served carries instanceUrl

PR #674.
- **Implementer:** Opus 5.5 high.
- **Review:** one reviewer, under the owner's rule of 2026-11-25 for a small fix that touches no security code. Reviewer 1 is Opus 5.5 high, standing in for Codex (`review/reviewer-1-opus.md`).

## The change

`environment_not_served(cfg, env)` in `core/config.py` builds the problem from `instance.directory`. All four refusals use it:
- `Pipeline.check_env_served`;
- the capacity route;
- the tiers route;
- `Pipeline._decide`.

GET /tiers now refuses before it reads the catalog, and answers `environment-not-served` where it answered `policy-violation`. docs/02:161 says it must. A URL that the directory does not give is left out, not sent as `null` (RFC 9457 §3.1).

## Review

- **Five claims confirmed.** Every mutant is killed. oasdiff reports no breaking change. No client reads `null`. `_decide` blocks nothing new.
- **R1-1, Medium, introduced by this PR:** an `instance.directory` with a bad shape turned these 422 answers into 500. Fixed: `load_instance` now checks the shape (`_directory_problems`). Its test fails 7 times on the PR head and passes on the fix.
- **R1-2, Low, in the changed lines:** the RFC 9457 citation is §3.1. Fixed.
- **R1-3, Low:** no shipped entry has a `portalUrl`. Filed as #675, Backlog.
- **R1-4, Low:** the mockup's body has more members than the API sends. Filed as #676, Backlog.

## The coordinator's run

The coordinator applied reviewer 1's patch with `patch -p1 -F0`, relocated 8 docs/14 citations, and read each one.

The full service suite ran in database `cmapi_coord_674`, in the venv built from main's lock, from 2026-11-25T11:06:00Z to 11:48:06Z: **2937 passed in 2507.79 s**, with no failure.

**Not proven yet:** on CRC, `GET /api/v1/capacity?env=prod` as `cmapi.viewer` must carry `instanceUrl`. That call closes #13's criterion 3, after the next deploy.
