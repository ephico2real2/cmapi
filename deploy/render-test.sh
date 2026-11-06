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
# Exactly four: two Deployments, each a migrate and a main container. One replaced by a pinned image would otherwise pass as
# "3 placeholders, 3 filled"; a Job or a sidecar on this image is a decision, and changes this number with it.
[ "$n" = 4 ] || bad "the source must hold the four cmapi image placeholders, got $n"
m=$(grep -rF "$GOOD" "$W/o1/components" "$W/o1/environment" | wc -l | tr -d ' ')
want "$n placeholders, $m filled" "$n placeholders, $m filled with the image" [ "$m" = "$n" ]
# Into a variable, not "| grep -q" in an if: under pipefail diff's own rc 1 made that pipeline false whatever it found.
extra=$(diff -r "$D/manifests/components" "$W/o1/components" | grep '^[<>]' | grep -vE 'image: |checksum/config: ')
if [ -n "$extra" ]; then bad "a line other than an image or the checksum changed: $extra"; else ok "only image and checksum lines changed"; fi
want "the mockup's own image is untouched" "the mockup's image changed" grep -q 'nginx-unprivileged@sha256:' "$W/o1/components/portal/10-mockup.yaml"
want "IMAGE names it" "IMAGE does not name it" [ "$(cat "$W/o1/IMAGE")" = "$GOOD" ]
if grep -rq 'sha256:DIGEST' "$W/o1"; then bad "a placeholder is left"; fi
# Refuses a tag without the flag, and leaves what was there.
"$R" kind "$GOOD" "$W/o2" >/dev/null; echo keep >"$W/o2/keep"
if quiet "$R" kind localhost/cmapi:dev "$W/o2"; then bad "a tag was accepted"; else want "a tag is refused and the last render stays" "the refusal deleted the last render" [ -e "$W/o2/keep" ]; fi
want "a tag with --allow-tag on kind" "--allow-tag refused on kind" quiet "$R" kind localhost/cmapi:dev "$W/o3" --allow-tag
grep -q 'image: localhost/cmapi:dev' "$W/o3/components/cmapi/20-api.yaml" || bad "--allow-tag did not fill the image"
# --allow-tag means a kind test, never a deployment.
cp -R "$D/manifests/environments/kind" "$D/manifests/environments/crc"
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
# checksum/config: the api's and the worker's pods restart when any of the three ConfigMaps changes, and nothing else does.
sums() { grep -h 'checksum/config:' "$1/components/cmapi/20-api.yaml" "$1/components/cmapi/30-worker.yaml" | sed -E 's/^ *checksum\/config: //'; }
A0=$(sums "$W/o1"); n=$(printf '%s\n' "$A0" | sort -u | wc -l | tr -d ' ')
want "both Deployments carry one value" "the Deployments' checksums differ: $A0" [ "$n" = 1 ]
[ "$(printf '%s\n' "$A0" | wc -l | tr -d ' ')" = 2 ] || bad "the checksum is not in both Deployments: $A0"
printf '%s\n' "$A0" | head -1 | grep -qE '^"[0-9a-f]{64}"$' || bad "the checksum is not a quoted SHA-256: $A0"
if grep -rq 'checksum/config\|CMAPI_CONFIG_CHECKSUM' "$W/o1/components/portal" "$W/o1/components/database-cnpg"; then bad "the checksum reached the mockup or the database"; else ok "the mockup and the database carry no checksum"; fi
want "the mockup's files are the source's" "a mockup file changed" diff -r "$D/manifests/components/portal" "$W/o1/components/portal"
"$R" kind "$GOOD" "$W/s1" >/dev/null; want "two renders are identical" "two renders differ" diff -r "$W/o1" "$W/s1"
# Not the path: the same files in another checkout give the same value, or a change of directory would restart the pods.
mkdir -p "$W/elsewhere/deploy"; cp "$HERE/render.sh" "$W/elsewhere/deploy/"; cp -R "$D/manifests" "$W/elsewhere/deploy/"
"$W/elsewhere/deploy/render.sh" kind "$GOOD" "$W/s2" >/dev/null; want "another checkout gives the same value" "the value depends on the path" [ "$(sums "$W/s2")" = "$A0" ]
# Pinned, so a change of method (and so a restart of every pod at the next deploy) is a decision, and macOS and Linux agree.
G=$D/manifests/environments/gold; mkdir -p "$G"; for c in env config trust; do printf 'metadata:\n  name: cmapi-%s\n' "$c" >"$G/$c.yaml"; done
"$R" gold "$GOOD" "$W/s3" >/dev/null; want "the method is the one recorded" "the checksum method changed: $(sums "$W/s3" | head -1)" [ "$(sums "$W/s3" | head -1)" = '"dff6162fb72d31b5c1b3d66e83a5df01f57cff923f79db8ea8bc53277b14aa15"' ]
rm -rf "$G"
for f in 10-env 20-config 30-trust; do
  cp "$D/manifests/environments/kind/$f.yaml" "$W/keep.yaml"; printf '# changed\n' >>"$D/manifests/environments/kind/$f.yaml"
  "$R" kind "$GOOD" "$W/s4" >/dev/null; B=$(sums "$W/s4")
  [ "$(printf '%s\n' "$B" | sort -u | wc -l | tr -d ' ')" = 1 ] && [ "$(printf '%s\n' "$B" | wc -l | tr -d ' ')" = 2 ] || bad "after changing $f the Deployments disagree: $B"
  want "a changed $f changes it in both Deployments" "a changed $f did not change the checksum" [ "$B" != "$A0" ]
  cp "$W/keep.yaml" "$D/manifests/environments/kind/$f.yaml"
done
# Moving bytes from one file's end to the next file's start changes it: the files are hashed one by one, not concatenated.
cp "$D/manifests/environments/kind/10-env.yaml" "$W/keep1.yaml"; cp "$D/manifests/environments/kind/20-config.yaml" "$W/keep2.yaml"
printf '# moved\n' >>"$D/manifests/environments/kind/10-env.yaml"; "$R" kind "$GOOD" "$W/s5" >/dev/null; M1=$(sums "$W/s5")
cp "$W/keep1.yaml" "$D/manifests/environments/kind/10-env.yaml"; { printf '# moved\n'; cat "$W/keep2.yaml"; } >"$D/manifests/environments/kind/20-config.yaml"; "$R" kind "$GOOD" "$W/s5" >/dev/null; M2=$(sums "$W/s5")
cp "$W/keep2.yaml" "$D/manifests/environments/kind/20-config.yaml"
want "bytes moved between two files change it" "bytes moved between two files did not change it" [ "$M1" != "$M2" ]
# An image change alone restarts through the image, not through this value.
"$R" kind "ghcr.io/ephico2real2/cmapi@sha256:$(printf 'd%.0s' {1..64})" "$W/s6" >/dev/null; want "another image keeps the value" "another image changed the checksum" [ "$(sums "$W/s6")" = "$A0" ]
# A placeholder left fails the render, and a ConfigMap no file declares stops it before the last render is touched.
"$R" kind "$GOOD" "$W/s7" >/dev/null; echo keep >"$W/s7/keep"
printf 'x: CMAPI_CONFIG_CHECKSUM\n' >"$D/manifests/components/cmapi/97-odd.yml"
if quiet "$R" kind "$GOOD" "$W/s7"; then bad "a checksum placeholder in a .yml passed"; else ok "a checksum placeholder the render cannot fill fails"; fi
rm -f "$D/manifests/components/cmapi/97-odd.yml"
want "a failed render leaves the last good one" "a failed render replaced the last good one" [ -e "$W/s7/keep" ]
want "and its IMAGE" "a failed render removed IMAGE" [ -f "$W/s7/IMAGE" ]
left=$(find "$W" -maxdepth 1 -name '.s7.*'); want "and nothing beside it" "a failed render left $left beside the out dir" [ -z "$left" ]
# The swap itself failing puts the last good render back.
REAL_MV=$(command -v mv); mkdir "$W/bin"
cat >"$W/bin/mv" <<STUB
#!/usr/bin/env bash
case "\$1" in */new) echo "mv: refused by the test" >&2; exit 1;; esac
exec "$REAL_MV" "\$@"
STUB
chmod +x "$W/bin/mv"
"$R" kind "$GOOD" "$W/s9" >/dev/null; echo keep >"$W/s9/keep"
if PATH="$W/bin:$PATH" quiet "$R" kind "$GOOD" "$W/s9"; then bad "a failed swap passed"; else want "a failed swap puts the last good render back" "a failed swap lost the last good render" [ -e "$W/s9/keep" ]; fi
# The out dir is what mkdir makes, not mktemp's 0700: a render other users or a container read must stay readable.
( umask 022; "$R" kind "$GOOD" "$W/s10" >/dev/null ); m=$(stat -c '%a' "$W/s10" 2>/dev/null || stat -f '%Lp' "$W/s10")
want "the out dir has the umask's mode" "the out dir is mode $m, not 755" [ "$m" = 755 ]
# A trailing slash, and "link/": the link is what is replaced, and what it pointed at stays.
"$R" kind "$GOOD" "$W/s11/" >/dev/null; "$R" kind "$GOOD" "$W/s11/" >/dev/null; want "a trailing slash renders" "a trailing slash did not render" [ -f "$W/s11/IMAGE" ]
"$R" kind "$GOOD" "$W/s12" >/dev/null; ln -s "$W/s12" "$W/s12link"
want "a link/ to a render renders" "a link/ to a render failed" quiet "$R" kind "$GOOD" "$W/s12link/"
want "and what it pointed at stays" "a link/ deleted what it pointed at" [ -f "$W/s12/IMAGE" ]
for f in 10-env 20-config 30-trust; do
  mv "$D/manifests/environments/kind/$f.yaml" "$W/keep.yaml"
  if quiet "$R" kind "$GOOD" "$W/o2"; then bad "a render without $f passed"; else want "no $f stops the render and the last render stays" "the failure without $f deleted the last render" [ -e "$W/o2/keep" ]; fi
  mv "$W/keep.yaml" "$D/manifests/environments/kind/$f.yaml"
done
cp "$D/manifests/environments/kind/10-env.yaml" "$D/manifests/environments/kind/11-env-again.yaml"
if quiet "$R" kind "$GOOD" "$W/s8"; then bad "two files declaring cmapi-env passed"; else ok "two files declaring one ConfigMap stop the render"; fi
rm -f "$D/manifests/environments/kind/11-env-again.yaml"
# It deletes only its own output: a directory it did not write is refused.
mkdir -p "$W/mine"; echo precious >"$W/mine/file"
if quiet "$R" kind "$GOOD" "$W/mine"; then bad "render.sh replaced a directory it did not write"; else want "a directory it did not write is refused" "refused, and deleted it anyway" [ -e "$W/mine/file" ]; fi
"$R" kind "$GOOD" "$D" >/dev/null 2>&1
want "deploy/ as the out dir does not delete deploy/" "deploy/ as the out dir deleted the manifests" [ -e "$D/manifests/README.md" ]
echo "render cases failed: $fails"; [ "$fails" = 0 ]
