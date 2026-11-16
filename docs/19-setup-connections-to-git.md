# Set up cmapi's connection to Git

This guide connects a cmapi instance to the Git repository that holds its cluster configuration. It covers the bot account, its API token, its SSH key, the pinned host keys, the switch from HTTPS to SSH, rotation and troubleshooting.

The design is in [`docs/reviews/2026-11-15-issue-286/`](reviews/2026-11-15-issue-286/README.md). The configuration keys are in [`docs/18`](18-configuration.md), under `instance.git`. The CRC deployment ([`docs/13`](13-crc-deployment.md), owner's step 3) points here.

## What cmapi needs

cmapi uses two credentials of one machine user account, `cmapi-git-bot`:

| Credential | Does | Object in namespace `cmapi` | Mounted in |
|---|---|---|---|
| An SSH key | The Git transport: `git fetch` and `git push` of the request branch `cmapi/<cluster>/<requestId>`. Never a push to `main` | Secret `cmapi-git-bot-ssh`, type `kubernetes.io/ssh-auth`, key `ssh-privatekey` (optional `ssh-publickey`) | worker |
| An API token | The pull request: open it, read it, merge it, comment, close it. Also the API pod's plan-time reads | Secret `cmapi-git-bot`, Opaque, key `token` | api, worker |
| The host's keys | Pin the Git host. An unknown host key is refused, and nothing is ever added | ConfigMap `cmapi-git-bot-known-hosts`, key `known_hosts` | worker |

An SSH key cannot call a host's REST API, so the token is always needed. Before the SSH key exists, Git can use the token over HTTPS. CRC does this now.

Each object is mounted as a folder, so an update reaches the pod with no restart. Two exceptions need a restart: the API client reads the token at start, and the SSH key's checks run at start.

## 1. The bot account (GitHub)

1. Create the GitHub account `cmapi-git-bot`. GitHub allows one machine user for automation ([Managing deploy keys](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys), "Machine users").
2. In the configuration repository (for CRC, `ephico2real2/cmapi-cluster-configs`), go to **Settings → Collaborators** and invite `cmapi-git-bot` with **Write** access.
3. Signed in as `cmapi-git-bot`, accept the invitation.
4. Set `instance.git.commitEmail` to the account's no-reply address. GitHub shows it under **Settings → Emails**, in the form `<id>+cmapi-git-bot@users.noreply.github.com`.

## 2. The API token

Signed in as `cmapi-git-bot`:

1. Open <https://github.com/settings/personal-access-tokens/new>.
2. **Token name:** `cmapi-<instance>`. **Resource owner:** the repository's owner. **Expiration:** set one, and rotate before it ends (section 6).
3. **Repository access:** **Only select repositories**, and select the configuration repository.
4. **Repository permissions:**

   | Permission | Access | For |
   |---|---|---|
   | Contents | Read and write | Git over HTTPS (before SSH), and the API pod's reads of a folder |
   | Pull requests | Read and write | Open, read, merge and close the PR, and its comments |
   | Metadata | Read-only | Every call (GitHub sets it) |

   Do not add Checks. A fine-grained token cannot call GitHub's Checks API, and cmapi does not use it (BUG-69, #279). Add Commit statuses only when `instance.git.hostChecks` or `instance.git.postStatus` is `true`. Both are `false` by default.
5. Click **Generate token**, and copy it. GitHub shows it only once.

Load it from the clipboard on stdin, so it is on no command line, in no shell history and on no screen:

```bash
pbpaste | tr -d '\r\n' | oc create secret generic cmapi-git-bot -n cmapi --from-file=token=/dev/stdin
pbcopy </dev/null
```

To replace an existing token, use `oc apply`:

```bash
pbpaste | tr -d '\r\n' | oc create secret generic cmapi-git-bot -n cmapi --from-file=token=/dev/stdin --dry-run=client -o yaml | oc apply -f -
pbcopy </dev/null
oc rollout restart deploy/cmapi-api deploy/cmapi-worker -n cmapi
```

## 3. The SSH key

cmapi runs `ssh` in batch mode, so the key must have **no passphrase**. At start cmapi refuses an encrypted key, a key that does not parse, a key that is not ed25519, and an `ssh-publickey` that is not the key's own. It logs the key's SHA256 fingerprint (`core/git/transport.py`).

```bash
# The key
mkdir -m 700 ~/cmapi-git-bot-key
ssh-keygen -t ed25519 -N '' -C 'cmapi-git-bot' -f ~/cmapi-git-bot-key/id_ed25519
ssh-keygen -lf ~/cmapi-git-bot-key/id_ed25519.pub    # the fingerprint cmapi logs at start

# The public key, for the bot account
pbcopy < ~/cmapi-git-bot-key/id_ed25519.pub
```

Signed in as `cmapi-git-bot`, go to **Settings → SSH and GPG keys → New SSH key**. Set **Key type** to **Authentication Key**, paste the key, and save.

Load the private key into the cluster:

```bash
oc create secret generic cmapi-git-bot-ssh -n cmapi \
  --type=kubernetes.io/ssh-auth \
  --from-file=ssh-privatekey=$HOME/cmapi-git-bot-key/id_ed25519 \
  --from-file=ssh-publickey=$HOME/cmapi-git-bot-key/id_ed25519.pub
```

## 4. The host keys

Take the host's keys over TLS from the host's own API, then compare their fingerprints with the ones the host publishes. Do not trust the first answer of a plain `ssh-keyscan` alone.

```bash
curl -s https://api.github.com/meta | jq -r '.ssh_keys[] | "github.com " + .' > ~/cmapi-git-bot-key/known_hosts
ssh-keygen -lf ~/cmapi-git-bot-key/known_hosts
```

Compare each line with [GitHub's SSH key fingerprints](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints). Keep every key type the host publishes. Then:

```bash
oc create configmap cmapi-git-bot-known-hosts -n cmapi --from-file=known_hosts=$HOME/cmapi-git-bot-key/known_hosts
```

Test the key from your workstation, with the same options cmapi uses:

```bash
ssh -i ~/cmapi-git-bot-key/id_ed25519 -o IdentitiesOnly=yes \
  -o UserKnownHostsFile=$HOME/cmapi-git-bot-key/known_hosts -o StrictHostKeyChecking=yes -T git@github.com
# Expected: "Hi cmapi-git-bot! You've successfully authenticated, but GitHub does not provide shell access."
```

Then remove the local copy, so that the cluster holds the only one:

```bash
rm -rf ~/cmapi-git-bot-key
```

## 5. Switch Git from HTTPS to SSH

`instance.git.url` chooses the transport. cmapi accepts `https://host/path`, `ssh://git@host[:port]/path` and `git@host:path`. It refuses `http://`, `git://`, and a user or a token in an `https` URL ([`docs/18`](18-configuration.md), `instance.git.url`).

1. In the instance's configuration (for CRC, `deploy/manifests/environments/crc/20-config.yaml`), set:

   ```yaml
   url: "git@github.com:ephico2real2/cmapi-cluster-configs.git"
   ```

   This is a change to the repository, so it goes through a pull request.
2. Apply the configuration, and restart the worker:

   ```bash
   oc rollout restart deploy/cmapi-worker -n cmapi
   oc logs deploy/cmapi-worker -n cmapi | grep -i fingerprint   # the fingerprint of section 3
   ```

3. Prove it: submit one request, for a `cmapi-` test namespace on CRC. It must reach `synced`, with its PR merged. Its timeline and the worker's `git_op` events show each step.

With SSH, Git no longer reads the API token. The token stays for the PR.

## 6. Rotation

| What | How | Restart |
|---|---|---|
| The API token | A new token (section 2), then the `oc apply` lines of section 2. Revoke the old one on the host | api and worker: the API client reads it at start |
| The SSH key | A new key (section 3), its public key added to the account, the Secret replaced with `oc apply`, then the old public key removed from the account | worker: the key's checks run at start |
| A host key | Add the new key to `known_hosts` and apply the ConfigMap. When the host has stopped using the old key, remove it | none: the folder mount updates in the pod |

## 7. Other Git hosts

The Git layer is the same for every host: one SSH key or one token. The PR needs an adapter for each host's API.

| Host | PR adapter | Status |
|---|---|---|
| GitHub | `core/git/github.py` | Built and proven on CRC (2026-11-15) |
| Gitea | `core/git/gitea.py` | Built: the chart's stand-in |
| GitLab | — | Proposed: #286 PR-B, not built |
| Bitbucket Cloud and Data Center | — | Proposed: #286 PR-C, not built |

The account and the credentials of each host (bot account, deploy key, access token) are in [`docs/13`](13-crc-deployment.md), owner's step 3, "On each host". On every host, protect `main` so that only a merged PR changes it.

## 8. Troubleshooting

| What you see | Cause | Fix |
|---|---|---|
| The worker does not start, and its log names the SSH key or `known_hosts` | The key is missing, has a passphrase, does not parse, is not ed25519, or `ssh-publickey` is not its own; or the ConfigMap `cmapi-git-bot-known-hosts` is missing (`core/git/transport.py`, `load_credentials`) | Make the key again as in section 3, or load the host keys as in section 4 |
| A Git operation is refused for the host key | The host's key is not in `known_hosts`, or it changed | Compare with the host's published fingerprints (section 4). Add a key only after that check |
| `No user exists for uid ...` from ssh | The container runs as a UID with no `/etc/passwd` entry, outside CRI-O | cmapi sets nss_wrapper for its ssh processes when this happens. On OpenShift, CRI-O adds the entry, and `/etc/passwd` stays `0644` |
| A PR call answers 401 or 403 | The token expired or was revoked, or a permission of section 2 is missing | A new token (section 6) |
| Every request ends `failed` at push_branch, with "a head that is not cmapi's" | A person pushed to a `cmapi/*` branch | cmapi never overwrites a person's commit. Remove that branch on the host, then `:retry` the request |
| A request stays `merge_failed` | The merge was refused after the change was applied: a conflict, a moved folder, or the host refused | The reason is on the PR and on the request's timeline. Fix the cause, then `:retry`. cmapi never rolls the cluster back |
