#!/usr/bin/env bash
# deploy/render-test.sh: what deploy/render.sh must do, on a throwaway copy of deploy/ (it deletes directories, so never on this tree). No cluster.
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
fails=0; bad() { echo "  FAIL $*"; fails=$((fails+1)); }; ok() { echo "  ok   $*"; }
# want <said when it holds> <said when it does not> <command...>
want() { local yes=$1 no=$2; shift 2; if "$@"; then ok "$yes"; else bad "$no"; fi; }
quiet() { "$@" >/dev/null 2>&1; }
D=$W/repo/deploy; mkdir -p "$D"; cp "$HERE/render.sh" "$D/"; cp -R "$HERE/manifests" "$D/"
GOOD=ghcr.io/ephico2real2/cmapi@sha256:$(printf 'a%.0s' {1..64})
INTERNAL=image-registry.openshift-image-registry.svc:5000/cmapi/cmapi@sha256:$(printf 'b%.0s' {1..64})
R=$D/render.sh
# Fills exactly the placeholder: every other byte of every file is the source's.
"$R" kind "$GOOD" "$W/o1" >/dev/null || bad "a digest was refused"
n=$(grep -r "sha256:DIGEST" "$D/manifests/components" "$D/manifests/environments/kind" | wc -l | tr -d ' ')
[ "$n" -gt 0 ] || bad "the source holds no placeholder: this case proves nothing"
m=$(grep -rF "$GOOD" "$W/o1/components" "$W/o1/environment" | wc -l | tr -d ' ')
want "$n placeholders, $m filled" "$n placeholders, $m filled with the image" [ "$m" = "$n" ]
if diff -r "$D/manifests/components" "$W/o1/components" | grep '^[<>]' | grep -v 'image: ' | grep -q .; then bad "a line other than an image changed"; else ok "only image lines changed"; fi
want "the mockup's own image is untouched" "the mockup's image changed" grep -q 'nginx-unprivileged@sha256:' "$W/o1/components/portal/10-mockup.yaml"
want "IMAGE names it" "IMAGE does not name it" [ "$(cat "$W/o1/IMAGE")" = "$GOOD" ]
if grep -rq 'sha256:DIGEST' "$W/o1"; then bad "a placeholder is left"; fi
# Refuses a tag without the flag, and leaves what was there.
"$R" kind "$GOOD" "$W/o2" >/dev/null; echo keep >"$W/o2/keep"
if quiet "$R" kind localhost/cmapi:dev "$W/o2"; then bad "a tag was accepted"; else want "a tag is refused and the last render stays" "the refusal deleted the last render" [ -e "$W/o2/keep" ]; fi
want "a tag with --allow-tag on kind" "--allow-tag refused on kind" quiet "$R" kind localhost/cmapi:dev "$W/o3" --allow-tag
grep -q 'image: localhost/cmapi:dev' "$W/o3/components/cmapi/20-api.yaml" || bad "--allow-tag did not fill the image"
# --allow-tag means a kind test, never a deployment.
mkdir -p "$D/manifests/environments/crc"; cp "$D/manifests/environments/kind/10-env.yaml" "$D/manifests/environments/crc/"
if "$R" crc localhost/cmapi:dev "$W/o4" --allow-tag >/dev/null 2>&1; then bad "--allow-tag was accepted for crc"; else ok "--allow-tag is refused for anything but kind"; fi
# The internal registry's digest is what Wave 1 deploys, by digest; no flag that says "never a deployment".
want "the internal registry by digest" "the internal registry's digest needs --allow-tag" quiet "$R" crc "$INTERNAL" "$W/o5"
if "$R" crc "registry.example.com/x@sha256:$(printf 'c%.0s' {1..64})" "$W/o6" >/dev/null 2>&1; then bad "another registry was accepted"; else ok "another registry is refused"; fi
# The flag anywhere; the out dir is the out dir.
"$R" kind localhost/cmapi:dev --allow-tag "$W/o7" >/dev/null 2>&1
want "--allow-tag before the out dir" "--allow-tag before the out dir: the out dir was ignored" [ -f "$W/o7/IMAGE" ]
# A partly written directory from an earlier run is replaced, leftovers and all.
"$R" kind "$GOOD" "$W/o8" >/dev/null; printf 'image: ghcr.io/ephico2real2/cmapi@sha256:DIGEST\n' >"$W/o8/components/cmapi/99-leftover.yaml"; rm -f "$W/o8/IMAGE"
want "a partly written render is rendered again" "a partly written render was refused" quiet "$R" kind "$GOOD" "$W/o8"
want "and its leftovers are gone" "a partly written render's leftover stayed" [ ! -e "$W/o8/components/cmapi/99-leftover.yaml" ]
# A placeholder the sed cannot fill fails, in any file.
printf 'image: ghcr.io/x@sha256:DIGEST\n' >"$D/manifests/components/cmapi/98-odd.yml"
if "$R" kind "$GOOD" "$W/o9" >/dev/null 2>&1; then bad "a placeholder in a .yml passed"; else ok "a placeholder the render cannot fill fails"; fi
rm -f "$D/manifests/components/cmapi/98-odd.yml"
# It deletes only its own output: a directory it did not write is refused.
mkdir -p "$W/mine"; echo precious >"$W/mine/file"
if quiet "$R" kind "$GOOD" "$W/mine"; then bad "render.sh replaced a directory it did not write"; else want "a directory it did not write is refused" "refused, and deleted it anyway" [ -e "$W/mine/file" ]; fi
"$R" kind "$GOOD" "$D" >/dev/null 2>&1
want "deploy/ as the out dir does not delete deploy/" "deploy/ as the out dir deleted the manifests" [ -e "$D/manifests/README.md" ]
echo "render cases failed: $fails"; [ "$fails" = 0 ]
