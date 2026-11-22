#!/usr/bin/env python3
"""Create an owner's CRC token Secret from a hidden terminal prompt. Standard library only."""
import argparse
import base64
import getpass
import json
import subprocess
import sys
import warnings


def stop(message):
    sys.exit("STOP: " + message)


def oc(args, payload=None):
    try:
        # Capture diagnostics too: a failed create can repeat submitted Secret data.
        return subprocess.run(["oc"] + args, input=payload, capture_output=True)
    except FileNotFoundError:
        stop("oc is not installed or not on PATH.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("ghcr", "git-bot"))
    parser.add_argument("github_user", nargs="?", help="account that owns the GHCR token")
    args = parser.parse_args()
    if args.kind == "ghcr" and (not args.github_user or args.github_user == "<github-user>"):
        parser.error("ghcr needs the token's GitHub account name")
    if args.kind == "git-bot" and args.github_user:
        parser.error("git-bot takes no account name")

    secret = "cmapi-ghcr-pull" if args.kind == "ghcr" else "cmapi-git-bot"
    if oc(["whoami"]).returncode:
        stop("oc is not logged in. Run oc login -u kubeadmin https://api.crc.testing:6443 and use its password prompt.")
    existing = oc(["get", "secret", secret, "-n", "cmapi", "--ignore-not-found", "-o", "name"])
    if existing.returncode:
        stop("oc could not check the Secret. Check the connection and permission to read Secrets in namespace cmapi.")
    if existing.stdout.strip():
        stop(f"Secret {secret} already exists. To replace it, run: oc delete secret {secret} -n cmapi ; then rerun this command.")

    if not sys.stdin.isatty():
        stop("Run this command in a terminal (Terminal.app); it needs a hidden token prompt.")
    # getpass normally falls back to echoed input if it cannot disable echo. Refuse that.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            token = getpass.getpass(f"{secret} token (hidden): ")
        except (getpass.GetPassWarning, EOFError, KeyboardInterrupt):
            stop("Hidden token input unavailable or cancelled. Run again in Terminal.app.")
    if not token:
        stop("The token is empty; no Secret was created. Rerun and enter the token at the hidden prompt.")

    create = ["create", "secret", "generic", secret, "-n", "cmapi"]
    if args.kind == "ghcr":
        auth = base64.b64encode(f"{args.github_user}:{token}".encode()).decode()
        payload = json.dumps({"auths": {"ghcr.io": {"auth": auth}}}).encode()
        create += ["--type=kubernetes.io/dockerconfigjson", "--from-file=.dockerconfigjson=/dev/stdin"]
    else:
        payload = token.encode()
        create += ["--from-file=token=/dev/stdin"]
    if oc(create, payload).returncode:
        stop(f"oc could not create Secret {secret}. Check login and namespace permissions. If it already exists, replace it with: oc delete secret {secret} -n cmapi ; then rerun this command.")
    print(f"Created Secret {secret} in namespace cmapi.")


if __name__ == "__main__":
    main()
